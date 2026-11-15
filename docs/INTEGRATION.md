# Local processing API and mathematical integration

## Scope

The pulled backend was a Python library/script, not an HTTP service. backend/ adds a thin FastAPI adapter around its existing stages.
The root Vite application is the integrated frontend. sky/ remains the independent Next.js prototype and is not a second runtime dependency.

The user-authorized integration covers uploaded exposures, processing controls, all five stages, image playback and results/exports. It does not invent an archive acquisition service.

## HTTP contract

All frontend requests use the same origin through Vite's /api proxy.

| Endpoint | Behavior |
| --- | --- |
| GET /api/health | Readiness, stage names and frame/pixel limits |
| POST /api/analyze | Multipart uploads/settings → completed analysis JSON |
| GET /api/runs/{id}/{artifact} | Generated PNG/CSV/JSON/plot downloads |
| GET /docs on port 8000 | Generated FastAPI API documentation |

POST /api/analyze fields:

| Field | Default / meaning |
| --- | --- |
| files | 3–8 exposures; all FITS or all raster |
| hdu_index | 0; FITS image HDU, 0–100 |
| filter_size | 3; odd median-filter size, 1–9 |
| box_size | 64; SEP background mesh, 8–256 pixels |
| normalize | true; match bright-pixel flux to the reference frame |
| z_thresh | 5; positive extraction threshold, 1–50 |
| min_area | 3; minimum connected peak area, 1–100 pixels |
| min_step_px | 1.5; minimum displacement between consecutive detections |
| max_step_px | 50; maximum displacement, at least the minimum |
| timestamps | JSON string array of UTC ISO times; empty uses headers/frame order |
| source | Optional user-supplied dataset/provenance description |

FITS uses the selected 2D HDU and merged primary/extension metadata. Missing/invalid WCS fails alignment.
MJD-OBS is preferred over DATE-OBS. TIMESYS is interpreted through Astropy and converted to UTC; absent TIMESYS uses UTC.
Header times describe the supplied observation keyword, not an inferred exposure midpoint.

An explicit UTC time for every file overrides headers. Partial overrides are rejected.
Complete times must be distinct, are sorted before alignment and yield pixel/day speed. With any unknown timestamp, all epochs become frame indices in upload order; observedAt stays null.

Limits: 20 MiB per file, 100 MiB total, 32 pixels minimum on each axis, at most 1,048,576 pixels per image. Animated/multipage raster files and mixed FITS/raster batches are rejected.
These are bounded local-demo limits, not production ingress protection: multipart parsing occurs before file-content validation.

HTTP 422 carries actionable input/processing errors. HTTP 409 means another run holds the processing lock.
Alignment failures produce errors instead of fake results. Unexpected processing errors are logged and return a general actionable message.

## Result shape

The version-1 response has id, baseUrl, source, timeUnit, width/height, hasWcs, frames, candidateCount, tracklets, settings, warnings, validPixelFraction, csv and nullable topPlot.
Full JSON is also saved as result.json, including the same run ID and asset base URL.

Each frame includes original filename, UTC time or null, numerical analysis time, background RMS, SHA-256 input digest, extracted peaks and relative image names.
Each peak contains frame, time, pixel x/y, nullable RA/Dec, peak_z, integrated significance-map flux and nearby minimum negative Z.
Each tracklet includes its CSV-compatible ID, three points, mean_speed_px, velocity_consistency, linearity_rmse_px and confidence (the existing backend field name for its heuristic score).

Four image layers are exported:
- aligned: registration output;
- cleaned: median-filtered, background-subtracted and optionally flux-normalized;
- difference: science minus the shared median reference;
- significance: difference divided by approximate combined scalar noise.

Intensity limits are shared across frames within a layer; difference limits are symmetric/shared, and Z display is clipped to ±10. Data are exported with lower image origin. SVG overlays invert y to match browser coordinates.
The top-candidate plot also uses shared limits across its three cutouts.

CSV contains all linked triplets, ranked by heuristic score, with speed_px_per_day or speed_px_per_frame as appropriate.
An empty result still exports CSV headers and JSON, but no top-candidate plot. Input bytes are deleted after processing; hashes and submitted filenames remain.

The API result is distinct from the curated manifest contract. It must not be treated as a reviewed/published SPHEREx dataset.
The original static interface remains documented in [DATA_CONTRACT.md](DATA_CONTRACT.md).

## Mathematics exposed in the UI

1. **Alignment:** FITS reprojection onto the first chronological frame's celestial grid, or Astroalign star registration for raster files.
2. **Cleaning:** median filter, SEP background subtraction and optional bright-pixel normalization. The common finite footprint is eroded to exclude interpolation/filter borders. Invalid regions are masked in SEP rather than treated as zero-valued sky.
3. **Difference/Z:** D = science − reference, Z = D / sqrt(science_RMS² + reference_RMS²). For at least three frames, reference is their pixel-wise median; its scalar RMS estimate uses 1.253314 × median(frame_RMS) / sqrt(N).
4. **Motion:** three consecutive detections are linked with step bounds and a constant-velocity prediction using the actual epoch-spacing ratio. Speeds are Euclidean pixel displacement divided by the actual time interval. Velocity consistency is exp(−std(speed)/(mean(speed)+1e−5)).
5. **Ranking:** line fits x(t), y(t) produce sqrt(mean(dx_residual² + dy_residual²)). Straightness = exp(−RMSE/1.5). Motion score averages straightness and velocity consistency. SNR score = 1−exp(−max(0,mean_Z−3)/5). Final score = (0.45×SNR + 0.55×motion) × dipole penalty, bounded to [0,1]. A nearby strong negative residual can halve the score.

This fixes the supplied implementation's mean-distance/RMSE mismatch, equal-time linking assumption and mixed MJD/index fallback.
Empty bright-pixel samples no longer produce NaN normalization; duplicate epochs are rejected rather than silently replaced with a time step of one.

## Scientific limits

The scalar noise approximation ignores important covariance: reprojection/filtering correlate pixels, a median's uncertainty is approximate and the science frame participates in its own reference.
Z therefore is not a calibrated statistical detection significance. The ranking weights are heuristics, not trained/calibrated discovery probabilities.

Three-frame triplets may overlap and represent the same source; there is no orbit fit, cross-triplet deduplication, catalog rejection or Planet X confirmation.
Minimum/maximum step settings measure displacement, not angular velocity. WCS converts positions, but reported speed remains pixel/time.
The flux field is integrated Z-map values, not calibrated photometric flux.
Comparability of wavelengths, calibration, masks and normalization still needs Artem/Niyati review.

## Verification

Committed tests:
- tests/test_pipeline.py: known combined-noise calculation, true RMSE, irregular epochs, duplicate times, flat normalization, heuristic penalty, complete FITS pipeline/exports, sorted headers, missing times, raster alignment, no detections, invalid inputs, HDUs, WCS offsets and health.
- tests/frontend.test.mjs: spherical coordinate matching including RA wrap/poles and contract rejection.

Run with the commands in the README. No real observations are needed for these synthetic regression fixtures.

A temporary Chromium check in ignored .tools/ exercised port 5173 end to end: coordinate empty state, synthetic FITS upload, all five stages, real image rendering, layer changes, playback, track selection/overlays, CSV/JSON/plot downloads, mobile layout, no-candidate result and invalid-file errors.
No browser page errors were observed. Synthetic test data are explicitly labelled and are not added to public/observations/.
