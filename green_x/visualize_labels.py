"""Draw dataset labels on images so they can be checked by eye.

Usage:
    python green_x/visualize_labels.py --dataset ../data/blender_v2_smoke/dataset \
        --out ../data/results/label_check --limit 20

For each image it writes <name>_labels.jpg (bounding box in blue, center in red,
scene type in the corner). For target-present images it also writes
<name>_zoom.png: an 8x enlargement around the labeled center, with the marker
drawn at the exact sub-pixel position, to check label accuracy.
Works with both the original 4-column labels and label format v2.
"""

import argparse
import csv
from pathlib import Path

import cv2

ZOOM = 8
HALF = 24  # crop half-size in original pixels


def number(value):
    return float(value) if value not in (None, '') else None


def zoom_crop(image, x, y):
    h, w = image.shape[:2]
    x0 = max(0, int(round(x)) - HALF)
    y0 = max(0, int(round(y)) - HALF)
    x1 = min(w, x0 + 2 * HALF)
    y1 = min(h, y0 + 2 * HALF)
    crop = cv2.resize(image[y0:y1, x0:x1], None, fx=ZOOM, fy=ZOOM,
                      interpolation=cv2.INTER_NEAREST)
    # Pixel-center convention: pixel (i) covers i-0.5 .. i+0.5.
    zx = (x - x0 + 0.5) * ZOOM - 0.5
    zy = (y - y0 + 0.5) * ZOOM - 0.5
    cv2.drawMarker(crop, (round(zx), round(zy)), (0, 0, 255),
                   cv2.MARKER_CROSS, 4 * ZOOM, 1)
    return crop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    root = Path(args.dataset)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with (root / "labels.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))

    for row in rows[:args.limit]:
        name = row["filename"]
        image = cv2.imread(str(root / "images" / name))
        if image is None:
            print(f"{name}: IMAGE MISSING")
            continue

        present = row.get("target_present", "1") == "1"
        x, y = number(row.get("x")), number(row.get("y"))
        box = [number(row.get(k)) for k in
               ("bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax")]

        labeled = image.copy()
        thickness = max(2, image.shape[1] // 800)
        if all(v is not None for v in box):
            cv2.rectangle(labeled, (round(box[0]), round(box[1])),
                          (round(box[2]), round(box[3])), (255, 0, 0), thickness)
        if present and x is not None:
            cv2.drawMarker(labeled, (round(x), round(y)), (0, 0, 255),
                           cv2.MARKER_CROSS, 12 * thickness, thickness)
            cv2.imwrite(str(out / f"{Path(name).stem}_zoom.png"),
                        zoom_crop(image, x, y))

        text = (f"{row.get('scene_type', 'x')}  present={int(present)}  "
                f"occluded={row.get('occluded', '')}  "
                f"truncated={row.get('truncated', '')}")
        scale = max(0.5, image.shape[1] / 1600)
        for color, width in (((0, 0, 0), 3 * thickness), ((255, 255, 255), thickness)):
            cv2.putText(labeled, text, (10, round(35 * scale)),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, color, width)
        cv2.imwrite(str(out / f"{Path(name).stem}_labels.jpg"), labeled)
        print(f"{name}: {row.get('scene_type', 'x')} present={int(present)}")

    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
