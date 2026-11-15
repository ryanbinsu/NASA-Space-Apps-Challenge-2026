# Mathematics review for submission

This is a source-based engineering review of the submitted implementation, not independent scientific certification.
No application or mathematics code was changed during this review. Artem and Niyati remain responsible for scientific validation of real observations.

Read [the API and mathematics guide](INTEGRATION.md) for detailed equations and parameter definitions.

## Two implementations are present

The **website** calls backend/analysis.py, which imports moving_object_pipeline.py. The equations and corrections below describe that wired implementation.

The later **standalone archive toolchain** uses spherex_coords.py → spherex_query.py → spherex_download.py → spherex_detect.py, launched by spherex_pipeline.py. See [the standalone tool guide](ARCHIVE_PIPELINE.md).
It is separate from the website API. Source inspection is not evidence that live archive retrieval has succeeded in this review.

Important standalone differences requiring scientific/engineering follow-up:

- Its track prediction still assumes equally spaced frames rather than using the epoch-spacing ratio.
- It substitutes a time interval of one for duplicate epochs and can mix missing-time frame indices with real MJD values.
- Its field named linearity_rmse_px is computed as the mean residual distance rather than the root mean square.
- Invalid reprojection regions are zero-filled without the website adapter's common-footprint masking.
- It adds sigma-clipped normalization with a [0.2, 5] scale clamp, selective local-residual replacement and a high-Z artifact flag. These are heuristic safeguards; they are not independently validated calibration or proof that every Z>200 source is spurious.
- The residual replacement can still affect real compact-source cores; source shape/quality flags are not used to certify a cosmic ray.
- The standalone module retains “calibrated” confidence language in places, but the implemented score remains a weighted heuristic with no documented probability calibration. The reorganized CLI instructions now label it accurately.
- The standalone plot rescales each cutout independently; apparent brightness differences should not be interpreted quantitatively.

The website's synthetic regression tests do not establish correctness of the separate standalone toolchain.
The former root INSTRUCTIONS.md is now ARCHIVE_PIPELINE.md in this directory; its obsolete missing-module export notes have been corrected.
Keep this distinction visible in the submission and avoid attributing a capability to the website merely because a standalone module exists.

## What is implemented

| Stage | Actual computation | Appropriate interpretation |
| --- | --- | --- |
| Alignment | Celestial-WCS reprojection for FITS, or star-pattern registration for raster images | A common comparison grid; accuracy still needs checking on the chosen dataset |
| Cleaning | Median filtering, SEP background estimation and optional bright-pixel normalization | Exploratory preprocessing; not a certified cosmic-ray or photometric-calibration procedure |
| Differences | Science image minus the pixel-wise median reference | Residual structure relative to the supplied sequence |
| Approximate Z | Difference divided by the quadrature sum of two scalar RMS estimates | A useful visualization/extraction statistic, not calibrated detection significance |
| Motion | Three consecutive detections, displacement bounds and a time-aware linear prediction | Candidate triplets consistent with approximately linear pixel motion |
| Ranking | Weighted signal/motion heuristics with a nearby-negative-residual penalty | A prioritization score, not a discovery probability |

## Equations checked against the source

- Difference: D = I − R.
- Combined scalar noise: sqrt(sigma_I² + sigma_R²).
- Approximate Z: D divided by that combined noise.
- Median-reference RMS estimate: 1.253314 × median(frame RMS) / sqrt(N).
- Inter-epoch speed: sqrt(delta_x² + delta_y²) / delta_t.
- Velocity consistency: exp(−std(pairwise speeds) / (mean(pairwise speeds) + 1e−5)).
- Position residual: distance from the separately fitted straight lines x(t), y(t).
- Linearity RMSE: sqrt(mean(residual distance²)).
- The final ranking combines signal and motion terms with weights 0.45 and 0.55, then applies a dipole penalty and bounds the result to [0, 1].

When real UTC epochs are complete, time differences are in days and speeds are pixels/day.
Otherwise every frame uses its sequence index and speeds are pixels/frame. No dates or physical elapsed times are inferred from file order.
The reported mean speed is the arithmetic mean of pairwise speeds, not a duration-weighted trajectory speed.

## Limitations to state explicitly

1. **Noise independence is an approximation.** Reprojection and median filtering correlate pixels. A science frame also contributes to its own reference, so the reference and science errors are not independent. Scalar quadrature does not model these covariances.
2. **Median uncertainty is approximate.** The 1.253314 factor is associated with an asymptotic independent-Gaussian median approximation. It is not an exact uncertainty calculation for a small, heteroscedastic or correlated image stack.
3. **The reference can contain the object.** A median reference may suppress a mover that occupies distinct pixels in different frames, but slow motion or repeated occupancy can retain source signal and reduce residuals. It does not guarantee removal.
4. **Preprocessing changes source structure.** Median filtering can attenuate compact/faint sources. Bright-pixel scaling is not matched-star photometric calibration and can be affected by saturation, variable sources or different spectral selections.
5. **Linking is deliberately simple.** Both consecutive displacement bounds and a fixed five-pixel prediction tolerance are used. There is no uncertainty-weighted association, orbit fitting, catalogue rejection, cross-triplet deduplication or proper-motion/parallax model.
6. **Units matter.** Step bounds are pixel displacement per pair, not angular velocity. WCS maps positions to coordinates, but the exported speed remains pixel/time. Integrated candidate flux is measured on the Z map, not calibrated photometric flux.
7. **Scores have no calibrated false-alarm meaning.** Ranking weights, scale constants and dipole thresholds are heuristics. A score of 0.9 does not mean a 90% chance of a genuine object.
8. **Tests establish mechanics.** Synthetic regression fixtures check known formulas and processing paths. They do not establish completeness, false-positive rate, astrometric accuracy or scientific validity on SPHEREx observations.

## Submission-safe description

“The application aligns a supplied image sequence, computes approximate difference statistics, links candidate detections into short linear-motion triplets, and ranks them for human inspection. Results are exploratory and require scientific validation.”

Avoid claiming a Planet X discovery, calibrated detection probabilities, validated SPHEREx performance or live archive retrieval.
