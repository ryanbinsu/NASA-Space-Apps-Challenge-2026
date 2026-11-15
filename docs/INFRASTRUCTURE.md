# Current infrastructure and tooling

## Runtime topology

The local stack has a browser frontend and a Python processing service.
npm run dev:full starts Uvicorn on 127.0.0.1:8000, waits for health readiness, then starts Vite on 127.0.0.1:5173.
The browser uses port 5173; Vite forwards /api to Python. No development CORS middleware is needed.

The launcher is scripts/dev.mjs and uses Node's built-in child_process. It chooses .venv/bin/python on Linux/macOS or .venv/Scripts/python.exe on Windows.
API startup failure prevents silently starting an unusable stack. Either child's exit stops its sibling; Ctrl+C stops both.

Python code changes require restarting the stack; no Python reload supervisor is configured. Vite handles normal frontend refresh.

## Toolchain and installation

- Node 24.22.3 is recorded in .nvmrc; package.json accepts compatible Node 24 releases from that version.
- npm installs the frontend. npm ci uses package-lock.json; npm install is for intentional dependency changes.
- Python 3.12 is recorded in .python-version. requirements.txt records direct packages and requirements.lock.txt records the validated complete environment.
- Install Python dependencies inside .venv as shown in the README. The existing workspace used an ignored managed Python 3.12 toolchain because system Python 3.14 lacked headers needed to build sep.

Use Node/npm/Python from the same operating system as the repository's dependency installation. WSL Linux and Windows node_modules are not interchangeable.
.tools/ is workspace convenience tooling, not a required path after cloning.

## Why each dependency exists

React/react-dom render the UI; Vite and its React plugin serve/build it.
TypeScript and type declaration packages check browser/build code. ESLint, typescript-eslint, React plugins and globals check code patterns.
No new npm runtime dependency was needed for integration or process management.

Scientific libraries were already imported by the supplied pipeline: NumPy, pandas, SEP, matplotlib, SciPy, Astropy, reproject, Astroalign and ImageIO. Pillow supports ordinary image reading/export and preflight dimension checks.
FastAPI adds the HTTP/parameter boundary, Uvicorn serves it and python-multipart parses file uploads.
httpx is used by the API regression test client. The current upstream test client emits an httpx-to-httpx2 deprecation warning; tests still pass.

The Python lock includes transitive scientific dependencies. Review both direct and full requirements when changing this environment.

## Configuration files

| File | Purpose |
| --- | --- |
| vite.config.ts | React plugin and /api proxy for dev/preview |
| tsconfig.json | Strict browser/React checks, no emit |
| tsconfig.node.json | Separate strict check for Vite configuration |
| eslint.config.js | Root frontend/tooling lint; sky/ has its own separate configuration |
| package.json | Frontend scripts and direct npm dependencies |
| package-lock.json | Resolved npm dependency tree |
| requirements.txt / requirements.lock.txt | Direct/full Python environment |
| .nvmrc / .python-version | Team runtime versions |
| .gitattributes | LF text normalization |
| .gitignore | Generated/environment/data exclusions |

There are no required environment secrets. SPHEREX_RUNS_DIR optionally changes where Python stores/serves generated runs, particularly in isolated tests.

## Commands and generated output

npm run build checks both TypeScript configurations, then writes dist/.
npm run preview serves that existing build and forwards /api to a separately running API on port 8000.
npm run lint checks the root app, scripts and frontend tests with warnings treated as failures.
npm run test:frontend uses Node's built-in test runner; Python tests use unittest and FastAPI's test client.

The build copies public/ into dist/. It does not validate the curated manifest at build time; the browser validator does that when loading.

After building, Uvicorn can serve dist/ directly on port 8000, with /api routes registered first.
That is a local single-port option, not a deployment. The Python server is started after building so the static directory exists at import time.

## Storage and resource model

| Path | Contents / behavior |
| --- | --- |
| public/observations/ | Curated public manifest and eventual reviewed images |
| .runtime/runs/<UUID>/ | Generated PNG layers, JSON, CSV and optional candidate plot |
| OS temporary directory | Uploaded raw inputs, removed after the request |
| .venv/ | Isolated Python installation |
| node_modules/ | npm packages |
| dist/ | Production frontend assets |
| .tools/ | Local toolchains, temporary browser harness and synthetic fixtures |

Inputs are bounded to 3–8 files, 20 MiB each, 100 MiB total and 1,048,576 pixels each.
An analysis rejects more than 200 extracted peaks in any frame and more than 10,000 possible tracklets, avoiding uncontrolled combinatorial linking.
Only one analysis runs at once in one Python process. Do not add multiple workers assuming the in-memory lock is shared across them.

Runs persist without automatic cleanup and are served publicly to anyone who can reach the local process. Input hashes support identity checking, not proof of scientific authenticity.
Failed runs may leave empty/partial output directories. Disk usage should be monitored during extended local use.

## Hosting status and remaining work

No public deployment, CI workflow, database, authentication, queue, remote object store or Docker setup is implemented.
Vercel was proposed for a static frontend; static hosting alone cannot execute the scientific Python API.
A future public host must provide a compatible Python runtime/API, same-origin routing or deliberate CORS, storage limits, ingress controls and multi-user operational decisions.
These are future hosting decisions, not prerequisites added to the local demonstration.

Existing sky/ remains a separate Next.js prototype. Its npm lock and configuration are preserved, but it is not launched or linted by the root application commands.

## Validation and debt

The integration guide records the synthetic mathematical/API and browser checks performed.
Tests exercise mechanics, not real SPHEREx calibration or scientific discovery validity.
Temporary Chromium tooling/libraries were placed under ignored .tools/ (the browser binary is in the normal user cache); no browser package was added to the application.

The earlier npm audit reported moderate issues in the development lint chain. Recheck npm audit and npm audit --omit=dev when changing dependencies rather than treating historical results as current guarantees.
No forced downgrade, database or public deployment was introduced.
