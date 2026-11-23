"""Sanity-check a green X dataset (original 4-column labels or label format v2).

Usage:
    python green_x/check_dataset.py <dataset_dir>

Checks every row and reports all problems, then exits with status 1 if any.
Pixel convention: pixel centers at integers, image spans -0.5 .. size - 0.5.
"""

import csv
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

SCENE_TYPES = {"x", "plus", "plain", "other_color", "absent"}


def number(value):
    return float(value) if value not in (None, "") else None


def check_row(root, row):
    problems = []
    path = root / "images" / row["filename"]
    if not path.exists():
        return ["image missing"]
    with Image.open(path) as im:
        w, h = im.size

    if row.get("width") and int(row["width"]) != w:
        problems.append(f"width column {row['width']} != image width {w}")
    if row.get("height") and int(row["height"]) != h:
        problems.append(f"height column {row['height']} != image height {h}")

    scene = row.get("scene_type", "x")
    present = row.get("target_present", "1")
    if scene not in SCENE_TYPES:
        problems.append(f"unknown scene_type {scene!r}")
    if present not in ("0", "1"):
        problems.append(f"target_present must be 0 or 1, got {present!r}")
    elif (present == "1") != (scene == "x"):
        problems.append(f"target_present={present} does not match scene_type={scene}")
    if row.get("occluded", "0") not in ("0", "1"):
        problems.append(f"occluded must be 0 or 1, got {row.get('occluded')!r}")

    x, y = number(row.get("x")), number(row.get("y"))
    if present == "1":
        if x is None or y is None:
            problems.append("target present but x/y blank")
        elif not (-0.5 <= x <= w - 0.5 and -0.5 <= y <= h - 0.5):
            problems.append(f"center ({x}, {y}) outside the image")
    elif x is not None or y is not None:
        problems.append("target absent but x/y filled in")

    box = [number(row.get(k)) for k in ("bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax")]
    if any(v is not None for v in box):
        if any(v is None for v in box):
            problems.append("bounding box partly blank")
        else:
            x0, y0, x1, y1 = box
            if not (-0.5 <= x0 < x1 <= w - 0.5 and -0.5 <= y0 < y1 <= h - 0.5):
                problems.append(f"bad bounding box {box}")
            elif present == "1" and x is not None and not (x0 <= x <= x1 and y0 <= y <= y1):
                problems.append("center outside its bounding box")
    elif present == "1" and "bbox_xmin" in row:
        problems.append("target present but bounding box blank")

    return problems


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "output/dataset")
    with (root / "labels.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("FAIL: no labels found")
        sys.exit(1)

    failures = 0
    for i, row in enumerate(rows):
        for problem in check_row(root, row):
            failures += 1
            print(f"row {i} ({row.get('filename')}): {problem}")

    counts = Counter(row.get("scene_type", "x") for row in rows)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    if failures:
        print(f"FAIL: {failures} problem(s) in {len(rows)} rows ({summary})")
        sys.exit(1)
    print(f"PASS: {len(rows)} labeled images ({summary}), all labels consistent")


if __name__ == "__main__":
    main()
