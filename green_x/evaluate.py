"""Evaluate the classical green X detector on a labeled dataset.

Usage:
    python green_x/evaluate.py --dataset <dataset_dir> [--out results.csv]
    python green_x/evaluate.py --dataset <dataset_dir> --no-green   # geometry only

Works with the original 4-column labels and with label format v2.

Each image gets one outcome:
  target present: hit (center within tolerance), wrong_location, or miss
  target absent:  correct_reject or false_positive

Tolerance: --tolerance-px if given; otherwise 10% of the board size from the
bounding box (sqrt of box area), or 10 px when there is no bounding box.
Center error statistics use hits only. Time is detect() only, not image loading.
"""

import argparse
import csv
import math
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from baseline_v2 import detect, DEFAULT_GREEN_THRESHOLD

FALLBACK_TOLERANCE_PX = 10.0
TOLERANCE_FRACTION = 0.10


def number(value):
    return float(value) if value not in (None, "") else None


def tolerance_for(row, fixed):
    if fixed is not None:
        return fixed
    box = [number(row.get(k)) for k in ("bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax")]
    if all(v is not None for v in box):
        size = math.sqrt(max(box[2] - box[0], 0) * max(box[3] - box[1], 0))
        if size > 0:
            return TOLERANCE_FRACTION * size
    return FALLBACK_TOLERANCE_PX


def altitude_bin(row, edges):
    altitude = number(row.get("altitude_m"))
    if altitude is None:
        return "unknown"
    for lo, hi in zip(edges, edges[1:]):
        if lo <= altitude < hi:
            return f"{lo:g}-{hi:g} m"
    return f"<{edges[0]:g} m" if altitude < edges[0] else f">={edges[-1]:g} m"


def evaluate_image(image, row, verify_green, green_threshold, fixed_tolerance):
    start = time.perf_counter()
    center, _, _ = detect(image, verify_green=verify_green,
                          green_threshold=green_threshold)
    elapsed_ms = 1000 * (time.perf_counter() - start)

    present = row.get("target_present", "1") == "1"
    result = {
        "filename": row["filename"],
        "scene_type": row.get("scene_type", "x"),
        "target_present": int(present),
        "occluded": int(row.get("occluded") or 0),
        "altitude_m": row.get("altitude_m", ""),
        "detected": int(center is not None),
        "pred_x": "", "pred_y": "", "error_px": "", "tolerance_px": "",
        "time_ms": round(elapsed_ms, 2),
    }
    if center is not None:
        result["pred_x"], result["pred_y"] = round(center[0], 3), round(center[1], 3)

    if not present:
        result["outcome"] = "false_positive" if center is not None else "correct_reject"
        return result

    tolerance = tolerance_for(row, fixed_tolerance)
    result["tolerance_px"] = round(tolerance, 2)
    if center is None:
        result["outcome"] = "miss"
        return result
    error = math.hypot(center[0] - float(row["x"]), center[1] - float(row["y"]))
    result["error_px"] = round(error, 3)
    result["outcome"] = "hit" if error <= tolerance else "wrong_location"
    return result


def describe_positives(results, indent="  "):
    n = len(results)
    hits = [r for r in results if r["outcome"] == "hit"]
    wrong = sum(r["outcome"] == "wrong_location" for r in results)
    misses = sum(r["outcome"] == "miss" for r in results)
    print(f"{indent}Hits: {len(hits)}/{n} ({100 * len(hits) / n:.1f}%)  "
          f"wrong location: {wrong}  misses: {misses}")
    if hits:
        errors = np.array([r["error_px"] for r in hits])
        print(f"{indent}Center error (hits): mean {errors.mean():.2f} px, "
              f"median {np.median(errors):.2f} px, "
              f"90th pct {np.percentile(errors, 90):.2f} px, max {errors.max():.2f} px")


def summarize(results, edges):
    positives = [r for r in results if r["target_present"]]
    negatives = [r for r in results if not r["target_present"]]

    print("\n========== TARGET PRESENT ==========")
    if positives:
        print(f"Images: {len(positives)}")
        describe_positives(positives)
        for occluded, name in ((0, "Not occluded"), (1, "Occluded")):
            group = [r for r in positives if r["occluded"] == occluded]
            if group:
                print(f"\n{name} ({len(group)}):")
                describe_positives(group, "    ")
        by_altitude = defaultdict(list)
        for r in positives:
            by_altitude[altitude_bin(r, edges)].append(r)
        if set(by_altitude) != {"unknown"}:
            print("\nBy altitude:")
            order = ([f"<{edges[0]:g} m"] +
                     [f"{lo:g}-{hi:g} m" for lo, hi in zip(edges, edges[1:])] +
                     [f">={edges[-1]:g} m", "unknown"])
            for name in [b for b in order if b in by_altitude]:
                print(f"  {name} ({len(by_altitude[name])}):")
                describe_positives(by_altitude[name], "    ")
    else:
        print("No target-present images.")

    print("\n========== TARGET ABSENT ==========")
    if negatives:
        fp = sum(r["outcome"] == "false_positive" for r in negatives)
        print(f"False positives: {fp}/{len(negatives)} ({100 * fp / len(negatives):.1f}%)")
        by_scene = defaultdict(list)
        for r in negatives:
            by_scene[r["scene_type"]].append(r)
        for scene in sorted(by_scene):
            group = by_scene[scene]
            n_fp = sum(r["outcome"] == "false_positive" for r in group)
            print(f"  {scene:<12} {n_fp}/{len(group)} ({100 * n_fp / len(group):.1f}%)")
    else:
        print("No target-absent images, so false positives were not measured.")

    times = np.array([r["time_ms"] for r in results])
    print("\n========== TIME PER IMAGE (detect only) ==========")
    print(f"Mean {times.mean():.1f} ms, median {np.median(times):.1f} ms, "
          f"90th pct {np.percentile(times, 90):.1f} ms")


def evaluate(dataset, output_path=None, verify_green=True,
             green_threshold=DEFAULT_GREEN_THRESHOLD, tolerance_px=None,
             altitude_edges=(8, 15, 25, 40)):
    dataset = Path(dataset)
    with (dataset / "labels.csv").open(newline="") as f:
        labels = list(csv.DictReader(f))

    results = []
    for row in labels:
        image = cv2.imread(str(dataset / "images" / row["filename"]))
        if image is None:
            print(f"WARNING: Missing image {row['filename']}")
            continue
        result = evaluate_image(image, row, verify_green, green_threshold, tolerance_px)
        results.append(result)
        if result["outcome"] not in ("hit", "correct_reject"):
            detail = f" error={result['error_px']}px" if result["error_px"] != "" else ""
            print(f"{result['filename']}: {result['scene_type']} "
                  f"{result['outcome'].upper()}{detail}")

    if not results:
        print("No valid images found.")
        return []

    if output_path is None:
        output_path = dataset.parent / "evaluation_results.csv"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print(f"\nGreen verification: {'on, threshold %.3f' % green_threshold if verify_green else 'off'}")
    print("Tolerance: " + (f"{tolerance_px} px (fixed)" if tolerance_px is not None else
          f"{TOLERANCE_FRACTION:.0%} of board size, or {FALLBACK_TOLERANCE_PX:g} px without a box"))
    summarize(results, list(altitude_edges))
    print(f"\nSaved results to: {output_path}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="output/dataset",
                        help="Folder with images/ and labels.csv")
    parser.add_argument("--out", default=None,
                        help="CSV path for per-image results (default: next to the dataset folder)")
    parser.add_argument("--no-green", action="store_true",
                        help="Skip green X verification (white-square geometry only)")
    parser.add_argument("--green-threshold", type=float, default=DEFAULT_GREEN_THRESHOLD)
    parser.add_argument("--tolerance-px", type=float, default=None,
                        help="Fixed hit tolerance in pixels (default: 10%% of board size)")
    parser.add_argument("--altitude-bins", default="8,15,25,40",
                        help="Comma-separated altitude bin edges in meters")
    args = parser.parse_args()
    evaluate(args.dataset, args.out, verify_green=not args.no_green,
             green_threshold=args.green_threshold, tolerance_px=args.tolerance_px,
             altitude_edges=[float(v) for v in args.altitude_bins.split(",")])
