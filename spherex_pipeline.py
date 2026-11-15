"""
spherex_pipeline.py
====================
Full coordinate-to-image moving-object discovery tool. Chains together:

    spherex_coords.py    parse sexagesimal / decimal-degree / object-name input
    spherex_query.py      search IRSA SIA2 for overlapping SPHEREx exposures
    spherex_download.py   download MEFs, split into per-HDU FITS + manifest.csv
    spherex_detect.py      align, clean, differencing, tracklet-link, score

Usage
-----
    python spherex_pipeline.py
    python spherex_pipeline.py --target "08h55m10.831s -07d14m42.53s" --radius 2 --detector 3
    python spherex_pipeline.py --target "133.79513, -7.24515" --z-thresh 4.5 --max-exposures 20

Run with no arguments for the original interactive prompts (same as
spherex_fetch_cli.py), or pass flags for non-interactive / scripted use.

Output
------
./spherex_output/<target_label>/
    manifest.csv                       (all downloaded exposures, all detectors)
    <obs_id>_D<detector>/IMAGE.fits ...
    detector_1/discoveries.csv, top_discovery.png     (if detector 1 had >=3 exposures)
    detector_2/discoveries.csv, top_discovery.png
    ... one subfolder per detector that had enough data to link tracklets ...
    all_discoveries.csv                (combined, sorted by confidence, across detectors)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from astropy import units as u

from spherex_coords import parse_coordinate, CoordinateParseError
from spherex_query import search_spherex, DEFAULT_RADIUS, SpherexQueryError
from spherex_download import download_and_split
from spherex_detect import run_pipeline_for_target

OUTPUT_ROOT = Path("./spherex_output")


def _prompt_detectors() -> list | None:
    raw = input(
        "Restrict to specific detector(s) 1-6 (comma-separated, "
        "or press Enter for all): "
    ).strip()
    if not raw:
        return None
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        print("Could not parse detector list; defaulting to all detectors.")
        return None


def fetch_target(
    raw_target: str,
    radius_arcmin: float | None = None,
    detectors: list[int] | None = None,
    max_exposures: int | None = None,
    interactive: bool = True,
):
    """Resolve, query, and download exposures for a target. Returns the
    resolved target label (or None on failure)."""
    try:
        resolved = parse_coordinate(raw_target)
    except CoordinateParseError as exc:
        print(f"Error: {exc}")
        return None

    print(
        f"Resolved '{raw_target}' as {resolved.input_type} -> "
        f"{resolved.skycoord.to_string('hmsdms')}"
    )

    radius = radius_arcmin * u.arcmin if radius_arcmin else DEFAULT_RADIUS

    print("Querying IRSA SIA2 across spherex_dr1 / spherex_qr3 (wide + deep)...")
    try:
        result = search_spherex(resolved.skycoord, radius=radius, detectors=detectors)
    except SpherexQueryError as exc:
        print(f"Query failed: {exc}")
        return None

    print(f"Found {len(result)} exposure(s).")
    if len(result) == 0:
        print("Nothing to download.")
        return None

    if interactive and max_exposures is None and len(result) > 10:
        cap_raw = input(
            f"This will download {len(result)} files (~{len(result) * 65} MB "
            f"at ~65 MB each). Enter a max number to fetch now for testing, "
            f"or press Enter to fetch all {len(result)}: "
        ).strip()
        if cap_raw:
            try:
                max_exposures = int(cap_raw)
            except ValueError:
                print("Could not parse number; fetching all exposures.")

    print(f"Downloading and splitting into {OUTPUT_ROOT / resolved.label} ...")
    exposures = download_and_split(
        result.table, OUTPUT_ROOT, resolved.label, max_exposures=max_exposures
    )
    n_skipped = sum(e.skipped for e in exposures)
    print(
        f"Done. {len(exposures) - n_skipped} downloaded, "
        f"{n_skipped} already present and skipped."
    )
    print(f"Manifest written to {OUTPUT_ROOT / resolved.label / 'manifest.csv'}")

    return resolved.label


def detect_for_target(
    target_label: str,
    detectors: list[int] | None = None,
    z_thresh: float = 5.0,
    max_step_px: float = 50.0,
) -> pd.DataFrame:
    """
    Runs the Step 1-5 detection pipeline for a target, once per requested
    detector (or once per detector found in the manifest if none specified),
    skipping detectors with fewer than 3 exposures. Combines everything into
    a single all_discoveries.csv at the target root.
    """
    target_dir = OUTPUT_ROOT / target_label
    manifest_path = target_dir / "manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.csv found at {manifest_path}; fetch data first.")

    manifest_df = pd.read_csv(manifest_path)
    if detectors is None:
        detectors = sorted(int(d) for d in manifest_df["detector"].dropna().unique())

    combined_frames = []
    for det in detectors:
        n_exposures = int((manifest_df["detector"] == det).sum())
        if n_exposures < 3:
            print(f"[detector {det}] Only {n_exposures} exposure(s) available; skipping (need >= 3).")
            continue

        print(f"\n=== Detector {det}: running detection pipeline ({n_exposures} exposures) ===")
        try:
            df = run_pipeline_for_target(
                target_label=target_label,
                output_root=OUTPUT_ROOT,
                detector=det,
                z_thresh=z_thresh,
                max_step_px=max_step_px,
                results_dir=target_dir / f"detector_{det}",
            )
        except ValueError as exc:
            print(f"[detector {det}] Skipped: {exc}")
            continue

        if not df.empty:
            combined_frames.append(df)

    if not combined_frames:
        print("\nNo moving-object candidates found on any detector.")
        return pd.DataFrame()

    combined_df = pd.concat(combined_frames, ignore_index=True)
    combined_df = combined_df.sort_values(by="confidence", ascending=False).reset_index(drop=True)
    combined_path = target_dir / "all_discoveries.csv"
    combined_df.to_csv(combined_path, index=False)
    print(f"\nCombined results across all detectors written to {combined_path}")
    print(combined_df.head(10).to_string(index=False))

    return combined_df


def main():
    parser = argparse.ArgumentParser(
        description="Coordinate -> SPHEREx image -> moving-object discovery pipeline."
    )
    parser.add_argument("--target", help="Sexagesimal, decimal RA/Dec, or object name.")
    parser.add_argument("--radius", type=float, help="Search radius in arcmin.")
    parser.add_argument("--detector", type=str, help="Comma-separated detector(s) 1-6, or omit for all.")
    parser.add_argument("--max-exposures", type=int, default=None, help="Cap number of exposures downloaded.")
    parser.add_argument("--z-thresh", type=float, default=5.0, help="Z-score detection threshold (default 5.0).")
    parser.add_argument("--max-step-px", type=float, default=50.0, help="Max per-frame motion in pixels (default 50).")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip download; detect only on existing data for --target-label.")
    parser.add_argument("--target-label", help="Existing ./spherex_output/<label> folder name (used with --skip-fetch).")
    args = parser.parse_args()

    detectors = None
    if args.detector:
        try:
            detectors = [int(x) for x in args.detector.split(",") if x.strip()]
        except ValueError:
            print("Could not parse --detector list; using all detectors.")

    interactive = args.target is None

    if args.skip_fetch:
        if not args.target_label:
            print("Error: --skip-fetch requires --target-label.")
            sys.exit(1)
        target_label = args.target_label
    else:
        raw_target = args.target or input(
            "Enter target (sexagesimal, decimal RA/Dec, or object name): "
        ).strip()
        radius = args.radius
        if radius is None and interactive:
            radius_raw = input(
                f"Search radius in arcmin (default {DEFAULT_RADIUS.to(u.arcmin).value:g}): "
            ).strip()
            radius = float(radius_raw) if radius_raw else None
        if detectors is None and interactive:
            detectors = _prompt_detectors()

        target_label = fetch_target(
            raw_target,
            radius_arcmin=radius,
            detectors=detectors,
            max_exposures=args.max_exposures,
            interactive=interactive,
        )
        if target_label is None:
            sys.exit(1)

    print(f"\n=== Running moving-object detection for '{target_label}' ===")
    detect_for_target(
        target_label,
        detectors=detectors,
        z_thresh=args.z_thresh,
        max_step_px=args.max_step_px,
    )


if __name__ == "__main__":
    main()
