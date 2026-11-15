# Scientific processing boundary

Artem owns acquisition, FITS processing, alignment and differencing.
The supplied implementation is currently [moving_object_pipeline.py](../moving_object_pipeline.py).
The HTTP adapter in [backend/](../backend/) calls its stages; it does not replace the pipeline with browser mathematics.

Read [the integration/API guide](../docs/INTEGRATION.md) for stage controls, timestamp handling, numerical fixes and known scientific approximations.
Niyati and Artem should review these before interpreting real observations.

The curated publication interface remains [DATA_CONTRACT.md](../docs/DATA_CONTRACT.md).
Generated analysis JSON is a different contract and is not automatically a reviewed NASA/SPHEREx export.
Keep real dataset/release/product identifiers and processing provenance; never label synthetic test fixtures as NASA observations.

Python 3.12 with requirements.lock.txt is the validated environment.
Keep bulk downloads and intermediates outside Git; generated local runs go to ignored .runtime/.
