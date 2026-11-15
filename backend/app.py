"""Loopback-only local API; Vite proxies /api for a single browser origin."""
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from backend.analysis import analyze

ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(os.environ.get("SPHEREX_RUNS_DIR", ROOT / ".runtime" / "runs"))
RUNS.mkdir(parents=True, exist_ok=True)
LOCK = Lock()
MAX_FILE = 20 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
EXTENSIONS = {".fits", ".fit", ".fts", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
app = FastAPI(title="SPHEREx Motion Explorer local processing", version="1.0")
app.mount("/api/runs", StaticFiles(directory=RUNS), name="runs")


@app.get("/api/health")
def health():
    return {"status": "ok", "maxFrames": 8, "maxPixels": 1048576,
            "stages": ["alignment", "background/normalization", "differences/significance",
                       "tracklet metrics", "heuristic ranking/CSV/plot"]}


@app.post("/api/analyze")
def analyze_uploads(
    files: list[UploadFile] = File(...),
    hdu_index: int = Form(0, ge=0, le=100),
    filter_size: int = Form(3, ge=1, le=9),
    box_size: int = Form(64, ge=8, le=256),
    normalize: bool = Form(True),
    z_thresh: float = Form(5.0, ge=1, le=50),
    min_area: int = Form(3, ge=1, le=100),
    max_step_px: float = Form(50.0, ge=0.1, le=500),
    min_step_px: float = Form(1.5, ge=0, le=100),
    timestamps: str = Form("[]"),
    source: str = Form("", max_length=300),
):
    if not 3 <= len(files) <= 8:
        raise HTTPException(422, "Upload between 3 and 8 exposures.")
    if filter_size % 2 == 0 or min_step_px > max_step_px:
        raise HTTPException(422, "Median size must be odd; minimum step cannot exceed maximum step.")
    try:
        supplied = json.loads(timestamps)
        if not isinstance(supplied, list) or not all(isinstance(t, str) for t in supplied):
            raise ValueError()
        supplied = [t.strip().removesuffix("Z") for t in supplied]
    except (ValueError, TypeError):
        raise HTTPException(422, "timestamps must be a JSON array of UTC ISO strings.") from None
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, "Another analysis is running. Wait for it to finish.")
    output = RUNS / uuid4().hex
    output.mkdir()
    try:
        with TemporaryDirectory(prefix="spherex-input-") as temp:
            paths, names, total = [], [], 0
            for index, upload in enumerate(files):
                name = Path(upload.filename or "").name
                suffix = Path(name).suffix.lower()
                if suffix not in EXTENSIONS:
                    raise ValueError("Supported inputs: FITS, PNG, JPEG and TIFF.")
                path = Path(temp) / f"{index}{suffix}"
                size = 0
                with path.open("wb") as dest:
                    while chunk := upload.file.read(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_FILE or total > MAX_TOTAL:
                            raise ValueError("Uploads are limited to 20 MiB each and 100 MiB total.")
                        dest.write(chunk)
                paths.append(path)
                names.append(name)
            result = analyze(paths, names, output, {
                "hdu_index": hdu_index, "filter_size": filter_size, "box_size": box_size,
                "normalize": normalize, "z_thresh": z_thresh, "min_area": min_area,
                "max_step_px": max_step_px, "min_step_px": min_step_px,
            }, supplied, source)
            result["id"] = output.name
            result["baseUrl"] = f"/api/runs/{output.name}/"
            (output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False))
            return result
    except (ValueError, OSError, IndexError, TypeError) as exc:
        raise HTTPException(422, f"Analysis failed: {exc}") from exc
    except Exception as exc:
        logging.exception("Processing failed")
        raise HTTPException(422, "Processing could not complete. Check image alignment/star content and server logs.") from exc
    finally:
        for upload in files:
            upload.file.close()
        LOCK.release()


if (ROOT / "dist").is_dir():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="frontend")
