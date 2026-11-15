# Provisional observation contract: version 1

**Proposed application interface; Artem and Niyati must review before real exports.**

This document covers curated static publications. The integrated uploaded-run API has a separate [contract and mathematics guide](INTEGRATION.md); generated analysis results are not automatically reviewed publications.
This does not describe the archive API.

## Delivery and target

Export public/observations/manifest.json and browser images beneath the same directory.
The initial manifest is honestly empty:

```json
{ "schemaVersion": 1, "targets": [] }
```

Unsupported versions fail loading; additive fields are tolerated.
Type definitions: src/types/observations.ts. Runtime checks: src/services/observations.ts.

Each target has:

| Field | Meaning |
| --- | --- |
| id | Stable nonempty ID, unique across targets |
| name | Nonempty human-readable name |
| raDegrees | Finite decimal degrees in [0, 360) |
| decDegrees | Finite decimal degrees in [-90, 90] |
| coordinateFrame | Proposed fixed value ICRS; never silently relabel another frame |
| observations | Array; empty means no observations included |

Coordinates identify the chosen region center, not necessarily a moving source.
No field size or search radius is inferred.

## Observations

Common fields:

| Field | Meaning |
| --- | --- |
| id | Stable nonempty ID, unique within its target |
| status | ready, unavailable or incompatible |
| observedAt | UTC YYYY-MM-DDTHH:mm:ssZ or YYYY-MM-DDTHH:mm:ss.sssZ; null only for excluded records with unknown time |
| provenance | Source array: datasetId, productId, sourceUrl |

datasetId identifies the actual collection/release, productId the actual product, and sourceUrl an HTTPS retrieval or authoritative product reference.
Ready frames require at least one source; composite images list every contributing product.
Excluded records may have an empty source array if no product was identified; explain this in reason.

Ready records additionally require:

| Field | Meaning |
| --- | --- |
| imagePath | Relative PNG, WebP or JPEG path beneath the manifest directory |
| spectral.description | Actual channel, spectral selection or compositing method |
| spectral.wavelengthMinMicrometers | Positive finite lower wavelength bound |
| spectral.wavelengthMaxMicrometers | Finite upper bound, at least the lower bound |
| processing.description | Alignment, masking, scaling and transformations; include reproducible references as needed |
| processing.pipelineVersion | Nonempty processing revision, such as a Git commit |
| processing.comparisonGroup | Nonempty target-local ID for a reviewed comparable series |

Wavelength units are micrometers. Bounds alone do not establish comparability; do not invent generic SPHEREx band names.
Allowed image paths use slash-separated ASCII letters, digits, underscores and hyphens, ending in a lowercase png/webp/jpg/jpeg extension.
Path syntax example only: target-id/frame-id.png. No external image URL, absolute path, traversal, spaces, query string or FITS input.
Resolve paths against the manifest directory, not the current page.

Excluded records require a nonempty reason and omit imagePath, spectral and processing.
Use unavailable for known acquisition/processing failures, incompatible for identified observations unsuitable for the comparison.
Do not invent records to fill gaps.

## Ordering and missing data

Order known timestamps ascending, breaking ties by ID ascending using code-point comparison.
Unknown timestamps come last and cannot enter playback. IDs remain stable when order changes.
The loader rejects incorrect ordering rather than quietly sorting.

- Empty targets: no targets published.
- Empty observations: no observations included, not proof the archive has none.
- Excluded record: explicit known failure or incompatibility.
- Unknown optional metadata: omit; never guess required metadata or use empty strings.
- Unknown required display metadata: exclude the record with a reason.
- HTTP, JSON or schema failure: load error, not a valid empty dataset.
- Missing image file: explicit asset error in the future viewer. Phase 1 does not request images.

## Scientific decisions requiring Artem and Niyati's approval

1. ICRS coordinates and footprint metadata for the future viewer.
2. Timestamp meaning: proposed exposure midpoint. Check source time scale and record conversions in processing provenance; do not relabel FITS times as UTC. Multi-exposure products may require intervals and a revised contract.
3. Spectral semantics: channels, spatial wavelength variation and composites may need richer metadata than a range.
4. Each comparison group's grid, dimensions, orientation, pixel scale, registration, masks and display normalization.
5. Actual availability of enough comparable epochs for selected targets.
6. Future difference products and interpretation; no difference-image contract is approved.

Until reviewed, this contract supports engineering collaboration only.
Ready does not certify scientific validity, and rendered images are not automatically quantitative calibrated measurements.
[Official archive access documentation](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access/) informs future acquisition; the application does not call it.
