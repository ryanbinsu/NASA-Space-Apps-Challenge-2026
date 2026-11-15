# Final submission handoff

## Demonstration entry point

The submitted integrated application runs from the **repository root**, not sky/.

```bash
npm ci
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
npm run dev:full
```

Open http://localhost:5173. The launcher also starts the Python API on loopback port 8000.
For an existing installed environment, only npm run dev:full is needed. See the root README for WSL-local Node setup.
Do not recreate the existing environment during a time-critical demo unnecessarily.

No development server was restarted during final repository cleanup. Start it deliberately when presenting.

## Supported demonstration

1. Identify the integrated frontend and explain that published targets are currently empty.
2. Upload 3–8 comparable FITS exposures (with a celestial WCS) or aligned-star-rich standard images.
3. Show parameter controls and run all five processing stages.
4. Inspect aligned/cleaned/difference/Z layers, playback and candidate overlays.
5. Select a tracklet, explain pixel/time units and the heuristic ranking, then export CSV/JSON/plot.
6. Show explicit error/no-candidate handling rather than substituting fake observations.

Use actual reviewed observations if available. If using synthetic regression/demo fixtures, say so prominently.
No real dataset is bundled, and passing synthetic tests is not a scientific-discovery claim.

## What is separate

The newer coordinate-to-archive CLI is in root spherex_*.py modules; its instructions are [here](ARCHIVE_PIPELINE.md).
It is not wired into the website. Its network retrieval was not exercised during this submission cleanup.
The earlier sky/ Next.js UI remains in the repository as a prototype, not the runtime entry point.

## Evidence and limitations

The integration previously passed production build, lint, three frontend tests, sixteen Python tests and a temporary Chromium end-to-end workflow. Final-cleanup checks are reported by the accompanying handover; distinguish those from a GitHub CI run.
The new GitHub workflow has not run remotely until the changes are committed and pushed.

Read [the mathematics review](MATHEMATICS_REVIEW.md) before describing significance, confidence, time units or the newer standalone detector.
Important limitations include approximate correlated noise, heuristic ranking, short overlapping triplets and unverified data comparability.
No confirmed Planet X detection, calibrated probability or complete live-coordinate web search is claimed.

## Submission owner actions

- Review the local diff and approve any commit/push; cleanup itself does not publish changes.
- Use the correct repository URL/branch and the team's actual demo/video/materials in the challenge submission.
- Verify the final scientific narrative with Niyati/Artem and presentation requirements with Pranav.
- Confirm the actual hosting/demo status. A local URL or downloadable frontend artifact is not a public deployed application.

Research is preserved at [research/RESEARCH.md](research/RESEARCH.md).
