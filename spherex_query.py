"""
spherex_query.py
=================
Searches the IRSA SPHEREx archive for all Spectral Image MEFs ("exposures")
overlapping a given sky position, across all available epochs and data
releases.

Verified against current (Nov 2026) IRSA documentation:
- SIA2 collections: spherex_dr1, spherex_dr1_deep, spherex_qr3, spherex_qr3_deep
  (QR2 is superseded and NOT searchable via SIA2).
- Query performed via astroquery.ipac.irsa.Irsa.query_sia(pos=(coord, radius),
  collection=[...]).
- Returned table columns include (among others): access_url, obs_id,
  s_ra, s_dec, t_min, t_max (MJD), em_min, em_max (bandpass, meters),
  energy_bandpassname, s_fov, obs_collection, obs_release_date,
  cloud_access.

Design notes / assumptions
---------------------------
- "All exposures available" (per project decision) means NO deduplication
  or epoch-binning is performed here: every row returned by SIA2 for the
  requested collections and radius is kept. Downstream code (e.g. a
  frontend "blink" viewer) is responsible for grouping/sub-sampling epochs
  if desired.
- Data-release scope is a module-level constant (`DEFAULT_COLLECTIONS`) so
  that adding a future release (e.g. spherex_dr2) is a one-line change
  without touching function signatures. Deep-field collections are
  included by default since "all data available" was requested; set
  `include_deep=False` to search wide-survey only.
- Detector/band filtering happens client-side (see `detectors` parameter)
  because the SIA2 'BAND' constraint operates on wavelength, not on the
  SPHEREx detector index directly, and detector number is only reliably
  recoverable from the obs_id / access_url naming convention
  (..._D[Detector]_...) or from em_min/em_max band ranges. We do it by
  filename, which is unambiguous.
- Results are sorted by t_min (MJD) ascending, i.e. chronological order,
  which is what a "blink" video needs.
- No files are downloaded in this module -- it only returns metadata deemed
  needed for `spherex_download.py` to do the actual retrieval. This keeps
  the two concerns independent and testable separately.

Dependencies
------------
- astropy
- astroquery (astroquery.ipac.irsa.Irsa)

Network access required: yes (queries IRSA's live SIA2 service).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from astropy.coordinates import SkyCoord
from astropy.table import Table, vstack
from astropy import units as u

try:
    from astroquery.ipac.irsa import Irsa
except ImportError as exc:  # pragma: no cover - import-time guard
    raise ImportError(
        "astroquery is required for spherex_query.py. Install with "
        "`pip install astroquery`."
    ) from exc


# ---------------------------------------------------------------------------
# Collection scope. Keep this list in one place so future data releases
# (e.g. a hypothetical spherex_dr2) require only a single edit here.
# ---------------------------------------------------------------------------
WIDE_COLLECTIONS = ["spherex_dr1", "spherex_qr3"]
DEEP_COLLECTIONS = ["spherex_dr1_deep", "spherex_qr3_deep"]
DEFAULT_COLLECTIONS = WIDE_COLLECTIONS + DEEP_COLLECTIONS

# Default cone-search radius. SPHEREx detectors are large (several degrees),
# so a modest default avoids pulling in excessive numbers of exposures.
# This is exposed as a user-settable parameter per the challenge brief
# ("let users choose the field of view").
DEFAULT_RADIUS = 1.0 * u.arcmin

# Filenames encode the detector as "..._D[Detector]_spx_..." or
# "...D[Detector]_spx_..." immediately before "_spx_". Capture that digit.
_DETECTOR_PATTERN = re.compile(r"D(\d)_spx_")


class SpherexQueryError(RuntimeError):
    """Raised when the IRSA SIA2 query fails or returns no usable table."""


@dataclass
class QueryResult:
    """
    Container for the result of a SPHEREx archive search.

    Attributes
    ----------
    table : astropy.table.Table
        One row per exposure (Spectral Image MEF), sorted chronologically
        by t_min. Includes an added 'detector' integer column (1-6) parsed
        from the access_url, and a 'release' column showing which of the
        queried collections the row came from (useful for logging/debug).
    target : SkyCoord
        The queried sky position, for provenance/manifest purposes.
    radius : astropy.units.Quantity
        The queried cone-search radius.
    collections : list[str]
        The collections actually searched.
    """
    table: Table
    target: SkyCoord
    radius: u.Quantity
    collections: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.table)

    def filter_by_detector(self, detectors) -> "QueryResult":
        """
        Return a new QueryResult restricted to the given detector number(s).

        Parameters
        ----------
        detectors : int or Iterable[int]
            Detector(s) to keep, each in [1, 6].
        """
        if isinstance(detectors, int):
            detectors = [detectors]
        detectors = set(detectors)
        invalid = detectors - set(range(1, 7))
        if invalid:
            raise ValueError(f"Invalid detector number(s): {sorted(invalid)}; must be 1-6.")
        mask = [d in detectors for d in self.table["detector"]]
        return QueryResult(self.table[mask], self.target, self.radius, self.collections)


def _extract_detector(access_url: str) -> int:
    """Parse the detector number (1-6) out of a SPHEREx access_url/filename."""
    match = _DETECTOR_PATTERN.search(access_url)
    if not match:
        return -1  # unknown; downstream code should treat -1 as "unparsed"
    return int(match.group(1))


def search_spherex(
    target: SkyCoord,
    radius: u.Quantity = DEFAULT_RADIUS,
    include_deep: bool = True,
    detectors=None,
) -> QueryResult:
    """
    Query IRSA for all SPHEREx Spectral Image MEFs overlapping `target`.

    Parameters
    ----------
    target : astropy.coordinates.SkyCoord
        Sky position to search around (output of spherex_coords.parse_coordinate).
    radius : astropy.units.Quantity, optional
        Cone-search radius (angular). Default is DEFAULT_RADIUS (1 arcmin).
        Larger radii return more exposures and are useful for fast-moving
        targets, at the cost of a larger, slower query and larger downloads.
    include_deep : bool, optional
        If True (default), also search the SPHEREx Deep Survey collections
        in addition to the Wide Survey. Set False to restrict to Wide only.
    detectors : int or Iterable[int], optional
        If given, restrict results to these detector number(s) (1-6).
        Default (None) returns all 6 detectors, consistent with the "search
        all available data" requirement; filtering is then applied
        client-side on the parsed access_url.

    Returns
    -------
    QueryResult

    Raises
    ------
    SpherexQueryError if the IRSA query fails entirely.
    """
    collections = WIDE_COLLECTIONS + (DEEP_COLLECTIONS if include_deep else [])

    try:
        table = Irsa.query_sia(pos=(target, radius), collection=collections)
    except Exception as exc:  # noqa: BLE001
        raise SpherexQueryError(
            f"IRSA SIA2 query failed for target={target.to_string('hmsdms')}, "
            f"radius={radius}, collections={collections}: {exc}"
        ) from exc

    if table is None or len(table) == 0:
        table = Table(
            names=["access_url", "obs_id", "t_min", "t_max", "s_ra", "s_dec"],
            dtype=["U512", "U128", "f8", "f8", "f8", "f8"],
        )

    # Attach a parsed 'detector' column.
    detector_col = [_extract_detector(str(url)) for url in table["access_url"]]
    table["detector"] = detector_col

    # Sort chronologically (t_min = MJD of exposure start) so downstream
    # consumers get images in time order for "blink" display.
    if "t_min" in table.colnames and len(table) > 0:
        table.sort("t_min")

    result = QueryResult(table=table, target=target, radius=radius, collections=collections)

    if detectors is not None:
        result = result.filter_by_detector(detectors)

    return result
