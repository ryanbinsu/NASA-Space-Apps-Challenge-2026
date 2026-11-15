"""Synthetic fixtures verify mechanics only; these are not astronomical observations."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

import imageio.v3 as iio
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

_STORE = tempfile.TemporaryDirectory()
os.environ["SPHEREX_RUNS_DIR"] = _STORE.name

from fastapi.testclient import TestClient
from backend.app import app
import moving_object_pipeline as pipeline


def star_frames():
    rng = np.random.default_rng(21)
    yy, xx = np.mgrid[:128, :128]
    background = np.full((128, 128), 100.0)
    for x, y in [(20, 25), (90, 20), (25, 90), (100, 100), (60, 30), (30, 60), (90, 60), (70, 95)]:
        background += 700 * np.exp(-((xx - x)**2 + (yy - y)**2) / 8)
    frames = []
    for index in range(3):
        frame = background + rng.normal(0, 1.5, background.shape)
        frame += 350 * np.exp(-((xx - (45 + index * 9))**2 + (yy - 70)**2) / 5)
        frames.append(frame.astype(np.float32))
    return frames


def fits_bytes(image, time, offset=0):
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [64 + offset, 64]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [120, -30]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    header = wcs.to_header()
    if time is not None:
        header["MJD-OBS"] = time
        header["TIMESYS"] = "UTC"
    data = io.BytesIO()
    fits.PrimaryHDU(image, header).writeto(data)
    return data.getvalue()


def point(time, x, y):
    return {"time": time, "x": x, "y": y, "peak_z": 8.0, "min_neg_z": -1.0, "frame": int(time)}


class MathematicsTests(unittest.TestCase):
    def test_combined_noise_formula(self):
        difference, zmap = pipeline.compute_zscore_difference(np.array([[14.0]]), np.array([[4.0]]), 3, 4)
        self.assertEqual(float(difference[0, 0]), 10)
        self.assertEqual(float(zmap[0, 0]), 2)

    def test_true_rmse(self):
        points = [point(0, 0, 0), point(1, 1, 2), point(2, 2, 0)]
        expected = np.sqrt(np.mean(np.array([2/3, -4/3, 2/3])**2))
        self.assertAlmostEqual(pipeline.compute_tracklet_metrics(points)["linearity_rmse_px"], expected)

    def test_irregular_epoch_prediction(self):
        tracklets = pipeline.link_tracklets([[point(0, 0, 0)], [point(1, 10, 0)], [point(3, 30, 0)]])
        self.assertEqual(len(tracklets), 1)
        self.assertAlmostEqual(tracklets[0]["mean_speed_px"], 10)
        self.assertAlmostEqual(tracklets[0]["velocity_consistency"], 1)

    def test_duplicate_epochs_rejected(self):
        with self.assertRaises(ValueError):
            pipeline.compute_tracklet_metrics([point(0, 0, 0), point(0, 2, 0), point(1, 4, 0)])

    def test_flat_normalization_is_finite(self):
        result, scale = pipeline.normalize_flux(np.zeros((32, 32)), np.zeros((32, 32)))
        self.assertTrue(np.isfinite(result).all())
        self.assertEqual(scale, 1)

    def test_heuristic_is_bounded_and_penalizes_dipoles(self):
        track = {"points": [point(0, 0, 0), point(1, 2, 0), point(2, 4, 0)],
                 "linearity_rmse_px": 0, "velocity_consistency": 1}
        clean_score = pipeline.score_discovery_confidence(track)
        track["points"][0]["min_neg_z"] = -8
        self.assertAlmostEqual(pipeline.score_discovery_confidence(track), clean_score / 2, places=3)
        self.assertTrue(0 <= clean_score <= 1)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.frames = star_frames()

    def upload(self, files=None, **data):
        if files is None:
            files = [("files", (f"synthetic-{i}.fits", fits_bytes(image, 61000 + i), "application/fits"))
                     for i, image in enumerate(self.frames)]
        return self.client.post("/api/analyze", files=files, data=data)

    def test_all_five_stages_and_exports(self):
        response = self.upload(source="SYNTHETIC TEST FIXTURE — not NASA observations")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(len(result["frames"]), 3)
        self.assertEqual(result["timeUnit"], "day")
        self.assertTrue(result["hasWcs"])
        self.assertGreater(result["candidateCount"], 0)
        self.assertGreater(len(result["tracklets"]), 0)
        for frame in result["frames"]:
            for path in frame["images"].values():
                artifact = self.client.get(result["baseUrl"] + path)
                self.assertEqual(artifact.status_code, 200)
                self.assertEqual(artifact.headers["content-type"], "image/png")
        for name in [result["csv"], "result.json", result["topPlot"]]:
            self.assertEqual(self.client.get(result["baseUrl"] + name).status_code, 200)
        track = result["tracklets"][0]
        self.assertTrue(0 <= track["confidence"] <= 1)
        self.assertIsNotNone(track["points"][0]["ra"])

    def test_header_order_sorted(self):
        files = [("files", (f"{i}.fits", fits_bytes(self.frames[i], 61000 + i), "application/fits")) for i in [2, 0, 1]]
        response = self.upload(files)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([f["filename"] for f in response.json()["frames"]], ["0.fits", "1.fits", "2.fits"])

    def test_partial_times_use_consistent_frame_units(self):
        files = [("files", (f"{i}.fits", fits_bytes(image, 61000 + i if i != 1 else None), "application/fits"))
                 for i, image in enumerate(self.frames)]
        response = self.upload(files)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["timeUnit"], "frame")
        self.assertEqual([f["observedAt"] for f in response.json()["frames"]], [None] * 3)
        self.assertEqual([f["time"] for f in response.json()["frames"]], [0, 1, 2])

    def test_raster_alignment(self):
        files = []
        for index, image in enumerate(self.frames):
            encoded = iio.imwrite("<bytes>", np.clip(image, 0, 255).astype(np.uint8), extension=".png")
            files.append(("files", (f"synthetic-{index}.png", encoded, "image/png")))
        response = self.upload(files, timestamps=json.dumps(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["hasWcs"])
        self.assertEqual(response.json()["timeUnit"], "day")

    def test_valid_no_detections(self):
        response = self.upload(z_thresh="50", min_area="100")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tracklets"], [])
        self.assertIsNone(response.json()["topPlot"])
        self.assertIn("candidate_id", self.client.get(response.json()["baseUrl"] + response.json()["csv"]).text)

    def test_invalid_file_and_settings_errors(self):
        files = [("files", (f"{i}.txt", b"invalid", "text/plain")) for i in range(3)]
        self.assertEqual(self.upload(files).status_code, 422)
        self.assertEqual(self.upload(filter_size="2").status_code, 422)
        self.assertEqual(self.upload(timestamps='["bad"]').status_code, 422)
        self.assertEqual(self.upload(min_step_px="51", max_step_px="50").status_code, 422)
        self.assertEqual(self.upload(files[:1]).status_code, 422)

    def test_duplicate_timestamps_and_hdu_errors(self):
        files = [("files", (f"{i}.fits", fits_bytes(image, 61000), "application/fits")) for i, image in enumerate(self.frames)]
        self.assertEqual(self.upload(files).status_code, 422)
        self.assertEqual(self.upload(hdu_index="99").status_code, 422)

    def test_fits_reprojection_handles_offset_wcs(self):
        files = [("files", (f"{i}.fits", fits_bytes(image, 61000 + i, offset=i), "application/fits"))
                 for i, image in enumerate(self.frames)]
        response = self.upload(files)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLess(response.json()["validPixelFraction"], 1)

    def test_standalone_master_runner_exports_time_units(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index, image in enumerate(self.frames):
                path = Path(folder) / f"{index}.fits"
                path.write_bytes(fits_bytes(image, 61000 + index))
                paths.append(path)
            result = pipeline.run_pipeline(paths, output_csv=Path(folder)/"out.csv",
                                           output_plot=Path(folder)/"out.png")
            self.assertFalse(result.empty)
            self.assertIn("speed_px_per_day", result.columns)

    def test_health(self):
        self.assertEqual(len(self.client.get("/api/health").json()["stages"]), 5)


if __name__ == "__main__":
    unittest.main()
