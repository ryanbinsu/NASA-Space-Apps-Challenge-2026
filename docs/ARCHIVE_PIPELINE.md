# Standalone SPHEREx coordinate-to-discovery CLI

Run commands from the **repository root**. This CLI is separate from the web API, which still uses moving_object_pipeline.py. Its network-dependent workflows were not run during final submission cleanup. Read [the mathematics review](MATHEMATICS_REVIEW.md) before interpreting its outputs.

Historical development claims below are not independent scientific validation; the source review records outstanding limitations.

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
| `spherex_query.py` | Queries IRSA's SIA2 service for SPHEREx exposures overlapping the target. |
| `spherex_download.py` | Downloads matching exposures, splits multi-extension FITS into per-HDU files, writes `manifest.csv`. |
| `spherex_detect.py` | The 5-step detection pipeline: WCS alignment, noise/background removal, Z-score differencing, tracklet linking, confidence scoring. |
| `spherex_pipeline.py` | The main CLI — chains all of the above end to end. **Run this one.** |
| `requirements_v2.txt` | Unpinned direct dependencies for the standalone CLI. |

All five Python modules listed above are present at the repository root. Keep them together: their imports and output paths assume this layout. requirements_v2.txt is an unpinned standalone dependency list; it is separate from the web stack's requirements.lock.txt.

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
| `confidence` | 0-1 uncalibrated heuristic ranking combining SNR and motion straightness/consistency; not a probability |
| `mean_snr_z` | Average peak Z-score (significance) across the 3 linked frames |
| `speed_px_per_unit_t` | Fitted speed in pixels per day (MJD units) |
| `linearity_rmse_px` | How well the 3 points fit a straight line (lower = better) |
| `start_ra/dec`, `end_ra/dec` | Sky coordinates at first and last detection, for follow-up |
| `artifact_flag` | `True` if any of the 3 linked detections had an implausibly high Z-score (> 200 by default) — see "Data-quality fixes" below. These are excluded from linking entirely by default, so this should normally stay `False`; it's kept as a visible safety net. |

Treat `confidence < 0.5` as low-reliability — cross-check against the
`top_discovery.png` cutout and consider star dipole artifacts near bright
sources before reporting a real discovery.

### Data-quality fixes: why cutouts used to look like pure noise

Earlier runs sometimes produced `top_discovery.png` cutouts that were just
grainy static with no visible source under the green circle, alongside
`discoveries.csv` entries with wildly inflated Z-scores (thousands, instead
of a plausible tens). Three bugs were fixed in `spherex_detect.py` to
address this:

1. **`normalize_flux` runaway scale factor (the main cause).** It picked
   "bright" pixels with a blind 99th-percentile cut. On a star-poor frame,
   that top 1% was often just noise, not starlight, so the computed
   brightness-matching scale factor could blow up 100x — amplifying that
   one frame's noise by the same amount and producing single-frame
   Z-score spikes that were a normalization artifact, not a real signal.
   Fixed with sigma-clipped "bright pixel" statistics, a minimum-sample-size
   guard, and a `[0.2, 5.0]` clamp on the resulting scale factor.
2. **`remove_cosmic_rays` blurred the whole image.** It ran a blanket
   median filter over every pixel — including real point sources — instead
   of targeting actual outliers. It now flags only pixels that are
   sigma-clipped statistical outliers relative to a local median and
   replaces just those, leaving real signal mostly intact.
3. **No sanity ceiling on Z-scores.** `extract_candidates` now flags any
   peak with Z above `max_sane_z` (default 200) as `is_artifact`; by
   default `link_tracklets` excludes these before building tracklets at
   all (`exclude_artifacts=True`), which also fixes the "1000+ discoveries,
   mostly junk" problem — those were largely coincidental straight-line
   matches between unrelated noise/glitch pixels. `score_discovery_confidence`
   and `compute_motion_score` additionally penalize (×0.3) any artifact that
   slips through as defense in depth.

If cutouts still look noisy after these fixes, it likely means the
candidate is genuinely low-SNR (check `mean_snr_z` and `confidence`) rather
than a pipeline bug — lower `--z-thresh` cautiously and inspect visually.

### Stretch goal: Motion Score

Alongside the main `confidence` score, `discoveries.csv` also includes a
much simpler, independent metric:

```
Motion Score = pixel displacement × brightness confidence
```

| Column | Meaning |
|---|---|
| `pixel_displacement_px` | Straight-line distance (px) between the first and last detection in the tracklet |
| `brightness_confidence` | Mean peak Z-score across the tracklet, squashed into [0, 1] |
| `motion_score` | The product of the two above — a quick, easy-to-explain sanity check: far + bright-confident scores high, either small displacement or low confidence pulls it down |

It's intentionally cruder than `confidence` (no straightness/velocity
weighting, no dipole penalty) — use it as a secondary sanity check, not a
replacement for `confidence`.

### Stretch goal: retrying flaky servers

IRSA's archive (both the SIA2 search endpoint and the file-download
server) can time out or drop connections under load. Both
`spherex_query.py` and `spherex_download.py` now loop and retry every few
seconds (5s for queries, 10s for downloads) instead of failing the whole
run on the first hiccup — you'll see `retrying in Ns...` messages in the
console if this happens. By default they retry indefinitely (Ctrl-C to
give up); pass a `max_attempts`/`max_retries` value in code if you want a
hard cap instead.

## 6. Known limitations

- Tracklet linking only considers straight 3-frame tracks; fast-moving or
  sparsely sampled objects spanning gaps may be missed.
- Each detector is processed independently — a real moving object crossing
  detector boundaries won't be linked across detectors.
- Confidence scoring is heuristic, not a formal statistical detection
  significance; always visually verify top candidates before trusting them.
