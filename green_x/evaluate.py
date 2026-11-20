
"""Evaluate Green X center detection against Blender ground truth.

Usage:
    python vision/evaluate.py --dataset output/dataset
"""

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

from baseline_v2 import detect


def evaluate(dataset):
    dataset = Path(dataset)
    image_dir = dataset / "images"
    label_path = dataset / "labels.csv"

    errors = []
    results = []
    total = 0
    detected = 0

    # Separate performance by occlusion.
    groups = {
        0: {"total": 0, "errors": [], "detected": 0},
        1: {"total": 0, "errors": [], "detected": 0},
    }

    with open(label_path, newline="") as f:
        labels = list(csv.DictReader(f))

    for label in labels:
        filename = label["filename"]
        gt_x = float(label["x"])
        gt_y = float(label["y"])
        occluded = int(label["occluded"])

        image = cv2.imread(str(image_dir / filename))

        if image is None:
            print(f"WARNING: Missing image {filename}")
            continue

        total += 1
        groups[occluded]["total"] += 1

        # Call your existing baseline detector.
        center, mask, corners = detect(
            image,
            verify_green=True,
            green_threshold=0.030
        )

        if center is None:
            print(f"{filename}: NOT DETECTED")

            results.append({
                "filename": filename,
                "occluded": occluded,
                "detected": 0,
                "error_px": "",
            })
            continue

        detected += 1
        groups[occluded]["detected"] += 1

        pred_x, pred_y = center

        # Euclidean distance between predicted and true center.
        error = float(np.hypot(
            pred_x - gt_x,
            pred_y - gt_y
        ))

        errors.append(error)
        groups[occluded]["errors"].append(error)

        results.append({
            "filename": filename,
            "occluded": occluded,
            "detected": 1,
            "error_px": round(error, 3),
        })

        print(
            f"{filename}: "
            f"pred=({pred_x:.1f}, {pred_y:.1f}), "
            f"true=({gt_x:.1f}, {gt_y:.1f}), "
            f"error={error:.2f}px"
        )

    # Save results for further analysis.
    output_path = dataset.parent / "evaluation_results.csv"

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "filename",
                "occluded",
                "detected",
                "error_px"
            ]
        )

        writer.writeheader()
        writer.writerows(results)

    print("\n========== OVERALL RESULTS ==========")

    if total == 0:
        print("No valid images found.")
        return

    print(f"Images evaluated: {total}")
    print(f"Targets detected: {detected}/{total}")
    print(f"Detection rate: {100 * detected / total:.1f}%")

    if errors:
        print(f"Mean error: {np.mean(errors):.2f} px")
        print(f"Median error: {np.median(errors):.2f} px")
        print(f"Maximum error: {np.max(errors):.2f} px")

        # Count predictions within a useful accuracy threshold.
        accurate = sum(e <= 5 for e in errors)

        print(
            f"Within 5 pixels: "
            f"{accurate}/{total} images "
            f"({100 * accurate / total:.1f}%)"
        )

    print("\n========== OCCLUSION ANALYSIS ==========")

    for occluded, group in groups.items():
        name = "Occluded" if occluded else "Not occluded"

        count = group["total"]
        found = group["detected"]

        if count == 0:
            continue

        rate = 100 * found / count

        print(f"\n{name}:")
        print(f"  Detection rate: {found}/{count} ({rate:.1f}%)")

        if group["errors"]:
            mean_error = np.mean(group["errors"])
            print(f"  Mean error: {mean_error:.2f} px")

    print(f"\nSaved results to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dataset",
        default="output/dataset",
        help="Path to Blender-generated dataset"
    )

    args = parser.parse_args()
    evaluate(args.dataset)
