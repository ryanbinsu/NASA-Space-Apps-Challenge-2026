# SPHEREx Coordinate-to-Discovery Pipeline

This tool takes a sky coordinate (or object name), finds overlapping SPHEREx
exposures, downloads them, and searches for moving objects (asteroids,
comets, etc.) by aligning, cleaning, differencing, and tracklet-linking the
exposures across time.

## 1. Setup

```bash
pip install -r requirements_v2.txt
```

Python 3.10+ is required (the code uses `X | Y` union type hints).

`sep` and `reproject` both need a working C compiler toolchain to build from
source wheels on some platforms; if `pip install` fails on `sep`, try
`conda install -c conda-forge sep reproject` instead.

## 2. Files

| File | Purpose |
|---|---|
| `spherex_coords.py` | Parses the target string (sexagesimal, decimal RA/Dec, or object name) into a resolved `SkyCoord` + label. |
| `spherex_query.py` | Queries IRSA's SIA2 service for SPHEREx exposures overlapping the target, carrying through the `cloud_access` column needed for cloud downloads. |
| `spherex_download.py` | Downloads matching exposures (preferring IRSA's AWS S3 cloud mirror, falling back to on-premises HTTP), splits multi-extension FITS into per-HDU files, writes `manifest.csv`. Also includes a standalone CLI/API for browsing and fetching directly from the public S3 bucket, bypassing the IRSA API entirely. |
| `spherex_detect.py` | The 5-step detection pipeline: WCS alignment, noise/background removal, Z-score differencing, tracklet linking, confidence scoring. |
| `spherex_pipeline.py` | The main CLI — chains all of the above end to end. **Run this one.** |
| `requirements_v2.txt` | Full dependency list for the combined pipeline. |

## 2a. Cloud data access (AWS S3)

Per IRSA's [SPHEREx Data Access documentation](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/),
every SPHEREx product on-premises at IPAC is also mirrored on AWS S3
(bucket `nasa-irsa-spherex`, region `us-east-1`), free and credential-free
via the AWS Open Data Sponsorship Program.

`spherex_pipeline.py` now downloads this way **by default**:
1. It reads the `cloud_access` JSON blob IRSA's SIA2 service returns for
   each exposure (e.g. `{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "...", "region": "us-east-1"}}`).
2. It opens the file straight from S3 anonymously (`fits.open("s3://...", fsspec_kwargs={"anon": True})`),
   avoiding IRSA's on-premises HTTP server entirely.
3. If a given exposure has no `cloud_access` entry yet (recent data can lag
   behind the on-prem → cloud mirroring) or the S3 read fails after
   retries, it automatically falls back to the on-premises `access_url`
   over plain HTTP — so the tool always works, it just prefers the faster/
   cheaper cloud path when available.

Pass `--no-cloud` to disable this and always use HTTP (e.g. in a network
environment that allows HTTPS to `irsa.ipac.caltech.edu` but blocks
outbound S3 traffic). The `manifest.csv` records a `source` column
(`cloud` or `http`) per exposure so you can confirm which path was used.

This requires the `fsspec` and `s3fs` packages (now included in
`requirements_v2.txt`) in addition to `astropy`/`astroquery`.

## 2b. Browsing/fetching the S3 bucket directly (no IRSA API at all)

Per IRSA's Cloud Data Access page and the AWS Open Data registry entry for
SPHEREx (`registry.opendata.aws/spherex-qr`), the whole archive is also a
plain **public, unsigned-request S3 bucket** that can be explored without
ever calling IRSA's SIA2/API — e.g. the documented CLI pattern
`aws s3 ls --no-sign-request s3://nasa-irsa-spherex/qr3/level2/`.

`spherex_download.py` now exposes this as both a small standalone CLI and
importable functions, independent of the coordinate-search pipeline:

```bash
# List top-level release folders in the bucket
python spherex_download.py --list ""

# List one level under a data release (dr1, qr3, qr2, or qr for QR1)
python spherex_download.py --list qr3/level2/

# Recursively list every key under a prefix
python spherex_download.py --list dr1/dark/ --recursive

# Download one object by its exact key (copied from a listing above, or
# from the browsable directory tree at https://irsa.ipac.caltech.edu/ibe/data/spherex/)
python spherex_download.py --get "qr3/level2/2026W21_2A/l2b-v27-2026-268/1/level2_..._spx_l2b-....fits" -o ./exposure.fits
```

In Python:

```python
from spherex_download import list_s3_prefix, fetch_s3_key, open_fits_from_s3_key

listing = list_s3_prefix("qr3/level2/")          # {"subdirs": [...], "files": [...]}
fetch_s3_key("qr3/level2/.../IMAGE.fits", "./out.fits")
hdulist = open_fits_from_s3_key("qr3/level2/.../IMAGE.fits")  # in-memory, no local file
```

Bucket details: `nasa-irsa-spherex`, region `us-east-1`. S3 key prefixes
mirror the on-premises directory layout documented at IRSA's Browsable
Directories page (`dr1/...`, `qr3/...`, `qr2/...`, `qr/...` for QR1), by
product type and detector — see the module docstring for the full list
(spectral images under `level2/`, calibration products under
`dark/`, `abs_gain_matrix/`, etc.).

**Important:** S3 keys encode processing metadata (release, planning
period, version, detector), not sky position. Direct S3 browsing is great
for bulk exploration or grabbing a file whose key you already know, but
finding *which* files overlap a given RA/Dec still requires the SIA2
coordinate search (`spherex_query.py`) that the main pipeline uses — this
S3 browsing path is a separate, complementary tool, not a replacement for
`spherex_pipeline.py`. It requires the `boto3` package (now in
`requirements_v2.txt`).

## 3. Running it

### Interactive (prompts for everything)

```bash
python spherex_pipeline.py
```

You'll be asked for:
- a target (e.g. `08h55m10.831s -07d14m42.53s`, `133.79513, -7.24515`, or an object name)
- a search radius in arcmin (press Enter for the default)
- which detector(s) 1–6 to restrict to (press Enter for all)

### Non-interactive / scripted

```bash
python spherex_pipeline.py \
  --target "08h55m10.831s -07d14m42.53s" \
  --radius 2 \
  --detector 3 \
  --z-thresh 4.5 \
  --max-exposures 20
```

Flags:

| Flag | Default | Meaning |
|---|---|---|
| `--target` | — | Sexagesimal, decimal RA/Dec, or object name |
| `--radius` | query default | Search radius in arcmin |
| `--detector` | all 6 | Comma-separated detector list, e.g. `2,3` |
| `--max-exposures` | all found | Cap how many exposures are downloaded |
| `--z-thresh` | 5.0 | Z-score threshold for flagging a transient peak |
| `--max-step-px` | 50.0 | Max allowed per-frame motion, in pixels, when linking tracklets |
| `--skip-fetch` | off | Skip download; re-run detection on already-downloaded data |
| `--target-label` | — | Required with `--skip-fetch`; the `./spherex_output/<label>` folder to reuse |
| `--no-cloud` | off (cloud preferred) | Disable AWS S3 cloud reads; always use IRSA on-premises HTTP instead |

### Re-running detection only (no new download)

```bash
python spherex_pipeline.py --skip-fetch --target-label "08h55m10.8s_-07d14m42.5s" --z-thresh 4.0
```

Useful for tuning `--z-thresh` / `--max-step-px` without re-querying IRSA.

## 4. Output layout

```
spherex_output/<target_label>/
    manifest.csv                  # every downloaded exposure, all detectors
    <obs_id>_D<detector>/IMAGE.fits
    detector_1/
        discoveries.csv           # candidates found on detector 1
        top_discovery.png         # cutout of the highest-confidence candidate
    detector_2/
        discoveries.csv
        top_discovery.png
    ...
    all_discoveries.csv           # every detector's results, combined & sorted by confidence
```

Detectors with fewer than 3 usable exposures are automatically skipped
(at least 3 time-separated frames are needed to fit a straight-line track).

## 5. Reading `discoveries.csv`

| Column | Meaning |
|---|---|
| `candidate_id` | Arbitrary ID (`OBJ_001`, `OBJ_002`, ...), sorted by confidence |
| `detector` | Which of the 6 SPHEREx detectors this came from |
| `confidence` | 0–1 calibrated score combining SNR and motion straightness/consistency |
| `mean_snr_z` | Average peak Z-score (significance) across the 3 linked frames |
| `speed_px_per_unit_t` | Fitted speed in pixels per day (MJD units) |
| `linearity_rmse_px` | How well the 3 points fit a straight line (lower = better) |
| `start_ra/dec`, `end_ra/dec` | Sky coordinates at first and last detection, for follow-up |

Treat `confidence < 0.5` as low-reliability — cross-check against the
`top_discovery.png` cutout and consider star dipole artifacts near bright
sources before reporting a real discovery.

## 6. Known limitations

- Tracklet linking only considers straight 3-frame tracks; fast-moving or
  sparsely sampled objects spanning gaps may be missed.
- Each detector is processed independently — a real moving object crossing
  detector boundaries won't be linked across detectors.
- Confidence scoring is heuristic, not a formal statistical detection
  significance; always visually verify top candidates before trusting them.
- `spherex_coords.py` is required but not bundled in this package — it was
  built earlier and must be dropped into the same folder (it parses the
  target string into a `SkyCoord` + filesystem-safe label; see
  `spherex_pipeline.py`'s import for the expected interface:
  `parse_coordinate(raw_target) -> object with .skycoord, .label, .input_type`,
  raising `CoordinateParseError` on bad input).
