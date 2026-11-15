import numpy as np
import pandas as pd
import sep
import matplotlib.pyplot as plt
from scipy.ndimage import median_filter, binary_erosion
from astropy.io import fits
from astropy.wcs import WCS
from astropy.time import Time
from reproject import reproject_interp
import astroalign as aa
import imageio.v3 as iio


# =====================================================================
# STEP 1: COORDINATE TRANSFORMATIONS & IMAGE ALIGNMENT
# =====================================================================

def load_fits_image(filepath, hdu_index=0):
    """Loads image data, header, WCS coordinate map, and timestamp from a FITS file."""
    with fits.open(filepath) as hdul:
        hdu = hdul[hdu_index]
        header = hdul[0].header.copy()
        header.update(hdu.header)
        if hdu.data is None or hdu.data.ndim != 2:
            raise ValueError("Select a two-dimensional FITS image HDU.")
        data = np.asarray(hdu.data, dtype=np.float64)
        wcs = WCS(header).celestial if header.get("CTYPE1") else None
        if wcs is not None and not wcs.has_celestial:
            wcs = None
        timestamp = None
        scale = str(header.get("TIMESYS", "UTC")).strip().lower()
        if header.get("MJD-OBS") is not None:
            timestamp = float(Time(header["MJD-OBS"], format="mjd", scale=scale).utc.mjd)
        elif header.get("DATE-OBS") is not None:
            timestamp = float(Time(header["DATE-OBS"], scale=scale).utc.mjd)
    return data, header, wcs, timestamp


def load_standard_image(filepath):
    """Loads a standard image (.png, .jpg, .tiff) and converts it to 2D grayscale float64."""
    img = iio.imread(filepath).astype(np.float64)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)
    return img


def align_fits_stack(filepaths, hdu_index=0):
    """Aligns a list of FITS files onto the WCS grid of the first (reference) image."""
    ref_data, ref_header, ref_wcs, ref_time = load_fits_image(filepaths[0], hdu_index)
    if ref_wcs is None:
        raise ValueError("FITS alignment requires a celestial WCS in the selected HDU.")
    aligned_images = [ref_data]
    timestamps = [ref_time]
    for path in filepaths[1:]:
        data, _, wcs, timestamp = load_fits_image(path, hdu_index)
        if wcs is None:
            raise ValueError("Every FITS image must have a celestial WCS.")
        aligned_data, footprint = reproject_interp((data, wcs), ref_wcs, shape_out=ref_data.shape)
        aligned_data[footprint <= 0] = np.nan
        aligned_images.append(aligned_data)
        timestamps.append(timestamp)
    # Never mix invented frame numbers with actual MJD dates.
    if any(t is None for t in timestamps):
        timestamps = list(map(float, range(len(filepaths))))
    return aligned_images, ref_wcs, timestamps


def align_standard_stack(filepaths):
    """Aligns a list of standard images (.png/.jpg) onto the first image using star patterns."""
    ref_data = load_standard_image(filepaths[0])
    aligned_images = [ref_data]
    timestamps = [0.0]

    for idx, path in enumerate(filepaths[1:], start=1):
        target_data = load_standard_image(path)
        aligned_data, footprint = aa.register(target_data, ref_data)
        aligned_data[footprint] = np.nan
        aligned_images.append(aligned_data)
        timestamps.append(float(idx))

    return aligned_images, timestamps


def pixel_to_radec(x, y, wcs):
    """Converts pixel coordinates (x, y) into celestial coordinates (RA, Dec) in degrees."""
    if wcs is None:
        return None, None
    sky_coord = wcs.pixel_to_world(x, y)
    return float(sky_coord.ra.deg), float(sky_coord.dec.deg)


def run_step1(filepaths, is_fits=True, hdu_index=0):
    """Main entry point for Step 1."""
    if is_fits:
        aligned_images, ref_wcs, timestamps = align_fits_stack(filepaths, hdu_index=hdu_index)
    else:
        aligned_images, timestamps = align_standard_stack(filepaths)
        ref_wcs = None
    return aligned_images, ref_wcs, timestamps


# =====================================================================
# STEP 2: NOISE REDUCTION & BACKGROUND SUBTRACTION
# =====================================================================

def remove_cosmic_rays(image, filter_size=3):
    """Removes single-pixel cosmic rays and hot-pixel glitches using a median filter."""
    return median_filter(image, size=filter_size)


def subtract_sky_background(image, box_size=64, mask=None):
    """Models 2D sky background glow, subtracts it, and measures global RMS noise."""
    data = np.ascontiguousarray(image, dtype=np.float64)
    bkg = sep.Background(data, mask=mask, bw=box_size, bh=box_size, fw=3, fh=3)
    clean_image = data - bkg.back()
    rms_noise = float(bkg.globalrms)
    return clean_image, rms_noise


def normalize_flux(image, reference_image):
    """Matches brightness scale of 'image' to 'reference_image' using bright star pixels."""
    ref_thresh = np.percentile(reference_image, 99)
    img_thresh = np.percentile(image, 99)

    ref_pixels = reference_image[reference_image > ref_thresh]
    img_pixels = image[image > img_thresh]
    if not ref_pixels.size or not img_pixels.size:
        return image, 1.0
    ref_bright = np.median(ref_pixels)
    img_bright = np.median(img_pixels)

    if not np.isfinite(ref_bright) or not np.isfinite(img_bright) or ref_bright <= 0 or img_bright <= 0:
        return image, 1.0

    scale_factor = ref_bright / img_bright
    return image * scale_factor, float(scale_factor)


def run_step2(aligned_images, filter_size=3, box_size=64, normalize=True, valid_mask=None):
    """Main entry point for Step 2."""
    cleaned_images = []
    noise_levels = []

    for idx, img in enumerate(aligned_images):
        denoised = remove_cosmic_rays(img, filter_size=filter_size)
        sky_sub, rms = subtract_sky_background(denoised, box_size=box_size, mask=None if valid_mask is None else ~valid_mask)

        if normalize and idx > 0:
            sky_sub, scale = normalize_flux(sky_sub, cleaned_images[0])
            rms = rms * scale

        cleaned_images.append(sky_sub)
        noise_levels.append(rms)

    return cleaned_images, noise_levels


# =====================================================================
# STEP 3: STATISTICAL ANALYSIS OF IMAGE DIFFERENCES
# =====================================================================

def compute_zscore_difference(science_img, ref_img, science_rms, ref_rms):
    """
    Subtracts reference image from science image and divides by combined noise
    to produce a statistical significance map (Z-score per pixel).
    """
    diff = science_img - ref_img
    combined_noise = np.sqrt(science_rms**2 + ref_rms**2)
    if combined_noise == 0:
        combined_noise = 1e-6
    z_map = diff / combined_noise
    return diff, z_map


def extract_candidates(z_map, frame_idx, timestamp, wcs=None, z_thresh=5.0, min_area=3):
    """
    Extracts statistically significant positive peaks (Z > z_thresh) from a difference map
    and attaches sky coordinates (RA/Dec) and local dipole measurements.
    """
    data = np.ascontiguousarray(z_map, dtype=np.float64)
    objects = sep.extract(data, thresh=z_thresh, minarea=min_area)

    candidates = []
    h, w = z_map.shape

    for obj in objects:
        x, y = float(obj["x"]), float(obj["y"])
        peak_z = float(obj["peak"])
        flux = float(obj["flux"])

        # Measure strongest negative pixel within a 5-pixel radius (to catch star dipoles later)
        x_int, y_int = int(round(x)), int(round(y))
        x_min, x_max = max(0, x_int - 5), min(w, x_int + 6)
        y_min, y_max = max(0, y_int - 5), min(h, y_int + 6)
        cutout = z_map[y_min:y_max, x_min:x_max]
        min_neg_z = float(np.min(cutout)) if cutout.size > 0 else 0.0

        ra, dec = pixel_to_radec(x, y, wcs)

        candidates.append({
            "frame": frame_idx,
            "time": timestamp,
            "x": x,
            "y": y,
            "ra": ra,
            "dec": dec,
            "peak_z": peak_z,
            "flux": flux,
            "min_neg_z": min_neg_z
        })

    return candidates


def run_step3(cleaned_images, noise_levels, timestamps, wcs=None, z_thresh=5.0, min_area=3, valid_mask=None):
    """
    Main entry point for Step 3.
    Builds a median reference stack (or uses Frame 0) and extracts moving candidates per frame.
    """
    # Using the pixel-wise median across all frames removes moving objects from the reference!
    if len(cleaned_images) >= 3:
        master_ref = np.median(np.stack(cleaned_images, axis=0), axis=0)
        ref_rms = float(1.253314 * np.median(noise_levels) / np.sqrt(len(cleaned_images)))
    else:
        master_ref = cleaned_images[0]
        ref_rms = noise_levels[0]

    all_frame_candidates = []
    z_maps = []

    for idx, (img, rms, t) in enumerate(zip(cleaned_images, noise_levels, timestamps)):
        _, z_map = compute_zscore_difference(img, master_ref, rms, ref_rms)
        if valid_mask is not None:
            z_map = np.where(valid_mask, z_map, 0.0)
        z_maps.append(z_map)
        cands = extract_candidates(z_map, frame_idx=idx, timestamp=t, wcs=wcs, z_thresh=z_thresh, min_area=min_area)
        all_frame_candidates.append(cands)

    return all_frame_candidates, z_maps


# =====================================================================
# STEP 4: MOTION SCORING METRICS (LINKING TRACKLETS)
# =====================================================================

def compute_tracklet_metrics(tracklet):
    """
    Evaluates a linked sequence of detections across >= 3 frames for:
      1. Velocity consistency (std dev of speed between frames)
      2. Trajectory linearity (RMSE from a straight line in pixels)
    """
    times = np.array([pt["time"] for pt in tracklet], dtype=np.float64)
    xs = np.array([pt["x"] for pt in tracklet], dtype=np.float64)
    ys = np.array([pt["y"] for pt in tracklet], dtype=np.float64)

    dt = np.diff(times)
    if len(times) < 3 or not np.all(np.isfinite(times)) or np.any(dt <= 0):
        raise ValueError("Tracklets require at least three strictly increasing finite times.")

    dx = np.diff(xs)
    dy = np.diff(ys)
    speeds = np.sqrt(dx**2 + dy**2) / dt

    mean_speed = float(np.mean(speeds))
    speed_std = float(np.std(speeds))
    # Relative velocity consistency: 1.0 = perfectly constant speed, 0.0 = erratic
    velocity_consistency = float(np.exp(-speed_std / (mean_speed + 1e-5)))

    # Fit straight line x(t) and y(t) and measure residual error (RMSE in pixels)
    t_norm = times - times[0]
    if np.all(t_norm == 0):
        t_norm = np.arange(len(times), dtype=np.float64)

    poly_x = np.polyfit(t_norm, xs, deg=1)
    poly_y = np.polyfit(t_norm, ys, deg=1)
    pred_x = np.polyval(poly_x, t_norm)
    pred_y = np.polyval(poly_y, t_norm)

    residuals = np.sqrt((xs - pred_x)**2 + (ys - pred_y)**2)
    linearity_rmse = float(np.sqrt(np.mean(residuals**2)))

    return {
        "mean_speed_px": mean_speed,
        "velocity_consistency": velocity_consistency,
        "linearity_rmse_px": linearity_rmse
    }


def link_tracklets(all_frame_candidates, max_step_px=50.0, min_speed_px=1.5):
    """
    Connects detections across consecutive frames into candidate trajectories (tracklets).
    Filters out stationary objects (< min_speed_px) and impossible jumps (> max_step_px).
    """
    if len(all_frame_candidates) < 3:
        return []

    tracklets = []
    # Build 3-point tracklets across consecutive frame triplets (f, f+1, f+2)
    for f in range(len(all_frame_candidates) - 2):
        cands_0 = all_frame_candidates[f]
        cands_1 = all_frame_candidates[f + 1]
        cands_2 = all_frame_candidates[f + 2]

        for p0 in cands_0:
            for p1 in cands_1:
                dist01 = np.hypot(p1["x"] - p0["x"], p1["y"] - p0["y"])
                if not (min_speed_px <= dist01 <= max_step_px):
                    continue

                # Predict where the object should be in frame f+2 assuming constant velocity
                dt01 = p1["time"] - p0["time"]
                if dt01 <= 0:
                    continue
                # Prediction must respect unequal epoch spacing (e.g. MJD days).
                for_time = cands_2[0]["time"] if cands_2 else p1["time"]
                ratio = (for_time - p1["time"]) / dt01
                if ratio <= 0:
                    continue
                pred_x2 = p1["x"] + (p1["x"] - p0["x"]) * ratio
                pred_y2 = p1["y"] + (p1["y"] - p0["y"]) * ratio

                for p2 in cands_2:
                    pred_err = np.hypot(p2["x"] - pred_x2, p2["y"] - pred_y2)
                    # Allow up to 5 pixels of deviation from linear prediction
                    dist12 = np.hypot(p2["x"] - p1["x"], p2["y"] - p1["y"])
                    if pred_err <= 5.0 and min_speed_px <= dist12 <= max_step_px:
                        track = [p0, p1, p2]
                        metrics = compute_tracklet_metrics(track)
                        if len(tracklets) >= 10000:
                            raise ValueError("Too many possible tracklets; raise the detection threshold.")
                        tracklets.append({
                            "points": track,
                            **metrics
                        })

    return tracklets


def run_step4(all_frame_candidates, max_step_px=50.0, min_speed_px=1.5):
    """Main entry point for Step 4."""
    return link_tracklets(all_frame_candidates, max_step_px=max_step_px, min_speed_px=min_speed_px)


# =====================================================================
# STEP 5: DISCOVERY CONFIDENCE MODELLING & REPORTING
# =====================================================================

def score_discovery_confidence(tracklet):
    """
    Computes an uncalibrated [0, 1] heuristic ranking score for a candidate tracklet
    rather than a misaligned star dipole or noise spike. It is not a calibrated probability.
    """
    pts = tracklet["points"]
    mean_z = float(np.mean([p["peak_z"] for p in pts]))
    worst_neg_z = float(np.min([p["min_neg_z"] for p in pts]))

    # 1. SNR Score: saturates near 1.0 once Z-score reaches ~10
    snr_score = float(1.0 - np.exp(-max(0.0, mean_z - 3.0) / 5.0))

    # 2. Motion Score: combines straightness and steady speed
    straightness_score = float(np.exp(-tracklet["linearity_rmse_px"] / 1.5))
    motion_score = 0.5 * straightness_score + 0.5 * tracklet["velocity_consistency"]

    # 3. Dipole Penalty: if a deep negative hole (Z < -4) sits right next to the positive peak,
    #    it is likely a poorly subtracted stationary star.
    dipole_ratio = abs(worst_neg_z) / (mean_z + 1e-5)
    dipole_penalty = 0.5 if (worst_neg_z < -4.0 and dipole_ratio > 0.5) else 1.0

    confidence = (0.45 * snr_score + 0.55 * motion_score) * dipole_penalty
    return round(float(np.clip(confidence, 0.0, 1.0)), 4)


def run_step5(tracklets, cleaned_images, output_csv="discoveries.csv", output_plot="top_discovery.png", time_unit="frame"):
    """
    Main entry point for Step 5.
    Scores all candidate tracklets, ranks them, exports a CSV table, and plots the #1 discovery.
    """
    if not tracklets:
        print("No valid moving tracklets found. Try lowering z_thresh or adjusting max_step_px.")
        empty = pd.DataFrame(columns=["candidate_id", "confidence", "mean_snr_z", f"speed_px_per_{time_unit}", "linearity_rmse_px"])
        empty.to_csv(output_csv, index=False)
        return empty

    rows = []
    for idx, tr in enumerate(tracklets):
        conf = score_discovery_confidence(tr)
        tr["confidence"] = conf
        p_start = tr["points"][0]
        p_end = tr["points"][-1]

        rows.append({
            "candidate_id": f"OBJ_{idx+1:03d}",
            "confidence": conf,
            "mean_snr_z": round(float(np.mean([p["peak_z"] for p in tr["points"]])), 2),
            f"speed_px_per_{time_unit}": round(tr["mean_speed_px"], 4),
            "linearity_rmse_px": round(tr["linearity_rmse_px"], 3),
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
    df.to_csv(output_csv, index=False)

    # Plot zoomed-in multi-frame cutout of the #1 highest-confidence discovery
    best_track = max(tracklets, key=lambda t: t["confidence"])
    plot_top_discovery(best_track, cleaned_images, output_path=output_plot)

    return df


def plot_top_discovery(tracklet, cleaned_images, output_path="top_discovery.png", box_radius=30):
    """
    Creates a side-by-side frame cutout showing the top candidate moving across exposures.
    Great visual slide for your hackathon pitch!
    """
    pts = tracklet["points"]
    fig, axes = plt.subplots(1, len(pts), figsize=(4 * len(pts), 4))
    if len(pts) == 1:
        axes = [axes]

    center_x = int(round(np.mean([p["x"] for p in pts])))
    center_y = int(round(np.mean([p["y"] for p in pts])))
    h, w = cleaned_images[0].shape

    x0, x1 = max(0, center_x - box_radius), min(w, center_x + box_radius)
    y0, y1 = max(0, center_y - box_radius), min(h, center_y + box_radius)

    values = np.concatenate([cleaned_images[pt["frame"]][y0:y1, x0:x1].ravel() for pt in pts])
    vmin, vmax = np.percentile(values, [5, 99])
    for ax, pt in zip(axes, pts):
        img = cleaned_images[pt["frame"]]
        cutout = img[y0:y1, x0:x1]
        ax.imshow(cutout, cmap="gray", vmin=vmin, vmax=vmax, origin="lower")
        ax.scatter(pt["x"] - x0, pt["y"] - y0, s=180, facecolors="none", edgecolors="lime", lw=2)
        ax.set_title(f"Frame {pt['frame']+1} | Z={pt['peak_z']:.1f}")
        ax.axis("off")

    plt.suptitle(f"Top Candidate (Heuristic score: {tracklet['confidence']*100:.1f}%)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(output_path, bbox_inches="tight")
    plt.close()


# =====================================================================
# MASTER PIPELINE RUNNER (CONNECTS STEPS 1 -> 2 -> 3 -> 4 -> 5)
# =====================================================================

def run_pipeline(filepaths, is_fits=True, hdu_index=0, z_thresh=5.0, max_step_px=50.0,
                 output_csv="discoveries.csv", output_plot="top_discovery.png"):
    """
    Executes the entire 5-step moving-object detection pipeline from raw images to ranked discoveries.
    """
    print("--- Step 1: Aligning images & loading coordinate maps ---")
    aligned_imgs, wcs_map, timestamps = run_step1(filepaths, is_fits=is_fits, hdu_index=hdu_index)

    timed = is_fits and all(load_fits_image(path, hdu_index)[3] is not None for path in filepaths)
    if timed:
        order = np.argsort(timestamps)
        timestamps = [timestamps[i] for i in order]
        aligned_imgs = [aligned_imgs[i] for i in order]
        if np.any(np.diff(timestamps) <= 0):
            raise ValueError("Observation times must be distinct.")
    common = binary_erosion(np.logical_and.reduce([np.isfinite(im) for im in aligned_imgs]), iterations=6)
    if not np.any(common):
        raise ValueError("No common valid sky area after alignment.")
    aligned_imgs = [np.where(common, im, np.median(im[common])) for im in aligned_imgs]

    print("--- Step 2: Removing cosmic rays, subtracting sky & normalizing flux ---")
    clean_imgs, sigmas = run_step2(aligned_imgs, valid_mask=common)

    print("--- Step 3: Computing statistical image differences (Z-scores) ---")
    frame_candidates, _ = run_step3(clean_imgs, sigmas, timestamps, wcs=wcs_map, z_thresh=z_thresh, valid_mask=common)
    total_raw = sum(len(c) for c in frame_candidates)
    print(f"    Extracted {total_raw} raw transient peaks across {len(clean_imgs)} frames.")

    print("--- Step 4: Linking detections into moving tracklets & scoring motion ---")
    tracklets = run_step4(frame_candidates, max_step_px=max_step_px)
    print(f"    Linked {len(tracklets)} candidate moving tracklets.")

    print("--- Step 5: Modelling discovery confidence & exporting results ---")
    results_df = run_step5(tracklets, clean_imgs, output_csv=output_csv,
                           output_plot=output_plot, time_unit="day" if timed else "frame")

    if not results_df.empty:
        print("\nTop Discoveries:")
        print(results_df.head(10).to_string(index=False))

    return results_df


if __name__ == "__main__":
    # Replace with your actual hackathon image files (at least 3 sequential exposures)
    input_files = [
        "image1.fits",
        "image2.fits",
        "image3.fits"
    ]

    # Set is_fits=False if your dataset uses .png, .jpg, or .tiff files
    discoveries = run_pipeline(
        filepaths=input_files,
        is_fits=True,
        hdu_index=0,
        z_thresh=5.0,
        max_step_px=50.0
    )