
"""White-square localization with optional green X verification.

Usage:
 python vision/baseline_v2.py image.png
 python vision/baseline_v2.py image.png --verify-green
"""

import argparse
from pathlib import Path

import cv2
import numpy as np


def order_corners(corners):
    """Return corners in cyclic order around the center."""
    centroid = corners.mean(axis=0)
    angles = np.arctan2(
        corners[:, 1] - centroid[1],
        corners[:, 0] - centroid[0]
    )
    return corners[np.argsort(angles)]


def diagonal_intersection(corners):
    p, q, r, s = order_corners(corners)
    A = np.column_stack((r - p, -(s - q)))

    if abs(np.linalg.det(A)) < 1e-6:
        return None

    t = np.linalg.solve(A, q - p)[0]
    return p + t * (r - p)


def verify_green_x(image, corners, threshold=0.030):
    """Verify green evidence along both target diagonals.

    Returns (accepted, score, warped_image, evidence_mask).
    Score is a heuristic, not a calibrated probability.
    """
    size = 128
    src = order_corners(corners).astype(np.float32)
    dst = np.array([
        [0, 0],
        [size - 1, 0],
        [size - 1, size - 1],
        [0, size - 1]
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(image, M, (size, size))

    # Use LAB: low a-channel indicates green relative to magenta.
    lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)
    a = lab[:, :, 1].astype(np.float32)

    # Green dominance in BGR; tolerate relatively faint strokes.
    b, g, r = cv2.split(warped.astype(np.float32))
    dominance = g - 0.5 * (r + b)

    # More sensitive to pale/desaturated green.
    lab_green = np.clip((128.0 - a) / 10.0, 0, 1)

    # Retain RGB green dominance as supporting evidence.
    rgb_green = np.clip(dominance / 15.0, 0, 1)

    evidence = 0.7 * lab_green + 0.3 * rgb_green

    # Slight blur helps with anti-aliased, thin green strokes.
    evidence = cv2.GaussianBlur(evidence, (3, 3), 0)

    yy, xx = np.indices((size, size))
    d1 = np.abs(xx - yy)
    d2 = np.abs(xx + yy - (size - 1))

    # Ignore the outermost border and central crossing.
    interior = (
        (xx > 10) & (xx < size - 11) &
        (yy > 10) & (yy < size - 11)
    )
    away_center = (
        (np.abs(xx - 63.5) > 10) |
        (np.abs(yy - 63.5) > 10)
    )
    valid = interior & away_center

    # Wide enough to tolerate minor corner-fitting errors.
    band1 = (d1 <= 9) & valid
    band2 = (d2 <= 9) & valid
    background = (d1 >= 17) & (d2 >= 17) & interior

    def band_score(band):
        # Compare green evidence against the off-diagonal area.
        return max(
            0.0,
            float(evidence[band].mean()) -
            float(evidence[background].mean())
        )

    # Calculate each diagonal's green evidence.
    score1 = band_score(band1)
    score2 = band_score(band2)

    strong = max(score1, score2)
    weak = min(score1, score2)

    # Reward strong evidence while requiring both diagonals.
    score = 0.6 * strong + 0.4 * weak

    accepted = (
        score >= threshold
        and weak >= 0.005
    )

    # Diagnostic output
    print(
    f"Diagonal 1: {score1:.4f} | "
    f"Diagonal 2: {score2:.4f} | "
    f"Weak: {weak:.4f} | "
    f"Combined: {score:.4f} | "
    f"Accepted: {accepted}"
    )
    debug_mask = np.clip(evidence * 255, 0, 255).astype(
        np.uint8
    )

    return accepted, score, warped, debug_mask


def detect(image, verify_green=False, green_threshold=0.030):
    H, W = image.shape[:2]
    image_area = H * W

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    brightness = lab[:, :, 0]

    smooth = cv2.GaussianBlur(brightness, (3, 3), 0)

    background = cv2.GaussianBlur(
        smooth, (0, 0), sigmaX=18, sigmaY=18
    )

    contrast = cv2.subtract(smooth, background)

    _, contrast_mask = cv2.threshold(
        contrast, 12, 255, cv2.THRESH_BINARY
    )

    _, bright_mask = cv2.threshold(
        smooth, 155, 255, cv2.THRESH_BINARY
    )

    mask = cv2.bitwise_and(contrast_mask, bright_mask)

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((5, 5), np.uint8)
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        np.ones((2, 2), np.uint8)
    )

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    candidates = []

    for cnt in contours:
        area = cv2.contourArea(cnt)

        if area < 0.0004 * image_area:
            continue

        if area > 0.35 * image_area:
            continue

        perimeter = cv2.arcLength(cnt, True)

        if perimeter == 0:
            continue

        polygon = cv2.approxPolyDP(
            cnt, 0.04 * perimeter, True
        )

        if len(polygon) != 4:
            continue

        if not cv2.isContourConvex(polygon):
            continue

        corners = polygon[:, 0, :].astype(np.float32)

        rect = cv2.minAreaRect(cnt)
        width, height = rect[1]

        if min(width, height) < 1:
            continue

        aspect_ratio = max(width, height) / min(width, height)

        if aspect_ratio > 1.8:
            continue

        rectangularity = area / (width * height)

        if rectangularity < 0.60:
            continue

        center = diagonal_intersection(corners)

        if center is None:
            continue

        candidate_mask = np.zeros((H, W), dtype=np.uint8)

        cv2.fillConvexPoly(
            candidate_mask,
            corners.astype(np.int32),
            255
        )

        mean_brightness = cv2.mean(
            brightness, mask=candidate_mask
        )[0]

        mean_contrast = cv2.mean(
            contrast, mask=candidate_mask
        )[0]

        shape_score = 1.0 / aspect_ratio
        brightness_score = mean_brightness / 255.0
        contrast_score = min(mean_contrast / 40.0, 1.0)

        geometry_score = (
            0.40 * shape_score
            + 0.30 * brightness_score
            + 0.30 * contrast_score
        )

        green_score = 0.0

        if verify_green:
            accepted, green_score, _, _ = verify_green_x(
                image, corners, green_threshold
            )

            if not accepted:
                continue

        # Green evidence breaks ties between verified candidates.
        score = geometry_score + (
            0.5 * green_score if verify_green else 0
        )

        candidates.append((score, center, corners))

    if not candidates:
        return None, mask, None

    _, center, corners = max(
        candidates, key=lambda item: item[0]
    )

    return tuple(float(v) for v in center), mask, corners


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument(
        "--out",
        default="output/baseline_v2_result.png"
    )
    parser.add_argument(
        "--verify-green",
        action="store_true"
    )
    parser.add_argument(
        "--green-threshold",
        type=float,
        default=0.035
    )

    args = parser.parse_args()

    img = cv2.imread(args.image)

    if img is None:
        raise FileNotFoundError(args.image)

    center, mask, corners = detect(
        img,
        verify_green=args.verify_green,
        green_threshold=args.green_threshold
    )

    if center is not None:
        cv2.polylines(
            img,
            [corners.astype(np.int32)],
            True,
            (255, 0, 0),
            2
        )

        cv2.drawMarker(
            img,
            tuple(round(v) for v in center),
            (0, 0, 255),
            cv2.MARKER_CROSS,
            17,
            2
        )

        print(
            "Target center (x,y): (%.1f, %.1f)" % center
        )

        if args.verify_green:
            _, score, warped, evidence = verify_green_x(
                img, corners, args.green_threshold
            )

            print(f"Green X score: {score:.4f}")

            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)

            cv2.imwrite(
                str(out.with_name(out.stem + "_warped.png")),
                warped
            )

            cv2.imwrite(
                str(out.with_name(out.stem + "_green.png")),
                evidence
            )
    else:
        print("No verified target found." if args.verify_green
              else "No valid white quadrilateral found.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    cv2.imwrite(str(out), img)
    cv2.imwrite(
        str(out.with_name(out.stem + "_mask.png")),
        mask
    )

    print("Saved:", out)


if __name__ == "__main__":
    main()
