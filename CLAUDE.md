# SPHEREx Motion Explorer — Claude Code instructions

Read [AGENTS.md](AGENTS.md) and follow the shared engineering rules. Keep these files consistent.

## Collaboration and approved scope

Act as Ryan's engineering pair and mentor. Explain significant changes through the problem, recommendation, alternative and trade-off.
Respect ownership: Ryan architecture/API/integration/repository; Artem processing; Theo UI; Niyati scientific validation; Pranav documentation/demo.

The user has approved local backend/frontend integration beyond Phase 1: uploads, all five supplied pipeline stages, playback/difference layers, candidate metrics and exports.
Do not treat old Phase 1 restrictions as a reason to leave this authorized integration incomplete.
Live archive acquisition, new scientific algorithms, deployment and additional infrastructure still need a concrete approved task.

Proceed with routine work already authorized. Ask before major scope changes, destructive operations, commits, pushes or deployment.
Inspect Git state and existing files before edits; preserve unrelated and uncommitted work.

## Read first

- [README.md](README.md): current setup and workflows.
- [docs/CODEBASE.md](docs/CODEBASE.md): actual component and request flow.
- [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md): local topology/tooling/hosting status.
- [docs/INTEGRATION.md](docs/INTEGRATION.md): API contract, mathematical corrections and caveats.
- [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md): separate curated static-data agreement.

## Current implementation

The canonical frontend is the root React/TypeScript/Vite app.
src/App.tsx renders the API status, published-observation browser and upload workbench.
Components use typed services to consume either the curated manifest or the FastAPI result.

backend/app.py handles uploads, bounded concurrency and artifact serving.
backend/analysis.py orchestrates moving_object_pipeline.py and exports four image layers, CSV, JSON and a top-candidate plot.
Generated outputs live in ignored .runtime/, while raw inputs are temporary.
The Python pipeline uses scientific libraries already present in the supplied code; do not duplicate its mathematics in JavaScript.

sky/ is the earlier independent Next.js prototype, preserved unchanged. Use root npm commands for the integrated site. If changing sky/, read its AGENTS.md and version-specific local Next.js documentation first.
Do not import its placeholder images or approximate target catalogue as verified scientific data.

## Environment and commands

Node 24.22.3 and npm; Python 3.12 in .venv. Use package-lock.json and requirements.lock.txt.
Do not generate competing JavaScript lockfiles or install Python packages globally.

```bash
npm ci
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
npm run dev:full
```

The integrated site is http://localhost:5173; internal API is http://127.0.0.1:8000.
The launcher stops both services on Ctrl+C. Restart after Python changes.

Validation:

```bash
npm run build
npm run lint
npm run test:frontend
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

For this existing WSL workspace, ignored .tools/ may contain Node and a managed Python installation. Do not assume these exist after cloning. Keep tools and dependencies within one operating system.

## Contracts and validation

Keep docs, TypeScript types, runtime checks, Python outputs and focused tests aligned when changing interfaces.
The uploaded-run API contract differs from the curated manifest. Do not silently treat generated runs as reviewed publications.
Coordinate matching searches published target centers only; no live archive query is implemented.

Report actual checks and failures. Successful HTTP requests are not browser verification.
Synthetic regression tests and temporary browser checks do not establish scientific validity.
Known earlier lint audit findings and the test client's deprecation warning are documented; inspect current output before reporting their status. Do not run npm audit fix --force without approval.

## Scientific integrity

Never fabricate observations, dates, bands, provenance or archive capabilities.
Complete timestamps produce pixel/day speed; unknown times consistently use frame units. Do not label frame indices as UTC dates.
Use actual WCS for RA/Dec; user-entered region coordinates do not create an astrometric solution.
Candidate flux is integrated Z-map signal, not calibrated photometry.
Z is approximate and ranking scores are uncalibrated heuristics, not probabilities or Planet X detections.
Keep fixtures explicitly synthetic and outside published astronomical assets.
Artem/Niyati must review comparability, wavelength selections, calibration and scientific interpretation before demonstrating real data.
