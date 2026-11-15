# Contributing

Start with [the README](README.md) and [documentation index](docs/README.md).
Use a focused branch and small pull request; explain the problem and behavior changed.

## Boundaries

- The submitted web application runs from the repository root: src/, backend/ and moving_object_pipeline.py.
- The standalone spherex_*.py archive CLI is a separate workflow, not a web API implementation.
- sky/ is the earlier UI prototype; it has separate tooling and instructions.
- Review shared interfaces with both producer and consumer owners before changing them.

## Validate

```bash
npm ci
npm run lint
npm run test:frontend
npm run build
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Use Node from .nvmrc and Python from .python-version. Install Python dependencies from requirements.lock.txt.
The [CI workflow](.github/workflows/ci.yml) repeats these checks on GitHub and produces a frontend artifact.

## Scientific changes

Document actual dataset/product identifiers, units, time scales, transformations and limitations.
Add expected-value regression fixtures for changed mathematics. Keep synthetic fixtures clearly labelled and out of published observations.
A heuristic score is not a probability; source review and passing tests do not certify a detection.

Keep generated datasets, .runtime/, spherex_output/, environments and credentials outside commits.
Do not change licensing, publish data, deploy or merge without the relevant owner's approval.
