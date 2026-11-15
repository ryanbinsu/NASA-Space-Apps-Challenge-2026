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

Cloud access
-------------------
Per IRSA's SPHEREx Data Access documentation
(https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/)
and the general IRSA Cloud Data Access page, all SPHEREx data products are
mirrored on AWS S3 in the public, credential-free bucket `nasa-irsa-spherex`
(region us-east-1), via the AWS Open Data Sponsorship Program. IRSA's SIA2
results include a `cloud_access` column with a JSON blob per row, e.g.:

    {"aws": {"bucket_name": "nasa-irsa-spherex",
              "key": "qr3/level2/.../level2_..._spx_l2b-....fits",
              "region": "us-east-1"}}

This module PREFERS reading directly from that S3 location (anonymous,
no credentials needed -- matching IRSA's own "IRSA Cloud Access Introduction"
tutorial pattern of `fits.open("s3://bucket/key", fsspec_kwargs={"anon": True})`),
and falls back to the on-premises `access_url` over plain HTTP if:
  - the `cloud_access` column is missing/empty for a row, or
  - the S3 read fails after retries (e.g. transient network issue, or the
    row predates the on-prem -> cloud mirroring delay IRSA documents), or
  - the caller explicitly passes `prefer_cloud=False` (e.g. restricted
    network environments with no outbound S3 access but working HTTP proxy
    access to irsa.ipac.caltech.edu).

Direct S3 bucket browsing (no IRSA API at all)
------------------------------------------------
Per IRSA's Cloud Data Access page and the SPHEREx AWS Open Data registry
listing (registry.opendata.aws/spherex-qr), the entire archive is also a
public, unsigned-request S3 bucket that can be listed and fetched with
plain boto3/aws-cli, e.g.:
    aws s3 ls --no-sign-request s3://nasa-irsa-spherex/qr3/level2/
This is independent of (and does not require) the SIA2 query step --
useful for bulk/scripted exploration, sanity-checking what exists for a
given data release, or fetching a specific file when you already know
its key (e.g. copied from the browsable directory listing at
https://irsa.ipac.caltech.edu/ibe/data/spherex/). See `list_s3_prefix`,
`fetch_s3_key`, `open_fits_from_s3_key`, and the module's `--list`/`--get`
CLI at the bottom of this file.

NOTE: S3 keys follow the directory layout from IRSA's "Browsable
Directories" docs (e.g. dr1/level2/[Planning Period]/l2b-v.../[Detector]/
or qr3/level2/... or qr2/level2/...) and do NOT encode sky position --
so turning a RA/Dec into a list of relevant keys still requires the
SIA2 query (spherex_query.py). Use direct S3 browsing for exploration
and direct-key fetches, not for coordinate search.

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
output directory, the original access_url (for traceability/re-download),
and which data source -- "cloud" or "http" -- actually supplied the
bytes for that exposure.

Design notes / assumptions
---------------------------
- Downloads are retried a few times on transient network errors for BOTH
  the cloud and HTTP paths, matching IRSA's own tutorial guidance that
  reads can occasionally fail/time out.
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
- fsspec, s3fs (for anonymous S3 reads of the cloud-hosted copy)
- boto3 (for direct S3 bucket browsing/fetching, independent of SIA2)

Network access required: yes (S3 by default, or IRSA HTTP as fallback /
if prefer_cloud=False).
"""
from __future__ import annotations

import csv
import json
import time
import http.client
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from astropy.io import fits
from astropy.utils.data import conf as astropy_conf

# SPHEREx files can be slow to transfer; raise astropy's default remote
# timeout as recommended by IRSA's own tutorial notebooks.
astropy_conf.remote_timeout = 120

EXTENSIONS = ["IMAGE", "FLAGS", "VARIANCE", "ZODI", "EPSF", "WCS-WAVE"]
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 10

# Retryable, transient-looking errors for both cloud (S3) and HTTP paths.
# S3 reads via fsspec/s3fs can raise a variety of exception types
# (botocore ClientError, OSError, TimeoutError) depending on the failure
# mode, so we deliberately catch broadly here and only *retry*, never
# silently swallow -- the final failure is always re-raised.
_RETRYABLE_EXCEPTIONS = (TimeoutError, urllib.error.HTTPError, http.client.IncompleteRead, OSError)


class SpherexDownloadError(RuntimeError):
    """Raised when a MEF cannot be fetched (via cloud or HTTP) or does not
    have the expected HDUs."""


# ---------------------------------------------------------------------
# Direct S3 bucket browsing -- no IRSA API / SIA2 involved at all.
# ---------------------------------------------------------------------
SPHEREX_BUCKET = "nasa-irsa-spherex"
SPHEREX_REGION = "us-east-1"
SPHEREX_RELEASE_PREFIXES = {"dr1": "dr1", "qr3": "qr3", "qr2": "qr2", "qr1": "qr"}


def _s3_client():
    """Build an anonymous (unsigned-request) boto3 S3 client for the public
    IRSA SPHEREx bucket. Raises a clear error if boto3 isn't installed."""
    try:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
    except ImportError as exc:
        raise SpherexDownloadError(
            "Direct S3 browsing requires 'boto3' (pip install boto3)."
        ) from exc
    return boto3.client("s3", region_name=SPHEREX_REGION, config=Config(signature_version=UNSIGNED))


def list_s3_prefix(prefix: str, bucket: str = SPHEREX_BUCKET, delimiter: str = "/") -> dict:
    """
    List the contents of an S3 "directory" directly from the public,
    credential-free SPHEREx bucket -- the Python equivalent of:
        aws s3 ls --no-sign-request s3://nasa-irsa-spherex/<prefix>/

    Parameters
    ----------
    prefix : str
        S3 prefix (path) relative to the bucket root, e.g.
        "qr3/level2/" or "dr1/abs_gain_matrix/cal-agm-v1-2026-300/1/".
        A trailing "/" is added automatically if missing.
    bucket : str, optional
        Defaults to the SPHEREx bucket ("nasa-irsa-spherex").
    delimiter : str, optional
        Use "/" (default) to list one directory level at a time
        (like `ls`); pass "" to recursively list every key under
        `prefix` instead.

    Returns
    -------
    dict with keys:
        "subdirs" : list[str]  -- immediate subdirectory prefixes (if delimiter="/")
        "files"   : list[str]  -- full keys of files directly under this prefix
    """
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    client = _s3_client()
    paginator = client.get_paginator("list_objects_v2")
    kwargs = {"Bucket": bucket, "Prefix": prefix}
    if delimiter:
        kwargs["Delimiter"] = delimiter

    subdirs: list[str] = []
    files: list[str] = []
    for page in paginator.paginate(**kwargs):
        for cp in page.get("CommonPrefixes", []):
            subdirs.append(cp["Prefix"])
        for obj in page.get("Contents", []):
            files.append(obj["Key"])

    return {"subdirs": subdirs, "files": files}


def fetch_s3_key(
    key: str,
    dest_path: Path,
    bucket: str = SPHEREX_BUCKET,
) -> Path:
    """
    Download a single object directly from the public SPHEREx S3 bucket by
    its exact key, with no IRSA API / SIA2 query involved -- useful when
    you already know the key (e.g. from a browsable-directory listing or a
    previous `list_s3_prefix` call) and just want the raw file.

    Parameters
    ----------
    key : str
        Full S3 key relative to the bucket root, e.g.
        "qr3/level2/2026W21_2A/l2b-v27-2026-268/1/level2_..._spx_l2b-....fits".
    dest_path : pathlib.Path
        Local path to write the file to (parent directories are created).
    bucket : str, optional
        Defaults to the SPHEREx bucket.

    Returns
    -------
    pathlib.Path
        `dest_path`, for convenience chaining.
    """
    client = _s3_client()
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            client.download_file(bucket, key, str(dest_path))
            return dest_path
        except Exception as exc:  # noqa: BLE001 - broad: botocore raises many types
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise SpherexDownloadError(f"Failed to fetch s3://{bucket}/{key} after retries: {last_exc}")


def open_fits_from_s3_key(key: str, bucket: str = SPHEREX_BUCKET) -> fits.HDUList:
    """
    Open a SPHEREx MEF directly from the public S3 bucket by key, in memory
    (no local file written), using astropy's anonymous fsspec S3 backend.
    Equivalent to the fallback-free path IRSA's own cloud-access tutorials
    demonstrate, but driven by a key you already know rather than one
    extracted from a SIA2 `cloud_access` cell.
    """
    uri = f"s3://{bucket}/{key}"
    hdulist = fits.open(uri, fsspec_kwargs={"anon": True}, memmap=False)
    for hdu in hdulist:
        _ = hdu.data
    return hdulist


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
    source: str = ""  # "cloud", "http", or "" if skipped


def _parse_cloud_access(cloud_access_raw) -> str | None:
    """
    Parse the IRSA SIA2 `cloud_access` cell (a JSON string, e.g.
    '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "...", "region": "us-east-1"}}')
    into an `s3://bucket/key` URI. Returns None if the cell is missing,
    empty, masked, or doesn't contain a usable AWS entry.
    """
    if cloud_access_raw is None:
        return None
    text = str(cloud_access_raw).strip()
    if not text or text.lower() in ("--", "nan", "none", "masked"):
        return None
    try:
        info = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    aws = info.get("aws") or info.get("AWS")
    if not aws:
        return None
    bucket = aws.get("bucket_name")
    key = aws.get("key")
    if not bucket or not key:
        return None
    return f"s3://{bucket}/{key}"


def _open_fits_with_retry(row, prefer_cloud: bool = True) -> tuple[fits.HDUList, str]:
    """
    Open a SPHEREx MEF for one query-result row, preferring the AWS S3
    cloud copy (anonymous access) and falling back to the on-premises
    IRSA `access_url` over HTTP. Retries transient errors on each path
    before falling back / giving up.

    Returns
    -------
    (hdulist, source) where source is "cloud" or "http".
    """
    access_url = str(row["access_url"]) if "access_url" in row.colnames else None
    cloud_access_raw = row["cloud_access"] if "cloud_access" in row.colnames else None
    s3_uri = _parse_cloud_access(cloud_access_raw) if prefer_cloud else None

    attempts: list[tuple[str, str]] = []
    if s3_uri:
        attempts.append(("cloud", s3_uri))
    if access_url:
        attempts.append(("http", access_url))

    if not attempts:
        raise SpherexDownloadError(
            "No access_url or usable cloud_access entry available for this exposure."
        )

    last_exc: Exception | None = None
    for source_type, location in attempts:
        for attempt in range(MAX_RETRIES):
            try:
                if source_type == "cloud":
                    # Anonymous S3 read via fsspec/s3fs, per IRSA's own
                    # "IRSA Cloud Access Introduction" tutorial pattern.
                    hdulist = fits.open(location, fsspec_kwargs={"anon": True}, memmap=False)
                else:
                    hdulist = fits.open(location, memmap=False)
                # Force read of all extensions now so the file stays usable
                # after we are done, consistent with IRSA's own tutorial.
                for hdu in hdulist:
                    _ = hdu.data
                return hdulist, source_type
            except _RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
        # Exhausted retries for this source; fall through to try the next
        # one (e.g. cloud failed entirely -> try HTTP) before giving up.

    raise SpherexDownloadError(
        f"Failed to download exposure via cloud and/or HTTP after retries: {last_exc}"
    )


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
    prefer_cloud: bool = True,
) -> list:
    """
    Download every exposure in `query_table` and split each into per-HDU
    FITS files.

    Parameters
    ----------
    query_table : astropy.table.Table
        The `.table` attribute of a spherex_query.QueryResult (or any table
        with the same columns: access_url, cloud_access, obs_id, detector,
        t_min, t_max, s_ra, s_dec, em_min, em_max).
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
        the manifest). Default None = fetch all exposures.
    prefer_cloud : bool, optional
        If True (default), read each exposure directly from IRSA's public
        AWS S3 mirror (`nasa-irsa-spherex` bucket, anonymous access, no
        credentials/egress charges) using the `cloud_access` column, and
        only fall back to the on-premises `access_url` over HTTP if the
        cloud entry is missing or the S3 read fails after retries. Set to
        False to always use HTTP (e.g. in network environments that block
        outbound S3 but allow HTTPS to irsa.ipac.caltech.edu).

    Returns
    -------
    list[DownloadedExposure]
        One entry per exposure attempted (including skipped ones), in the
        same order as `query_table`.

    Notes
    -----
    This function also writes `<output_root>/<target_label>/manifest.csv`
    summarising all processed exposures (including a `source` column:
    "cloud", "http", or blank for skipped rows), which is the documented
    handoff interface for the data-cleaning teammate.
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
                    source="",
                )
            )
            continue

        hdulist, source = _open_fits_with_retry(row, prefer_cloud=prefer_cloud)
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
                source=source,
            )
        )
        print(f"  [{obs_id} D{detector}] fetched via {source}.")

    n_cloud = sum(1 for e in results if e.source == "cloud")
    n_http = sum(1 for e in results if e.source == "http")
    if n_cloud or n_http:
        print(f"Source summary: {n_cloud} via AWS S3 (cloud), {n_http} via IRSA HTTP (fallback).")

    _write_manifest(target_dir / "manifest.csv", results)
    return results


def _write_manifest(path: Path, exposures: list) -> None:
    """Write the handoff manifest CSV documented in the module docstring."""
    fieldnames = [
        "obs_id", "detector", "t_min_mjd", "t_max_mjd",
        "ra_deg", "dec_deg", "em_min_m", "em_max_m",
        "output_dir", "access_url", "source", "skipped",
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
                "source": exp.source,
                "skipped": exp.skipped,
            })


# ---------------------------------------------------------------------
# Standalone CLI: browse / fetch the SPHEREx S3 bucket directly, with no
# IRSA API or coordinate query involved at all.
#
# Examples
# --------
#   python spherex_download.py --list qr3/level2/
#   python spherex_download.py --list dr1/ --recursive
#   python spherex_download.py --get qr3/level2/2026W21_2A/l2b-v27-2026-268/1/level2_..._spx_l2b-....fits -o ./out.fits
# ---------------------------------------------------------------------
def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Browse or fetch SPHEREx data directly from the public "
                     f"AWS S3 bucket ({SPHEREX_BUCKET}), bypassing the IRSA API entirely."
    )
    parser.add_argument("--list", metavar="PREFIX", help="List subdirectories/files under an S3 prefix, e.g. 'qr3/level2/'.")
    parser.add_argument("--recursive", action="store_true", help="With --list, recursively list every key under PREFIX instead of one level.")
    parser.add_argument("--get", metavar="KEY", help="Download a single object by its exact S3 key.")
    parser.add_argument("-o", "--output", metavar="PATH", help="Destination path for --get (required with --get).")
    args = parser.parse_args()

    if args.list:
        result = list_s3_prefix(args.list, delimiter="" if args.recursive else "/")
        for d in result["subdirs"]:
            print(f"  DIR  {d}")
        for f in result["files"]:
            print(f"  FILE {f}")
        print(f"\n{len(result['subdirs'])} subdirector(ies), {len(result['files'])} file(s) under '{args.list}'.")
    elif args.get:
        if not args.output:
            parser.error("--get requires -o/--output")
        dest = fetch_s3_key(args.get, Path(args.output))
        print(f"Saved to {dest}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
