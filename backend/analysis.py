"""Translate uploaded files into pipeline inputs and JSON/browser artifacts."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from astropy.time import Time
from PIL import Image
from scipy.ndimage import binary_erosion

import moving_object_pipeline as pipeline

MAX_PIXELS = 1024 * 1024
MAX_CANDIDATES = 200


def inspect_input(path, hdu_index):
    if path.suffix.lower() in {".fits", ".fit", ".fts"}:
        with fits.open(path, memmap=True) as hdus:
            if hdu_index >= len(hdus):
                raise ValueError(f"HDU {hdu_index} does not exist.")
            header = hdus[hdu_index].header
            width, height = header.get("NAXIS1", 0), header.get("NAXIS2", 0)
            if header.get("NAXIS") != 2:
                raise ValueError("FITS input must be a 2D image; select its image HDU.")
        kind = "fits"
    else:
        with Image.open(path) as image:
            width, height = image.size
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Upload individual exposures, not an animated/multipage image.")
        kind = "raster"
    if min(width, height) < 32 or width * height > MAX_PIXELS:
        raise ValueError("Each image must be at least 32×32 and at most 1,048,576 pixels.")
    return kind


def analyze(paths, names, output, settings, supplied_times, source_label):
    kinds = [inspect_input(path, settings["hdu_index"]) for path in paths]
    if len(set(kinds)) != 1:
        raise ValueError("Use all FITS images or all standard images in one analysis.")
    is_fits = kinds[0] == "fits"
    warnings = [
        "Uploaded data provenance is user-supplied and has not been verified as NASA/SPHEREx data.",
        "Scores are heuristic rankings, not calibrated probabilities or confirmed discoveries.",
        "Z maps use an approximate scalar-noise model; reprojection, filtering and the shared reference introduce correlations.",
    ]
    header_times = [pipeline.load_fits_image(p, settings["hdu_index"])[3] for p in paths] if is_fits else [None] * len(paths)
    if supplied_times:
        if len(supplied_times) != len(paths):
            raise ValueError("Supply one UTC timestamp per uploaded file, or leave all blank.")
        try:
            times = [float(Time(value, format="isot", scale="utc").mjd) for value in supplied_times]
        except (ValueError, TypeError) as exc:
            raise ValueError("Timestamps must be valid UTC ISO dates, without the final Z.") from exc
        # Supplied UTC values are explicit user metadata; they override incomplete headers.
        warnings.append("UTC observation times were supplied by the user and override FITS headers.")
    else:
        times = header_times
    timed = all(t is not None and np.isfinite(t) for t in times)
    if timed:
        if len(set(times)) != len(times):
            raise ValueError("Observation times must be distinct; simultaneous images do not define motion.")
        order = sorted(range(len(paths)), key=lambda index: times[index])
    else:
        order = list(range(len(paths)))
        warnings.append("At least one observation time is unknown. Upload order and frame units are used for the entire sequence; no dates are invented.")
    paths = [paths[i] for i in order]
    names = [names[i] for i in order]
    times = [times[i] for i in order] if timed else list(map(float, range(len(paths))))
    aligned, wcs, _ = pipeline.run_step1(paths, is_fits=is_fits, hdu_index=settings["hdu_index"])
    shape = aligned[0].shape
    common = np.logical_and.reduce([np.isfinite(image) for image in aligned])
    common = binary_erosion(common, iterations=settings["filter_size"] // 2 + 5)
    if common.sum() < 1024:
        raise ValueError("Too little common valid sky area after alignment.")
    aligned = [np.where(common, image, np.median(image[common])) for image in aligned]
    cleaned, noise = pipeline.run_step2(
        aligned, filter_size=settings["filter_size"],
        box_size=settings["box_size"], normalize=settings["normalize"], valid_mask=common,
    )
    if not all(np.all(np.isfinite(image)) for image in cleaned) or not all(np.isfinite(noise)):
        raise ValueError("Processing produced nonfinite values; check image coverage and flux.")
    if any(value <= 0 for value in noise):
        raise ValueError("Background RMS must be positive. Flat/blank images cannot yield meaningful significance.")
    candidates, z_maps = pipeline.run_step3(
        cleaned, noise, times, wcs=wcs, z_thresh=settings["z_thresh"],
        min_area=settings["min_area"], valid_mask=common,
    )
    if any(len(frame) > MAX_CANDIDATES for frame in candidates):
        raise ValueError("More than 200 peaks per frame. Raise Z threshold/minimum area or use a smaller cutout.")
    tracks = pipeline.run_step4(candidates, max_step_px=settings["max_step_px"], min_speed_px=settings["min_step_px"])
    unit = "day" if timed else "frame"
    table = pipeline.run_step5(tracks, cleaned, output_csv=output / "candidates.csv",
                               output_plot=output / "top-candidate.png", time_unit=unit)
    reference = np.median(np.stack(cleaned), axis=0)
    low, high = np.percentile(np.concatenate([im[common] for im in cleaned]), [1, 99.5])
    if high <= low:
        high = low + 1
    raw_low, raw_high = np.percentile(np.concatenate([im[common] for im in aligned]), [1, 99.5])
    if raw_high <= raw_low:
        raw_high = raw_low + 1
    differences = [im - reference for im in cleaned]
    difference_limit = max(float(np.percentile(np.abs(np.stack(differences)[:, common]), 99.5)), 1e-6)
    frames = []
    for index, (path, name, image, clean, zmap, difference) in enumerate(zip(paths, names, aligned, cleaned, z_maps, differences)):
        for mode, data, vmin, vmax, cmap in [
            ("aligned", image, raw_low, raw_high, "gray"),
            ("cleaned", clean, low, high, "gray"),
            ("difference", difference, -difference_limit, difference_limit, "RdBu_r"),
            ("significance", zmap, -10, 10, "RdBu_r"),
        ]:
            plt.imsave(output / f"{index}-{mode}.png", data, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax)
        frames.append({
            "id": str(index), "filename": name,
            "observedAt": Time(times[index], format="mjd", scale="utc").isot + "Z" if timed else None,
            "time": times[index], "rms": float(noise[index]),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "candidates": candidates[index],
            "images": {mode: f"{index}-{mode}.png" for mode in ["aligned", "cleaned", "difference", "significance"]},
        })
    ranked = sorted(tracks, key=lambda item: item["confidence"], reverse=True)
    # Candidate IDs match the CSV, which assigns IDs before sorting.
    identities = {id(track): f"OBJ_{i+1:03d}" for i, track in enumerate(tracks)}
    result = {
        "schemaVersion": 1, "source": source_label or "User-uploaded sequence",
        "timeUnit": unit, "width": shape[1], "height": shape[0],
        "hasWcs": wcs is not None, "frames": frames, "settings": settings,
        "warnings": warnings, "candidateCount": sum(map(len, candidates)),
        "tracklets": [{"id": identities[id(track)], **track} for track in ranked],
        "csv": "candidates.csv", "topPlot": "top-candidate.png" if not table.empty else None,
        "validPixelFraction": float(common.mean()),
    }
    # Round-trip with strict JSON catches accidental NaN/Infinity before returning HTTP success.
    result = json.loads(json.dumps(result, allow_nan=False))
    (output / "result.json").write_text(json.dumps(result, indent=2))
    return result
