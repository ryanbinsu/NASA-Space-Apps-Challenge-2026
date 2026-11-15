"""
spherex_coords.py
==================
Coordinate / target-name parsing for the SPHEREx retrieval tool.

Purpose
-------
Accepts the three conventional ways an astronomer specifies a sky position
and converts any of them into a single `astropy.coordinates.SkyCoord`
(ICRS frame), which is the common currency used by the rest of the pipeline
(spherex_query.py, spherex_download.py).

Supported input conventions
----------------------------
1. Sexagesimal (hms/dms):      "08h55m10.831s -07d14m42.53s"
                                "08 55 10.831 -07 14 42.53"
2. Decimal degrees (RA, Dec):  "133.79513, -7.24515"
                                "133.79513 -7.24515"
3. Object name (SIMBAD/NED
   resolvable via Sesame):     "Barnard's Star", "WISE 0855-0714", "R Draconis"

Design notes / assumptions
---------------------------
- Decimal-degree pairs are disambiguated from sexagesimal strings by the
  ABSENCE of h/m/s/d unit letters and the PRESENCE of a comma or a clean
  two-token float split. This is a heuristic; if your team's frontend
  already knows which convention the user picked (e.g. a UI radio button),
  call `parse_sexagesimal`, `parse_decimal_degrees`, or `parse_object_name`
  directly instead of the auto-detecting `parse_coordinate`.
- Object-name resolution requires network access (queries the Sesame
  name resolver via astropy). It is NOT attempted unless the string fails
  to parse as numeric coordinates first, to avoid unnecessary network
  round-trips for the common case.
- All returned SkyCoord objects are in the ICRS frame, consistent with the
  SIA2 'POS' parameter convention used by IRSA (see spherex_query.py).

Dependencies
------------
- astropy (coordinates, units)

This module has NO dependency on astroquery, so it can be unit-tested and
reused independently of the network-querying code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from astropy.coordinates import SkyCoord
from astropy import units as u


class CoordinateParseError(ValueError):
    """Raised when a user-supplied target string cannot be resolved to a SkyCoord."""


@dataclass
class ResolvedTarget:
    """
    Container for a successfully parsed target.

    Attributes
    ----------
    skycoord : SkyCoord
        The resolved position in ICRS.
    input_string : str
        The raw string the user typed.
    input_type : str
        One of {"sexagesimal", "decimal_degrees", "object_name"} indicating
        which parsing path succeeded.
    """
    skycoord: SkyCoord
    input_string: str
    input_type: str

    @property
    def label(self) -> str:
        """A filesystem-safe label for naming output directories."""
        safe = re.sub(r"[^A-Za-z0-9_.+-]+", "_", self.input_string.strip())
        return safe.strip("_") or "target"


_SEXAGESIMAL_UNIT_PATTERN = re.compile(r"[hHdDmMsS]")

# Stricter pattern used only for auto-detection in parse_coordinate(): requires
# the unit letter to immediately follow a digit (e.g. "08h", "14d"), so plain
# words containing h/d/m/s (like "WISE", "Draconis", "R Draconis") are not
# mistaken for sexagesimal coordinates. (parse_sexagesimal() itself keeps the
# looser pattern above, since a direct call implies the caller already knows
# the input is sexagesimal.)
_SEXAGESIMAL_UNIT_AFTER_DIGIT_PATTERN = re.compile(r"\d\s*[hHdDmMsS]")
_NUMERIC_PAIR_PATTERN = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*[, ]\s*([+-]?\d+(?:\.\d+)?)\s*$"
)


def parse_sexagesimal(text: str) -> SkyCoord:
    """
    Parse a sexagesimal RA/Dec string, e.g.
    "08h55m10.831s -07d14m42.53s" or "08 55 10.831 -07 14 42.53".

    Raises
    ------
    CoordinateParseError if astropy cannot parse the string as sexagesimal.
    """
    try:
        # If unit letters (h/d/m/s) are present, SkyCoord infers units itself.
        if _SEXAGESIMAL_UNIT_PATTERN.search(text):
            return SkyCoord(text, frame="icrs")
        # Otherwise assume space-separated "HH MM SS.s +/-DD MM SS.s"
        return SkyCoord(text, unit=(u.hourangle, u.deg), frame="icrs")
    except Exception as exc:  # noqa: BLE001 - re-raised with context below
        raise CoordinateParseError(f"Could not parse '{text}' as sexagesimal: {exc}") from exc


def parse_decimal_degrees(text: str) -> SkyCoord:
    """
    Parse a "RA, Dec" or "RA Dec" pair expressed in decimal degrees.

    Raises
    ------
    CoordinateParseError if the string is not a clean pair of floats.
    """
    match = _NUMERIC_PAIR_PATTERN.match(text)
    if not match:
        raise CoordinateParseError(f"'{text}' is not a decimal-degree RA/Dec pair.")
    ra_deg, dec_deg = (float(match.group(1)), float(match.group(2)))
    if not (0.0 <= ra_deg <= 360.0):
        raise CoordinateParseError(f"RA={ra_deg} deg is out of the valid [0, 360] range.")
    if not (-90.0 <= dec_deg <= 90.0):
        raise CoordinateParseError(f"Dec={dec_deg} deg is out of the valid [-90, 90] range.")
    return SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")


def parse_object_name(text: str) -> SkyCoord:
    """
    Resolve an object name to coordinates using astropy's SkyCoord.from_name,
    which queries the Sesame name resolver (SIMBAD/NED/VizieR) over the network.

    Requires network access. Raises CoordinateParseError on failure
    (unknown name, resolver unreachable, etc.).
    """
    try:
        return SkyCoord.from_name(text.strip())
    except Exception as exc:  # noqa: BLE001
        raise CoordinateParseError(
            f"Could not resolve object name '{text}' via Sesame: {exc}"
        ) from exc


def parse_coordinate(text: str) -> ResolvedTarget:
    """
    Auto-detect which of the three conventions `text` follows and return a
    ResolvedTarget. Tries, in order: decimal-degree pair, sexagesimal,
    then object-name resolution (the only one requiring network access).

    Parameters
    ----------
    text : str
        Raw user input, e.g. from an `input()` prompt or a web form field.

    Returns
    -------
    ResolvedTarget

    Raises
    ------
    CoordinateParseError if none of the three strategies succeed.
    """
    text = text.strip()
    if not text:
        raise CoordinateParseError("Empty coordinate/target string.")

    # 1. Decimal degree pair (cheap, no network, unambiguous once it matches).
    if _NUMERIC_PAIR_PATTERN.match(text):
        return ResolvedTarget(parse_decimal_degrees(text), text, "decimal_degrees")

    # 2. Sexagesimal (a unit letter immediately follows a digit, e.g. "08h",
    #    or the string is a clean 6-token space list like
    #    "08 55 10.831 -07 14 42.53"). Using the digit-anchored pattern here
    #    (rather than a bare letter search) avoids misclassifying object names
    #    that happen to contain h/d/m/s, e.g. "WISE 0855" ('S' in WISE),
    #    "R Draconis" ('D' in Draconis).
    six_token_numeric = len(text.replace(",", " ").split()) == 6 and not re.search(
        r"[A-Za-z]", text
    )
    looks_sexagesimal = bool(_SEXAGESIMAL_UNIT_AFTER_DIGIT_PATTERN.search(text)) or six_token_numeric
    if looks_sexagesimal:
        return ResolvedTarget(parse_sexagesimal(text), text, "sexagesimal")

    # 3. Fall back to object-name resolution (network required).
    return ResolvedTarget(parse_object_name(text), text, "object_name")
