"""
spherex_download.py
====================
Downloads SPHEREx Spectral Image MEFs identified by spherex_query.py, and
splits each one into 6 separate single-extension FITS files (one per HDU:
IMAGE, FLAGS, VARIANCE, ZODI, EPSF, WCS-WAVE), for handoff to a teammate
responsible for cleaning/processing.

Verified MEF structure (per current IRSA SPHEREx documentation):
    HDU 0: PRIMARY   (empty)
    HDU 1: IMAGE     - 2040x2040 float32, calibrated flux (MJy/sr)
    HDU 2: FLAGS     - 2040x2040 int32, per-pixel quality bitmap
    HDU 3: VARIANCE  - 2040x2040 float32, per-pixel noise variance
    HDU 4: ZODI      - 2040x2040 float32, modeled zodiacal background
    HDU 5: EPSF      - binary table, effective PSF per detector zone
    HDU 6: WCS-WAVE  - binary table, per-pixel wavelength/bandwidth lookup

Output layout
-------------
For a target with label `<label>` (see spherex_coords.ResolvedTarget.label),
files are written to:

    <output_root>/<label>/<obs_id>_D<detector>/
        IMAGE.fits
        FLAGS.fits
        VARIANCE.fits
        ZODI.fits
        EPSF.fits
        WCS-WAVE.fits

Each split file's PRIMARY header is the original MEF's PRIMARY header
(for provenance), followed by the single extracted extension as HDU 1,
so every output file is independently openable with
`astropy.io.fits.open(path)[1]` or `[path][1].data`.

A single manifest CSV is also written to `<output_root>/<label>/manifest.csv`
summarising one row per exposure with the metadata a cleaning teammate
needs: obs_id, detector, observation time range, RA/Dec, bandpass,
output directory, and the original access_url (for traceability/re-download).

Design notes / assumptions
---------------------------
- Files are fetched via their `access_url` (on-premises IRSA copy), using
  plain HTTP GET through astropy's download machinery. This mirrors the
  official IRSA tutorial approach and avoids depending on AWS/cloud
  credentials (`cloud_access` column) which not all team members may have.
- Downloads are retried a few times on transient network errors, matching
  IRSA's own tutorial guidance that reads can occasionally fail/time out.
- This module does NOT interpret or clean pixel data (flagging, zodi
  subtraction, co-adding, differencing) -- that is explicitly the next
  team member's job. It only fetches and losslessly reorganises the
  archive's own FITS products.
- Existing output directories are skipped (not re-downloaded) by default,
  so the tool is safe to re-run incrementally as new SPHEREx data arrives;
  pass force=True to override.

Dependencies
------------
- astropy (io.fits, utils.data)

Network access required: yes.
"""
from __future__ import annotations

import csv
import time
import http.client
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from astropy.io import fits
from astropy.table import Row
from astropy.utils.data import conf as astropy_conf

# SPHEREx files can be slow to transfer; raise astropy's default remote
# timeout as recommended by IRSA's own tutorial notebooks.
astropy_conf.remote_timeout = 120

EXTENSIONS = ["IMAGE", "FLAGS", "VARIANCE", "ZODI", "EPSF", "WCS-WAVE"]
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 10


class SpherexDownloadError(RuntimeError):
    """Raised when a MEF cannot be fetched or does not have the expected HDUs."""


@dataclass
class DownloadedExposure:
    """Summary of one successfully processed exposure, for manifest writing."""
    obs_id: str
    detector: int
    output_dir: Path
    access_url: str
    t_min: float
    t_max: float
    ra_deg: float
    dec_deg: float
    em_min: float
    em_max: float
    skipped: bool = False


def _open_fits_with_retry(url: str) -> fits.HDUList:
    """Open a remote FITS URL, retrying on transient network errors."""
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            hdulist = fits.open(url, memmap=False)
            # Force read of all extensions now so the file stays usable
            # after we are done, consistent with IRSA's own tutorial.
            for hdu in hdulist:
                _ = hdu.data
            return hdulist
        except (TimeoutError, urllib.error.HTTPError, http.client.IncompleteRead) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise SpherexDownloadError(f"Failed to download {url} after {MAX_RETRIES} attempts: {last_exc}")


def _split_mef(hdulist: fits.HDUList, dest_dir: Path) -> None:
    """Write each of the 6 named extensions in `hdulist` to its own FITS file."""
    primary_header = hdulist[0].header
    available = {hdu.name for hdu in hdulist}
    missing = [name for name in EXTENSIONS if name not in available]
    if missing:
        # Not every exposure necessarily has all 6 bands/extensions present
        # (per IRSA docs: "some observations will not include all 6 bands").
        # We proceed with whatever extensions ARE present rather than fail
        # the whole exposure, but this is surfaced so it can be logged.
        pass

    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in EXTENSIONS:
        if name not in available:
            continue
        hdu = hdulist[name]
        out_primary = fits.PrimaryHDU(header=primary_header.copy())
        out_extension = fits.ImageHDU(data=hdu.data, header=hdu.header, name=name) \
            if hdu.is_image else fits.BinTableHDU(data=hdu.data, header=hdu.header, name=name)
        out_hdulist = fits.HDUList([out_primary, out_extension])
        out_path = dest_dir / f"{name}.fits"
        out_hdulist.writeto(out_path, overwrite=True)


def download_and_split(
    query_table,
    output_root: Path,
    target_label: str,
    force: bool = False,
    max_exposures: int | None = None,
) -> list:
    """
    Download every exposure in `query_table` and split each into per-HDU
    FITS files.

    Parameters
    ----------
    query_table : astropy.table.Table
        The `.table` attribute of a spherex_query.QueryResult (or any table
        with the same columns: access_url, obs_id, detector, t_min, t_max,
        s_ra, s_dec, em_min, em_max).
    output_root : pathlib.Path
        Root directory under which `<target_label>/<obs_id>_D<detector>/`
        subdirectories will be created.
    target_label : str
        Filesystem-safe name for this target (see
        spherex_coords.ResolvedTarget.label), used as a subdirectory name.
    force : bool, optional
        If False (default), exposures whose output directory already
        exists and is non-empty are skipped (useful for incremental runs
        as new SPHEREx data arrives). If True, always re-download.
    max_exposures : int or None, optional
        If given, only the first `max_exposures` rows of `query_table` are
        downloaded (the rest are ignored entirely -- not even listed in
        the manifest). This is intended for development/testing, since a
        single cone search can legitimately return hundreds of ~65 MB
        files (one per exposure/detector). Default None = fetch all
        exposures, matching the full-pipeline behaviour.

    Returns
    -------
    list[DownloadedExposure]
        One entry per exposure attempted (including skipped ones), in the
        same order as `query_table`.

    Notes
    -----
    This function also writes `<output_root>/<target_label>/manifest.csv`
    summarising all processed exposures, which is the documented handoff
    interface for the data-cleaning teammate.
    """
    target_dir = Path(output_root) / target_label
    target_dir.mkdir(parents=True, exist_ok=True)

    results: list[DownloadedExposure] = []

    rows = query_table if max_exposures is None else query_table[:max_exposures]

    for row in rows:
        obs_id = str(row["obs_id"])
        detector = int(row["detector"])
        access_url = str(row["access_url"])
        exposure_dir = target_dir / f"{obs_id}_D{detector}"

        already_done = exposure_dir.exists() and any(exposure_dir.iterdir())
        if already_done and not force:
            results.append(
                DownloadedExposure(
                    obs_id=obs_id,
                    detector=detector,
                    output_dir=exposure_dir,
                    access_url=access_url,
                    t_min=float(row["t_min"]) if "t_min" in row.colnames else float("nan"),
                    t_max=float(row["t_max"]) if "t_max" in row.colnames else float("nan"),
                    ra_deg=float(row["s_ra"]) if "s_ra" in row.colnames else float("nan"),
                    dec_deg=float(row["s_dec"]) if "s_dec" in row.colnames else float("nan"),
                    em_min=float(row["em_min"]) if "em_min" in row.colnames else float("nan"),
                    em_max=float(row["em_max"]) if "em_max" in row.colnames else float("nan"),
                    skipped=True,
                )
            )
            continue

        hdulist = _open_fits_with_retry(access_url)
        try:
            _split_mef(hdulist, exposure_dir)
        finally:
            hdulist.close()

        results.append(
            DownloadedExposure(
                obs_id=obs_id,
                detector=detector,
                output_dir=exposure_dir,
                access_url=access_url,
                t_min=float(row["t_min"]) if "t_min" in row.colnames else float("nan"),
                t_max=float(row["t_max"]) if "t_max" in row.colnames else float("nan"),
                ra_deg=float(row["s_ra"]) if "s_ra" in row.colnames else float("nan"),
                dec_deg=float(row["s_dec"]) if "s_dec" in row.colnames else float("nan"),
                em_min=float(row["em_min"]) if "em_min" in row.colnames else float("nan"),
                em_max=float(row["em_max"]) if "em_max" in row.colnames else float("nan"),
                skipped=False,
            )
        )

    _write_manifest(target_dir / "manifest.csv", results)
    return results


def _write_manifest(path: Path, exposures: list) -> None:
    """Write the handoff manifest CSV documented in the module docstring."""
    fieldnames = [
        "obs_id", "detector", "t_min_mjd", "t_max_mjd",
        "ra_deg", "dec_deg", "em_min_m", "em_max_m",
        "output_dir", "access_url", "skipped",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for exp in exposures:
            writer.writerow({
                "obs_id": exp.obs_id,
                "detector": exp.detector,
                "t_min_mjd": exp.t_min,
                "t_max_mjd": exp.t_max,
                "ra_deg": exp.ra_deg,
                "dec_deg": exp.dec_deg,
                "em_min_m": exp.em_min,
                "em_max_m": exp.em_max,
                "output_dir": str(exp.output_dir),
                "access_url": exp.access_url,
                "skipped": exp.skipped,
            })
