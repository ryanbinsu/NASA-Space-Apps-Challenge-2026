# Development, continuous integration and delivery

## One supported web stack

Use root npm commands for the React/Vite frontend and FastAPI service.
Node and Python versions are recorded in .nvmrc and .python-version.
Use package-lock.json and requirements.lock.txt for reproducible web-stack installs.

The archive CLI's requirements_v2.txt is separate and unpinned. Installing it over the validated web environment can change dependency resolution; use a separate virtual environment when evaluating it.
Do not infer that standalone archive behavior is tested because the web API tests pass.

## Continuous integration

[.github/workflows/ci.yml](../.github/workflows/ci.yml) runs on pushes, pull requests and manual dispatch.

The frontend job installs from the npm lock, runs lint and frontend tests, then builds the production frontend.
The Python job uses Python 3.12, installs the complete dependency lock, checks installed compatibility and runs the mathematics/API regression suite.
The newer standalone modules receive syntax checks only; no automated network query/download or scientific certification is claimed.

Jobs have bounded timeouts, dependency caching, read-only repository permissions and cancellation of superseded runs.
The earlier independent sky/ prototype is outside this workflow's runtime validation.

Local equivalents are documented in [CONTRIBUTING.md](../CONTRIBUTING.md).
The workflow is repository configuration only; it does not run on GitHub until committed/pushed to a repository with Actions enabled.
Local workflow parsing is not evidence of a successful hosted run.

## Delivery artifact

Successful frontend CI uploads dist/ as a downloadable build artifact with limited retention.
This is a reviewable static frontend artifact, **not a self-contained Python application** and not a deployment.
The backend source and locked Python requirements remain in the repository at the corresponding commit.

To reproduce a local single-port build:

```bash
npm ci
npm run build
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

The API serves dist/ when it exists at server startup. Open http://localhost:8000 for this local mode.

## Continuous deployment boundary

Automatic production deployment is intentionally not configured.
No approved host, credentials or public multi-user storage/ingress design is supplied, and static Vercel hosting alone cannot run the Python scientific pipeline.

A future deployment change must identify the Python host, frontend/API routing, artifact storage/retention and rollback procedure.
Deploy the same reviewed commit that passed checks, with the owner's approval.
Do not add a nominal deploy job that silently skips missing credentials or implies a public release occurred.

## Source-control hygiene

Work on focused branches; review interfaces and scientific changes with their owners.
Generated environments, local output, archive downloads, logs and Finder metadata are ignored.
Submission cleanup moves documentation only, preserves executable source paths, and leaves local tools/environments intact for the demo.
