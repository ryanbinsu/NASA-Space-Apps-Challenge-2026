# SPHEREx Stellar Motion Tracker — User Guide

A tool to search NASA's SPHEREx mission archive for a given star, download real
infrared sky images across multiple time epochs, clean them, and detect
candidate moving objects.

---

## 1. Setup (one-time)

```bash
# Clone the repo
git clone https://github.com/ryanbinsu/NASA-Space-Apps-Challenge-2026.git
cd NASA-Space-Apps-Challenge-2026/spherex_tool

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Running the full pipeline

From inside `spherex_tool/`, with your virtual environment active:

```bash
python3 spherex_pipeline.py
```

You will be asked for:

| Prompt | What to enter |
|---|---|
| **Target** | A star name (`Barnard's Star`), sexagesimal coordinates (`08h55m10.831s -07d14m42.53s`), or decimal RA/Dec (`133.79, -7.25`) |
| **Search radius** | Field of view in arcminutes (press Enter for default ≈ 1 arcmin) |
| **Detector(s)** | Press Enter to search all 6 SPHEREx detectors, or type specific numbers (e.g. `3,6`) |
| **Max exposures** | If many exposures are found, type a number to limit download size/time (e.g. `10`), or press Enter to fetch all |

The tool will then automatically:
1. Resolve your target to sky coordinates
2. Search NASA's IRSA SPHEREx archive (DR1 + QR3 releases)
3. Download matching exposures and split each into 6 FITS files (image, flags, variance, zodiacal background, PSF, wavelength map)
4. Align, clean, and compare images across time
5. Report candidate moving objects, ranked by confidence

**Note:** a single search can return hundreds of exposures (~65 MB each). Use the max-exposure prompt to keep test runs quick.

---

## 3. Generating viewable images

Raw SPHEREx data is FITS format (not viewable directly in a browser/image viewer).
To turn downloaded data into PNG images:

```bash
python3 make_all_images.py
```

This scans `spherex_output/<target>/` for all downloaded exposures and produces
a single grid image (`*_grid.png`) showing every exposure side by side —
useful for visually comparing how the sky changed over time.

To view the tool's own top motion candidate (produced automatically by step 5
of the pipeline above):

```bash
open spherex_output/<target_label>/detector_<N>/top_discovery.png
```

replacing `<target_label>` with your target's output folder name (shown in the
terminal after the run, e.g. `Barnard_s_Star`) and `<N>` with the detector
number that produced results.

---

## 4. Re-running detection without re-downloading

If you already have data for a target and just want to re-run detection
(e.g. after a code change), skip the fetch step entirely:

```bash
python3 spherex_pipeline.py --skip-fetch --target-label "Barnard_s_Star"
```

---

## 5. Output structure

```
spherex_output/<target_label>/
├── manifest.csv                     # one row per exposure: time, coords, file paths
├── <obs_id>_D<detector>/
│   ├── IMAGE.fits                   # calibrated science image
│   ├── FLAGS.fits                   # per-pixel quality bitmask
│   ├── VARIANCE.fits                # per-pixel noise
│   ├── ZODI.fits                    # modeled background
│   ├── EPSF.fits                    # point-spread function
│   └── WCS-WAVE.fits                # per-pixel wavelength solution
├── detector_<N>/
│   ├── discoveries.csv              # ranked candidate moving objects
│   └── top_discovery.png            # visual of the highest-confidence candidate
└── all_discoveries.csv              # combined results across all detectors
```

**Always open FITS files with `astropy`, never a text editor** — they are
binary files and will appear as garbled text otherwise:

```python
from astropy.io import fits
data = fits.open("IMAGE.fits")[1].data
```

---

## 6. Tested targets

This tool has been verified end-to-end on all targets named in the 2026 NASA
Space Apps SPHEREx challenge brief:

- Barnard's Star
- Epsilon Indi B
- WISE 0855 (use exact form `WISE J085510.83-071442.5`, or sexagesimal
  `08h55m10.831s -07d14m42.53s`)
- RW Aurigae
- R Draconis

---

## 7. Known limitations

- NASA's IRSA archive query service (SIA2) can experience intermittent
  outages; the tool retries automatically but may still fail during a true
  service outage — simply wait and retry.
- Detection confidence scoring is a first-pass model and is still being
  calibrated; treat `discoveries.csv` results as candidate leads, not
  confirmed detections.
