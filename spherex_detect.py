"""
spherex_detect.py
==================
Moving-object detection pipeline for SPHEREx exposures. Consumes the
output of spherex_fetch_cli.py / spherex_download.py (a target directory
containing manifest.csv and one <obs_id>_D<detector>/IMAGE.fits per
exposure) and runs:

    Step 1: WCS alignment of all exposures onto a common pixel grid
    Step 2: Cosmic-ray removal, sky-background subtraction, flux normalization
    Step 3: Z-score difference imaging against a median "reference" stack
    Step 4: Tracklet linking (3-frame straight-line motion candidates)
    Step 5: Confidence scoring, discoveries.csv + top_discovery.png

This module is designed to be called either standalone (point it at an
already-downloaded target directory) or from spherex_pipeline.py, which
chains it directly onto a fresh coordinate -> query -> download run.
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import sep
import matplotlib.pyplot as plt
from scipy.ndimage import median_filter
from astropy.io import fits
from astropy.wcs import WCS
from astropy.stats import sigma_clipped_stats
from reproject import reproject_interp


# =====================================================================
# SPHEREX DATA DISCOVERY (CONNECTS TO manifest.csv FROM spherex_download.py)
# =====================================================================

def get_spherex_exposures(target_dir: str | Path, detector: int | None = None) -> list[Path]:
    """
    Reads manifest.csv (written by spherex_download.download_and_split) to
    find IMAGE.fits files for a target, optionally restricted to a single
    detector (1-6), sorted chronologically by MJD so motion tracking runs
    in exact time order.

    manifest.csv columns (per spherex_download.py):
        obs_id, detector, t_min_mjd, t_max_mjd, ra_deg, dec_deg,
        em_min_m, em_max_m, output_dir, access_url, skipped
    """
    target_path = Path(target_dir)
    if not target_path.exists():
        raise FileNotFoundError(f"Target directory not found: {target_path}")

    manifest_path = target_path / "manifest.csv"
    timed_files: list[tuple[float, Path]] = []

    if manifest_path.exists():
        manifest_df = pd.read_csv(manifest_path)

        if detector is not None:
            if "detector" not in manifest_df.columns:
                raise ValueError(
                    f"manifest.csv at {manifest_path} has no 'detector' column; "
                    "cannot filter by detector."
                )
            manifest_df = manifest_df[manifest_df["detector"] == detector]

        for _, row in manifest_df.iterrows():
            img_path = Path(row["output_dir"]) / "IMAGE.fits"
            if not img_path.exists():
                continue
            mjd = row.get("t_min_mjd", None)
            timed_files.append((float(mjd) if pd.notna(mjd) else np.nan, img_path))

    # Fallback (no manifest, or manifest matched nothing on disk): glob directly
    # and read MJD-OBS from FITS headers instead.
    if not timed_files:
        image_paths = sorted(target_path.glob("*/IMAGE.fits"))
        if detector is not None:
            image_paths = [p for p in image_paths if p.parent.name.endswith(f"_D{detector}")]
        for idx, img_path in enumerate(image_paths):
            with fits.open(img_path) as hdul:
                hdr = hdul[0].header
                mjd = hdr.get("MJD-OBS")
                if mjd is None and len(hdul) > 1:
                    mjd = hdul[1].header.get("MJD-OBS")
                timed_files.append((float(mjd) if mjd is not None else float(idx), img_path))

    if not timed_files:
        raise FileNotFoundError(
            f"No IMAGE.fits files found for detector={detector} inside {target_path}"
        )

    # Any missing MJDs fall back to arrival order rather than breaking the sort.
    timed_files = [
        (t if not np.isnan(t) else float(i), p) for i, (t, p) in enumerate(timed_files)
    ]
    timed_files.sort(key=lambda item: item[0])
    sorted_paths = [item[1] for item in timed_files]

    print(f"Found {len(sorted_paths)} SPHEREx exposure(s) in '{target_path}' (detector={detector}).")
    return sorted_paths


# =====================================================================
# STEP 1: COORDINATE TRANSFORMATIONS & IMAGE ALIGNMENT
# =====================================================================

def load_fits_image(filepath: Path, hdu_index: int = 0):
    """Loads image data, header, WCS coordinate map, and timestamp from a FITS file."""
    with fits.open(filepath) as hdul:
        # Auto-fallback to HDU 1 if HDU 0 has no image array (true for
        # spherex_download.py's split files: HDU0 is PRIMARY/empty).
        if hdul[hdu_index].data is None and len(hdul) > 1:
            hdu_index = 1
        hdu = hdul[hdu_index]
        data = np.nan_to_num(hdu.data.astype(np.float64), nan=0.0)
        header = hdu.header
        wcs = WCS(header) if header.get("CTYPE1") else None
        timestamp = header.get("MJD-OBS", None)
    return data, header, wcs, timestamp, hdu_index


def align_fits_stack(filepaths: list[Path], hdu_index: int = 0):
    """Aligns any number of FITS exposures onto the WCS grid of the first exposure."""
    ref_data, ref_header, ref_wcs, ref_time, active_hdu = load_fits_image(filepaths[0], hdu_index)
    aligned_images = [ref_data]
    timestamps = [float(ref_time) if ref_time is not None else 0.0]

    for idx, path in enumerate(filepaths[1:], start=1):
        with fits.open(path) as hdul:
            aligned_data, _ = reproject_interp(hdul[active_hdu], ref_header)
            aligned_data = np.nan_to_num(aligned_data, nan=0.0)
            aligned_images.append(aligned_data)
            t = hdul[active_hdu].header.get("MJD-OBS", None)
            timestamps.append(float(t) if t is not None else float(idx))

    return aligned_images, ref_wcs, timestamps


def pixel_to_radec(x: float, y: float, wcs: WCS | None):
    """Converts pixel coordinates (x, y) into celestial coordinates (RA, Dec) in degrees."""
    if wcs is None:
        return None, None
    sky_coord = wcs.pixel_to_world(x, y)
    return float(sky_coord.ra.deg), float(sky_coord.dec.deg)


def run_step1(filepaths: list[Path], hdu_index: int = 0):
    """Main entry point for Step 1."""
    return align_fits_stack(filepaths, hdu_index=hdu_index)


# =====================================================================
# STEP 2: NOISE REDUCTION & BACKGROUND SUBTRACTION
# =====================================================================

def remove_cosmic_rays(image: np.ndarray, filter_size: int = 3, sigma_thresh: float = 5.0) -> np.ndarray:
    """
    Removes single-pixel cosmic rays and hot-pixel glitches.

    FIX: the original version ran a blanket median_filter over the *entire*
    image, which blurs every real point source (stars, moving objects) right
    along with cosmic rays, suppressing exactly the signal we're trying to
    detect. This version instead computes a median-filtered version of the
    image only as a local-background reference, finds pixels whose residual
    above that reference is a sigma-clipped statistical outlier (i.e. actually
    looks like a cosmic ray / hot pixel, not a point source that spans several
    pixels), and replaces *only those flagged pixels* with the local median.
    Everything else -- including real PSF cores -- is left untouched.
    """
    median_img = median_filter(image, size=filter_size)
    residual = image - median_img
    _, med_resid, std_resid = sigma_clipped_stats(residual, sigma=3.0, maxiters=5)
    std_resid = std_resid if std_resid > 0 else 1e-6

    outlier_mask = residual > (med_resid + sigma_thresh * std_resid)
    cleaned = image.copy()
    cleaned[outlier_mask] = median_img[outlier_mask]
    return cleaned


def subtract_sky_background(image: np.ndarray, box_size: int = 64):
    """Models 2D sky background glow, subtracts it, and measures global RMS noise."""
    data = np.ascontiguousarray(image, dtype=np.float64)
    bkg = sep.Background(data, bw=box_size, bh=box_size, fw=3, fh=3)
    clean_image = data - bkg.back()
    rms_noise = float(bkg.globalrms)
    return clean_image, rms_noise


def normalize_flux(
    image: np.ndarray,
    reference_image: np.ndarray,
    min_bright_px: int = 20,
    min_scale: float = 0.2,
    max_scale: float = 5.0,
):
    """
    Matches brightness scale of 'image' to 'reference_image' using bright star pixels.

    FIX: this was the main source of the absurd Z-scores (thousands instead
    of tens) seen in top_discovery.png cutouts. The old version picked
    "bright" pixels using a plain 99th-percentile cut. On a frame with few
    real stars in the box, the top 1% is often just noise, not starlight --
    so the resulting scale_factor could blow up arbitrarily (e.g. 100x),
    multiplying that one frame's noise by the same huge factor and producing
    single-frame Z-score spikes that were really a normalization artifact,
    not a real transient.

    This version:
      1. Uses sigma-clipped stats to define "bright" robustly (median + 5
         sigma above the robust background), not a blind percentile.
      2. Requires a minimum number of bright pixels before trusting the
         computed scale at all -- otherwise it leaves the frame unscaled.
      3. Clamps the final scale factor to [min_scale, max_scale]; real
         flat-field/throughput drift between SPHEREx exposures is small,
         so a factor outside that range is itself a sign of an unreliable
         estimate, not real physics.
    """
    _, ref_med, ref_std = sigma_clipped_stats(reference_image, sigma=3.0, maxiters=5)
    _, img_med, img_std = sigma_clipped_stats(image, sigma=3.0, maxiters=5)

    ref_thresh = ref_med + 5 * ref_std
    img_thresh = img_med + 5 * img_std

    ref_bright_px = reference_image[reference_image > ref_thresh]
    img_bright_px = image[image > img_thresh]

    if ref_bright_px.size < min_bright_px or img_bright_px.size < min_bright_px:
        # Not enough reliable "bright" pixels to trust a scale estimate --
        # better to leave the frame unscaled than to guess and amplify noise.
        return image, 1.0

    ref_bright = np.median(ref_bright_px)
    img_bright = np.median(img_bright_px)

    if img_bright <= 0:
        return image, 1.0

    scale_factor = ref_bright / img_bright
    scale_factor = float(np.clip(scale_factor, min_scale, max_scale))
    return image * scale_factor, scale_factor


def run_step2(aligned_images: list[np.ndarray], filter_size: int = 3, box_size: int = 64, normalize: bool = True):
    """Main entry point for Step 2."""
    cleaned_images = []
    noise_levels = []

    for idx, img in enumerate(aligned_images):
        denoised = remove_cosmic_rays(img, filter_size=filter_size)
        sky_sub, rms = subtract_sky_background(denoised, box_size=box_size)

        if normalize and idx > 0:
            sky_sub, scale = normalize_flux(sky_sub, cleaned_images[0])
            rms = rms * scale

        cleaned_images.append(sky_sub)
        noise_levels.append(rms)

    return cleaned_images, noise_levels


# =====================================================================
# STEP 3: STATISTICAL ANALYSIS OF IMAGE DIFFERENCES
# =====================================================================

def compute_zscore_difference(science_img: np.ndarray, ref_img: np.ndarray, science_rms: float, ref_rms: float):
    """Computes pixel-wise Z-score significance map from difference image."""
    diff = science_img - ref_img
    combined_noise = np.sqrt(science_rms**2 + ref_rms**2)
    if combined_noise == 0:
        combined_noise = 1e-6
    z_map = diff / combined_noise
    return diff, z_map


def extract_candidates(
    z_map: np.ndarray,
    frame_idx: int,
    timestamp: float,
    wcs=None,
    z_thresh: float = 5.0,
    min_area: int = 3,
    max_sane_z: float = 200.0,
):
    """
    Extracts statistically significant peaks (Z > z_thresh) and checks for star dipoles.

    FIX: adds an `is_artifact` flag for peaks that are statistically
    implausible for a real astrophysical source -- Z-scores in the thousands
    (as seen before the normalize_flux / cosmic-ray fixes above) basically
    never happen for genuine point sources once noise is estimated properly;
    they're single-pixel glitches or normalization blow-ups that slipped
    through. Flagged peaks are still recorded (so nothing is silently
    hidden) but link_tracklets excludes them from tracklet-building by
    default, and score_discovery_confidence / compute_motion_score penalize
    them heavily if they end up in a tracklet anyway.
    """
    data = np.ascontiguousarray(z_map, dtype=np.float64)
    objects = sep.extract(data, thresh=z_thresh, minarea=min_area)

    candidates = []
    h, w = z_map.shape

    for obj in objects:
        x, y = float(obj["x"]), float(obj["y"])
        peak_z = float(obj["peak"])
        flux = float(obj["flux"])
        npix = int(obj["npix"])

        x_int, y_int = int(round(x)), int(round(y))
        x_min, x_max = max(0, x_int - 5), min(w, x_int + 6)
        y_min, y_max = max(0, y_int - 5), min(h, y_int + 6)
        cutout = z_map[y_min:y_max, x_min:x_max]
        min_neg_z = float(np.min(cutout)) if cutout.size > 0 else 0.0

        ra, dec = pixel_to_radec(x, y, wcs)

        is_artifact = bool(peak_z > max_sane_z)

        candidates.append({
            "frame": frame_idx,
            "time": timestamp,
            "x": x,
            "y": y,
            "ra": ra,
            "dec": dec,
            "peak_z": peak_z,
            "flux": flux,
            "min_neg_z": min_neg_z,
            "npix": npix,
            "is_artifact": is_artifact,
        })

    return candidates


def run_step3(
    cleaned_images: list[np.ndarray],
    noise_levels: list[float],
    timestamps: list[float],
    wcs=None,
    z_thresh: float = 5.0,
    max_sane_z: float = 200.0,
):
    """Main entry point for Step 3."""
    if len(cleaned_images) >= 3:
        master_ref = np.median(np.stack(cleaned_images, axis=0), axis=0)
        # RMS of a median stack of N Gaussian-noise frames with equal sigma
        # is ~1.253 * sigma / sqrt(N) (the 1.253 factor accounts for the
        # efficiency loss of the median vs. the mean estimator).
        ref_rms = float(1.253 * np.median(noise_levels) / np.sqrt(len(cleaned_images)))
    else:
        master_ref = cleaned_images[0]
        ref_rms = noise_levels[0]

    all_frame_candidates = []
    z_maps = []

    for idx, (img, rms, t) in enumerate(zip(cleaned_images, noise_levels, timestamps)):
        _, z_map = compute_zscore_difference(img, master_ref, rms, ref_rms)
        z_maps.append(z_map)
        cands = extract_candidates(
            z_map, frame_idx=idx, timestamp=t, wcs=wcs, z_thresh=z_thresh, max_sane_z=max_sane_z
        )
        all_frame_candidates.append(cands)

    n_artifacts = sum(c["is_artifact"] for frame in all_frame_candidates for c in frame)
    if n_artifacts:
        print(f"    Flagged {n_artifacts} peak(s) as likely artifacts (Z > {max_sane_z}); excluded from linking by default.")

    return all_frame_candidates, z_maps


# =====================================================================
# STEP 4: MOTION SCORING METRICS (LINKING TRACKLETS)
# =====================================================================

def compute_tracklet_metrics(tracklet: list[dict]):
    """Evaluates velocity consistency and linear trajectory RMSE across linked exposures."""
    times = np.array([pt["time"] for pt in tracklet], dtype=np.float64)
    xs = np.array([pt["x"] for pt in tracklet], dtype=np.float64)
    ys = np.array([pt["y"] for pt in tracklet], dtype=np.float64)

    dt = np.diff(times)
    dt = np.where(dt == 0, 1.0, dt)

    dx = np.diff(xs)
    dy = np.diff(ys)
    speeds = np.sqrt(dx**2 + dy**2) / dt

    mean_speed = float(np.mean(speeds))
    speed_std = float(np.std(speeds))
    velocity_consistency = float(np.exp(-speed_std / (mean_speed + 1e-5)))

    t_norm = times - times[0]
    if np.all(t_norm == 0):
        t_norm = np.arange(len(times), dtype=np.float64)

    poly_x = np.polyfit(t_norm, xs, deg=1)
    poly_y = np.polyfit(t_norm, ys, deg=1)
    pred_x = np.polyval(poly_x, t_norm)
    pred_y = np.polyval(poly_y, t_norm)

    residuals = np.sqrt((xs - pred_x)**2 + (ys - pred_y)**2)
    linearity_rmse = float(np.mean(residuals))

    return {
        "mean_speed_px": mean_speed,
        "velocity_consistency": velocity_consistency,
        "linearity_rmse_px": linearity_rmse
    }


def link_tracklets(
    all_frame_candidates: list[list[dict]],
    max_step_px: float = 50.0,
    min_speed_px: float = 1.5,
    exclude_artifacts: bool = True,
):
    """
    Connects detections across consecutive exposures into candidate trajectories.

    FIX: with exclude_artifacts=True (the default), peaks flagged as
    is_artifact in extract_candidates are dropped before linking. This
    matters a lot in practice -- previously, hundreds of single-pixel
    glitches per frame could coincidentally line up within the straight-line
    tolerance purely by chance (combinatorial false positives), which is how
    a run could produce 1000+ "discoveries" that were mostly noise.
    """
    if len(all_frame_candidates) < 3:
        return []

    if exclude_artifacts:
        all_frame_candidates = [
            [c for c in frame if not c.get("is_artifact", False)] for frame in all_frame_candidates
        ]

    tracklets = []
    for f in range(len(all_frame_candidates) - 2):
        cands_0 = all_frame_candidates[f]
        cands_1 = all_frame_candidates[f + 1]
        cands_2 = all_frame_candidates[f + 2]

        for p0 in cands_0:
            for p1 in cands_1:
                dist01 = np.hypot(p1["x"] - p0["x"], p1["y"] - p0["y"])
                if not (min_speed_px <= dist01 <= max_step_px):
                    continue

                pred_x2 = p1["x"] + (p1["x"] - p0["x"])
                pred_y2 = p1["y"] + (p1["y"] - p0["y"])

                for p2 in cands_2:
                    pred_err = np.hypot(p2["x"] - pred_x2, p2["y"] - pred_y2)
                    if pred_err <= 5.0:
                        track = [p0, p1, p2]
                        metrics = compute_tracklet_metrics(track)
                        tracklets.append({"points": track, **metrics})

    return tracklets


def run_step4(
    all_frame_candidates: list[list[dict]],
    max_step_px: float = 50.0,
    min_speed_px: float = 1.5,
    exclude_artifacts: bool = True,
):
    """Main entry point for Step 4."""
    return link_tracklets(
        all_frame_candidates,
        max_step_px=max_step_px,
        min_speed_px=min_speed_px,
        exclude_artifacts=exclude_artifacts,
    )


# =====================================================================
# STEP 5: DISCOVERY CONFIDENCE MODELLING & REPORTING
# =====================================================================

def score_discovery_confidence(tracklet: dict) -> float:
    """Computes a calibrated [0, 1] confidence score for a candidate moving object."""
    pts = tracklet["points"]
    mean_z = float(np.mean([p["peak_z"] for p in pts]))
    worst_neg_z = float(np.min([p["min_neg_z"] for p in pts]))

    snr_score = float(1.0 - np.exp(-max(0.0, mean_z - 3.0) / 5.0))
    straightness_score = float(np.exp(-tracklet["linearity_rmse_px"] / 1.5))
    motion_score = 0.5 * straightness_score + 0.5 * tracklet["velocity_consistency"]

    dipole_ratio = abs(worst_neg_z) / (mean_z + 1e-5)
    dipole_penalty = 0.5 if (worst_neg_z < -4.0 and dipole_ratio > 0.5) else 1.0

    # FIX (defense in depth): link_tracklets excludes is_artifact peaks by
    # default, but if that's ever disabled, or an artifact slips through for
    # some other reason, heavily penalize it here too rather than letting it
    # report a high confidence.
    artifact_penalty = 0.3 if any(p.get("is_artifact", False) for p in pts) else 1.0

    confidence = (0.45 * snr_score + 0.55 * motion_score) * dipole_penalty * artifact_penalty
    return round(float(np.clip(confidence, 0.0, 1.0)), 4)


# ---------------------------------------------------------------------
# STRETCH GOAL: a simple, independent "Motion Score"
#
#   Motion Score = pixel displacement x brightness confidence
#
# This is intentionally a much cruder metric than score_discovery_confidence
# above (no straightness/velocity-consistency weighting, no dipole penalty).
# It's meant as a quick, easy-to-explain sanity-check number: "how far did
# it move, scaled by how sure we are it's really a signal (not noise)?"
# Large displacement + low brightness confidence, or small displacement +
# high confidence, both get down-weighted relative to a candidate that
# scores well on both axes.
# ---------------------------------------------------------------------

def compute_motion_score(tracklet: dict) -> dict:
    """
    Motion Score = pixel displacement x brightness confidence.

    - pixel displacement: straight-line distance (px) between the first
      and last linked detection in the tracklet (not the summed path
      length -- for a 3-point near-straight track these are almost the
      same, but end-to-end displacement is simpler and cheaper to explain).
    - brightness confidence: the peak Z-score of each detection (how far
      above the background noise it is) squashed into [0, 1] with the same
      saturating curve used for snr_score in score_discovery_confidence,
      so "confidence" means the same thing in both metrics.

    Returns a dict with the three sub-values plus the final motion_score,
    so all of it can be dropped straight into discoveries.csv.
    """
    pts = tracklet["points"]
    p_start, p_end = pts[0], pts[-1]

    pixel_displacement = float(np.hypot(p_end["x"] - p_start["x"], p_end["y"] - p_start["y"]))

    mean_z = float(np.mean([p["peak_z"] for p in pts]))
    brightness_confidence = float(1.0 - np.exp(-max(0.0, mean_z - 3.0) / 5.0))

    # FIX (defense in depth, matches score_discovery_confidence): don't let
    # an artifact that slipped past link_tracklets' default filtering report
    # a big, confident-looking motion score.
    if any(p.get("is_artifact", False) for p in pts):
        brightness_confidence *= 0.3

    motion_score = pixel_displacement * brightness_confidence

    return {
        "pixel_displacement_px": round(pixel_displacement, 2),
        "brightness_confidence": round(brightness_confidence, 4),
        "motion_score": round(motion_score, 2),
    }


def plot_top_discovery(tracklet: dict, cleaned_images: list[np.ndarray], output_path: Path, box_radius: int = 30):
    """Saves a side-by-side frame cutout showing the top candidate moving across exposures."""
    pts = tracklet["points"]
    fig, axes = plt.subplots(1, len(pts), figsize=(4 * len(pts), 4))
    if len(pts) == 1:
        axes = [axes]

    center_x = int(round(np.mean([p["x"] for p in pts])))
    center_y = int(round(np.mean([p["y"] for p in pts])))
    h, w = cleaned_images[0].shape

    x0, x1 = max(0, center_x - box_radius), min(w, center_x + box_radius)
    y0, y1 = max(0, center_y - box_radius), min(h, center_y + box_radius)

    for ax, pt in zip(axes, pts):
        img = cleaned_images[pt["frame"]]
        cutout = img[y0:y1, x0:x1]
        vmin, vmax = np.percentile(cutout, [5, 99])
        ax.imshow(cutout, cmap="gray", vmin=vmin, vmax=vmax, origin="lower")
        ax.scatter(pt["x"] - x0, pt["y"] - y0, s=180, facecolors="none", edgecolors="lime", lw=2)
        ax.set_title(f"Exp {pt['frame']+1} | Z={pt['peak_z']:.1f}")
        ax.axis("off")

    plt.suptitle(f"Top Discovery (Confidence: {tracklet['confidence']*100:.1f}%)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


def run_step5(tracklets: list[dict], cleaned_images: list[np.ndarray], output_dir: Path, detector: int | None = None) -> pd.DataFrame:
    """Scores candidate tracklets, saves discoveries.csv, and plots top_discovery.png."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not tracklets:
        print("No valid moving tracklets found. Try lowering z_thresh or adjusting max_step_px.")
        return pd.DataFrame()

    rows = []
    for idx, tr in enumerate(tracklets):
        conf = score_discovery_confidence(tr)
        tr["confidence"] = conf
        motion = compute_motion_score(tr)
        p_start = tr["points"][0]
        p_end = tr["points"][-1]
        artifact_flag = any(p.get("is_artifact", False) for p in tr["points"])

        rows.append({
            "candidate_id": f"OBJ_{idx+1:03d}",
            "detector": detector,
            "confidence": conf,
            "artifact_flag": artifact_flag,
            "mean_snr_z": round(float(np.mean([p["peak_z"] for p in tr["points"]])), 2),
            "speed_px_per_unit_t": round(tr["mean_speed_px"], 2),
            "linearity_rmse_px": round(tr["linearity_rmse_px"], 3),
            "pixel_displacement_px": motion["pixel_displacement_px"],
            "brightness_confidence": motion["brightness_confidence"],
            "motion_score": motion["motion_score"],
            "start_x": round(p_start["x"], 2),
            "start_y": round(p_start["y"], 2),
            "end_x": round(p_end["x"], 2),
            "end_y": round(p_end["y"], 2),
            "start_ra": round(p_start["ra"], 6) if p_start["ra"] is not None else None,
            "start_dec": round(p_start["dec"], 6) if p_start["dec"] is not None else None,
            "end_ra": round(p_end["ra"], 6) if p_end["ra"] is not None else None,
            "end_dec": round(p_end["dec"], 6) if p_end["dec"] is not None else None,
        })

    df = pd.DataFrame(rows).sort_values(by="confidence", ascending=False).reset_index(drop=True)
    csv_path = output_dir / "discoveries.csv"
    df.to_csv(csv_path, index=False)

    best_track = max(tracklets, key=lambda t: t["confidence"])
    plot_path = output_dir / "top_discovery.png"
    plot_top_discovery(best_track, cleaned_images, output_path=plot_path)
    print(f"Saved results to {csv_path} and {plot_path}")

    return df


# =====================================================================
# MASTER PIPELINE RUNNER (single detector)
# =====================================================================

def run_pipeline_for_target(
    target_label: str,
    output_root: str | Path = "./spherex_output",
    detector: int | None = None,
    z_thresh: float = 5.0,
    max_step_px: float = 50.0,
    max_sane_z: float = 200.0,
    results_dir: str | Path | None = None,
) -> pd.DataFrame:
    """
    Processes all exposures for a given target (optionally restricted to one
    detector) found under <output_root>/<target_label>/.

    results_dir overrides where discoveries.csv / top_discovery.png are
    written (defaults to the target directory itself); spherex_pipeline.py
    uses this to keep per-detector outputs separate.
    """
    target_dir = Path(output_root) / target_label
    filepaths = get_spherex_exposures(target_dir, detector=detector)

    if len(filepaths) < 3:
        raise ValueError(
            f"Need at least 3 exposures to link moving tracks, but only found "
            f"{len(filepaths)} in {target_dir} (detector={detector})."
        )

    print(f"--- Step 1: Aligning {len(filepaths)} SPHEREx exposures ---")
    aligned_imgs, wcs_map, timestamps = run_step1(filepaths, hdu_index=0)

    print("--- Step 2: Removing cosmic rays, subtracting sky & normalizing flux ---")
    clean_imgs, sigmas = run_step2(aligned_imgs)

    print("--- Step 3: Computing statistical image differences (Z-scores) ---")
    frame_candidates, _ = run_step3(clean_imgs, sigmas, timestamps, wcs=wcs_map, z_thresh=z_thresh, max_sane_z=max_sane_z)
    print(f"    Extracted {sum(len(c) for c in frame_candidates)} raw transient peaks.")

    print("--- Step 4: Linking detections into moving tracklets & scoring motion ---")
    tracklets = run_step4(frame_candidates, max_step_px=max_step_px)
    print(f"    Linked {len(tracklets)} candidate moving tracklets.")

    print("--- Step 5: Modelling discovery confidence & exporting results ---")
    out_dir = Path(results_dir) if results_dir is not None else target_dir
    results_df = run_step5(tracklets, clean_imgs, output_dir=out_dir, detector=detector)

    if not results_df.empty:
        print("\nTop Discoveries:")
        print(results_df.head(10).to_string(index=False))

    return results_df


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "your_target_label_here"
    det = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run_pipeline_for_target(target_label=target, output_root="./spherex_output", detector=det)
