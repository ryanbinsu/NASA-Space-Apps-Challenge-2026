# SPHEREx Motion Explorer

Team Phys***'s NASA Space Apps Challenge 2026 project for **Planet X and SPHEREx**.

The main application now connects the team's Python moving-object pipeline to a React interface.
Upload FITS or raster exposures, inspect aligned/cleaned/difference/Z images, play the sequence, review candidate tracklets and export the results.

## Run the integrated application

Requirements: **Node 24.22.3**, npm and **Python 3.12** (see .nvmrc and .python-version).
From the repository root:

```bash
npm ci
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
npm run dev:full
```

Open **http://localhost:5173**. One command starts Python on loopback port 8000 and Vite on 5173; /api requests are proxied automatically. Ctrl+C stops both processes. Restart this command after Python changes.

For Windows-native development, create the venv with your Python 3.12 executable and use .venv/Scripts/python.exe for installation/checks. The Node launcher detects the platform. For this WSL repository, run everything inside Ubuntu; do not share node_modules between Windows and Linux.

The existing workspace has ignored local toolchains. If Node is not on the WSL PATH:

```bash
export PATH="$PWD/.tools/node-v24.22.3-linux-x64/bin:$PATH"
npm run dev:full
```

This workspace's .venv is already installed. On another machine, install Python/Node normally; .tools/ and .venv/ are not in Git. Python 3.14 on this machine could not build sep without Python headers; Python 3.12 was validated using its wheel.

## Use the website

1. Choose a published target or search the published manifest by ICRS RA/Dec and angular radius. The current manifest is empty; search does not contact an archive.
2. Upload **3–8** comparable exposures: all FITS, or all PNG/JPEG/TIFF. Each must be 32×32 or larger, at most 1,048,576 pixels, at most 20 MiB; total upload limit is 100 MiB.
3. For FITS, select the image HDU under Processing parameters. A celestial WCS is required. Standard images require enough shared stars for alignment.
4. FITS observation times are read from MJD-OBS or DATE-OBS and converted from TIMESYS to UTC (UTC is the FITS default when TIMESYS is absent). Complete times are sorted. Optionally supply UTC overrides for every file.
5. If any time is missing, the entire sequence uses upload order and frame units. Reorder files with the arrow buttons. Dates are never fabricated.
6. Run analysis. Inspect all four image layers, timeline/playback, peak overlays and ranked three-frame tracklets. Select a tracklet for its coordinates and per-detection metrics.
7. Download CSV, complete JSON/provenance and, when a tracklet exists, the top-candidate plot.

Parameters expose the pipeline's image HDU, median filter size, background mesh, flux normalization, Z threshold, minimum peak area and minimum/maximum inter-frame displacement.

Scores are **uncalibrated heuristic rankings**, not discovery probabilities. Pixel speed is per day with real times, otherwise per frame. A valid no-candidate result is not an analysis error or proof that no moving object exists.

## Commands

| Command | Responsibility |
| --- | --- |
| npm run dev:full | Python API + Vite on localhost:5173 |
| npm run dev | Frontend only; API must already run for processing |
| npm run typecheck | Application and Vite configuration checks |
| npm run build | Type checks then production frontend in dist/ |
| npm run lint | Root frontend/tooling checks, warnings fail |
| npm run test:frontend | Built-in Node tests for coordinates and contracts |
| npm run preview | Preview existing frontend build, proxying /api to 8000 |
| .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v | Mathematics and API regression tests |

To run Python separately:

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

API documentation: http://localhost:8000/docs.
After npm run build, this same Python command also serves the built website at http://localhost:8000, including its API, for a local single-port run.

## Architecture and ownership

```text
Browser :5173 → Vite /api proxy → FastAPI :8000 → moving_object_pipeline.py
                                     ↓
                              .runtime/runs/<id>/
                         PNG layers + CSV + JSON + plot
```

| Location / owner | Responsibility |
| --- | --- |
| src/components/ / Theo with Ryan integration | Upload controls, published targets, playback, results |
| src/services/ and src/types/ / Ryan | Static and HTTP contracts, validation, coordinate matching |
| moving_object_pipeline.py / Artem | Five scientific-processing stages |
| backend/ / Ryan with Artem review | Upload validation, orchestration, artifact export and API |
| public/observations/ | Optional curated static manifest/images |
| Niyati | Data suitability, targets and scientific validation |
| Pranav | Documentation, judging requirements and demo |

The separate sky/ Next.js project is the earlier viewer prototype and remains intact. Its target/search/playback concepts are connected in the root application; placeholder images and approximate targets are not used as scientific data. Use the root commands above for the integrated site, rather than starting a second frontend on port 3000.

Use focused branches and review contract changes with both producer and consumer owners. No commits, pushes or deployment are implicit in local validation.

## Guides

- [Architecture](docs/ARCHITECTURE.md)
- [Codebase walkthrough](docs/CODEBASE.md)
- [Infrastructure](docs/INFRASTRUCTURE.md)
- [API contract and mathematics](docs/INTEGRATION.md)
- [Curated static data contract](docs/DATA_CONTRACT.md)
- [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md)

## Limitations and scientific provenance

No live SPHEREx archive query/acquisition code or real observation dataset was supplied in this repository.
Uploaded provenance remains user supplied; WCS, dates and candidate rankings require scientific review. No Planet X detection claim is made.
The backend uses approximate scalar noise and a median reference, not a calibrated significance/probability model.

Runs are stored locally under ignored .runtime/; there is no database, authentication, automatic retention cleanup or remote storage.
The local API is loopback-only and processes one run at a time. Public multi-user deployment needs separate operational design; Vercel static hosting alone cannot execute this Python pipeline.

Validation used explicitly synthetic fixtures, not NASA observations. See the integration guide for checks and limitations.
The earlier frontend audit recorded moderate development lint advisories; recheck npm audit before describing current status. No forced dependency downgrade was applied.

## Authoritative references

- [Official challenge](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/?tab=details)
- [SPHEREx archive access documentation](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/)

The challenge page was inaccessible during initial research. Verify detailed judging/science requirements against the official source; do not infer archive capabilities from this local pipeline.
