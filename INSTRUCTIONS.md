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
| `spherex_coords.py` | Parses the target string (sexagesimal, decimal RA/Dec, or object name) into a resolved `SkyCoord` + label. *(not included here — see note below)* |
| `spherex_query.py` | Queries IRSA's SIA2 service for SPHEREx exposures overlapping the target. *(not included here — see note below)* |
| `spherex_download.py` | Downloads matching exposures, splits multi-extension FITS into per-HDU files, writes `manifest.csv`. *(not included here — see note below)* |
| `spherex_detect.py` | The 5-step detection pipeline: WCS alignment, noise/background removal, Z-score differencing, tracklet linking, confidence scoring. |
| `spherex_pipeline.py` | The main CLI — chains all of the above end to end. **Run this one.** |
| `requirements_v2.txt` | Full dependency list for the combined pipeline. |

> **Note:** This zip contains `spherex_detect.py` and `spherex_pipeline.py`,
> which were developed/updated in this conversation. `spherex_coords.py`,
> `spherex_query.py`, and `spherex_download.py` are imported by
> `spherex_pipeline.py` but were written earlier and are not part of this
> export — place your existing copies of those three files in the same
> folder before running.

## 3. Running it

### Interactive (prompts for everything)

```bash
python spherex_pipeline.py
```

You'll be asked for:
- a target (e.g. `08h55m10.831s -07d14m42.53s`, `133.79513, -7.24515`, or an object name)
- a search radius in arcmin (press Enter for the default)
- which detector(s) 1-6 to restrict to (press Enter for all)

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
| `confidence` | 0-1 calibrated score combining SNR and motion straightness/consistency |
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
