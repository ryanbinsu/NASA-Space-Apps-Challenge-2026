# Current codebase walkthrough

The integrated site runs from the repository root. Read [architecture](ARCHITECTURE.md), [infrastructure](INFRASTRUCTURE.md) and [the API/mathematics guide](INTEGRATION.md) alongside this walkthrough.

## Repository map

New standalone archive tools also live at the root: spherex_coords.py, spherex_query.py, spherex_download.py, spherex_detect.py and spherex_pipeline.py. Their [CLI guide](ARCHIVE_PIPELINE.md) and [separate mathematical caveats](MATHEMATICS_REVIEW.md) distinguish them from the website; the web API still imports moving_object_pipeline.py.

| Location | Responsibility |
| --- | --- |
| index.html, src/main.tsx | Browser entry and React mounting |
| src/App.tsx | Project shell, API connection indicator and the two workspaces |
| src/components/PublishedObservations.tsx | Curated target/coordinate search and comparison-group selection |
| src/components/AnalysisWorkbench.tsx | Upload/parameter form, asynchronous processing, candidate results and exports |
| src/components/ObservationViewer.tsx | Reusable frame viewer, layers, playback, timeline and overlays |
| src/services/observations.ts | Existing curated-manifest fetch and runtime validator |
| src/services/analysis.ts | Health check, multipart submission and processing-result validator |
| src/services/targets.ts | Great-circle coordinate distance and published-target matching |
| src/types/observations.ts | Curated manifest's TypeScript representation |
| src/types/analysis.ts | HTTP result, candidate, tracklet and parameter types |
| backend/app.py | Local HTTP API, input limits, concurrency lock and static artifact serving |
| backend/analysis.py | Pipeline orchestration and JSON/browser export adapter |
| moving_object_pipeline.py | The team's five processing stages, with integration correctness fixes |
| scripts/dev.mjs | Start/stop the Python API and Vite together |
| tests/ | Synthetic mathematics/API tests and Node frontend tests |
| public/observations/ | Curated manifest/images; initially empty |
| processing/README.md | Ownership guidance for scientific processing work |
| sky/ | Earlier independent Next.js prototype, retained unchanged |
| docs/ | Engineering and data-contract documentation |

Generated node_modules/, .venv/, .tools/, dist/ and .runtime/ are ignored. They are not source dependencies to commit.

## Entry and connection status

index.html loads main.tsx. main.tsx imports global CSS and renders App in React StrictMode.
StrictMode may repeat development effect setup/cleanup; the curated manifest effect uses an AbortController.

App renders PublishedObservations and AnalysisWorkbench independently.
Its health request sets checking/online/offline status; a Check connection button retries it.
An unavailable API does not prevent browsing static curated observations. Processing errors remain visible in the upload workspace.

## Curated observations path

PublishedObservations loads the versioned static JSON using the original parseManifest validator.
A malformed manifest is an error; an empty manifest is a valid empty state.

Target selection supplies the manifest's actual name and coordinates. Coordinate search uses spherical great-circle separation, including RA wrap and poles, against published target centers.
It does not query an archive or claim that an empty local result means the archive has no coverage.

Ready records are grouped by their declared comparisonGroup so unlike reviewed series are not automatically mixed.
Excluded observations remain visible with their reasons and source metadata is available in a details panel.
A curated image path resolves relative to the observations directory; it is not a Python input path.

The static contract remains independent of the uploaded-run result. Do not publish an analysis response as a reviewed manifest without a deliberate conversion/review step.

## Uploaded analysis path

AnalysisWorkbench stores each File with its optional UTC override. Reordering moves both together.
The form checks file count/size, complete-or-empty overrides, odd median size and step bounds before submitting.
The server independently validates its inputs; browser validation is not trusted as an API boundary.

runAnalysis builds FormData without manually setting Content-Type, allowing the browser to supply its multipart boundary.
It converts HTTP/network errors into user-facing messages and validates successful JSON before exposing typed results.

The workbench clears prior results before each run and disables the form while awaiting completion. It does not report fake progress percentages.
A disconnected browser does not cancel Python computation.

Returned data drive actual PNG URLs, the candidate table, speed units, WCS coordinates, selected-track metrics, per-frame noise, file hashes and export links.
The table shows at most 200 ranked triplets for responsiveness; CSV/JSON contain all returned results.
No-candidate completion is handled separately from errors and still provides exports.

## Shared viewer

ObservationViewer receives a display-oriented list of frames rather than knowing about uploads or the static manifest.
Uploaded results provide all four image modes; curated data currently provide cleaned/browser intensity only.

Local state controls the selected frame, mode, playback interval, overlay checkbox and image-load error.
A timer runs only while playing with at least two frames. Cleanup removes it; zero/one-frame sequences cannot produce modulo-zero playback.
Changing a timeline value pauses playback. Keys reset the viewer when the run/target/comparison group changes.

Generated images use lower-origin pixel coordinates. SVG circles invert y so detections remain aligned with the rendered image.
Selecting a tracklet restricts overlays to its points in the current frame; otherwise all extracted peaks are shown.
Image height is constrained for usable playback controls on desktop and mobile. An image request failure becomes a visible error rather than an empty sky frame.

## Python request boundary

backend/app.py accepts a small multipart batch on /api/analyze.
A process-local lock serializes expensive runs and matplotlib use. Raw inputs go to a TemporaryDirectory with safe generated filenames; user filenames are metadata only.
Outputs go into a UUID directory under .runtime/runs/, never into public/observations/.

backend/analysis.py checks dimensions/type/HDU, reads or accepts timestamps, sorts complete epochs and chooses consistent frame units when time is unknown.
It calls the existing stage functions, masks invalid common alignment coverage, exports PNG layers and invokes the pipeline's ranked CSV/plot reporting.
The response is strict JSON: NaN/Infinity fail rather than leaking into browser calculations.

backend/app.py adds the run identity/base URL and saves the same complete result for downloading.
After request completion, uploaded bytes are removed. Generated files persist locally until deliberately cleaned; there is no job database or automatic retention policy.

## Scientific code ownership and fixes

moving_object_pipeline.py still owns alignment, background/normalization, differences, extraction, linking, metrics and score/reporting.
Integration changes fix unequal-time prediction, true RMSE, invalid-border noise contamination, empty normalization samples and inappropriate timestamp/speed/confidence labels.
The heuristic itself is preserved and exposed honestly; it has not become a calibrated probability model.

See INTEGRATION.md for equations, parameter limits and known scientific approximations. Niyati/Artem review remains necessary before interpreting real observations.

## Reading and changing the code

For a new contributor, follow: API/static contract → types → services → workbench/viewer → API adapter → pipeline.
For UI changes, start in components/CSS. For a data change, update contract documentation, TypeScript declarations, runtime checks and tests together.
For mathematical changes, add a fixture with a known expected quantity rather than testing only that a function returns something.
