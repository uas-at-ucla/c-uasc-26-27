# Green X target localization (issue #3)

Find the package-recovery target (white square, green X) and estimate the
X intersection in **original image pixel coordinates**. First milestone:
offline Python, pixel coordinates only; no ROS interface yet.

## Setup

Run from the repo root. The virtual environment and datasets live
**outside** the repo and are not committed.

```bash
python3 -m venv ../.venv
source ../.venv/bin/activate
python -m pip install -r green_x/requirements.txt
```

## Dataset format

Each dataset is a folder with `images/` and `labels.csv`.
Pixel convention: pixel centers are at integers; the top-left pixel center is
`(0, 0)` and an image spans `-0.5 .. width - 0.5`.

**Label format v2** (written by `blender/generate_green_x.py`), one row per image:

| Column | Meaning |
|---|---|
| `filename`, `source`, `session_id` | Image file, data source, render batch or flight |
| `scene_type` | `x` (target), or negatives `plus`, `plain`, `other_color`, `absent` |
| `width`, `height` | Image size |
| `target_present` | 1 only for `x` |
| `x`, `y` | X intersection; blank for negatives |
| `occluded` | 1 if the package sits on the board center |
| `truncated` | 1 if part of the board is outside the image |
| `bbox_xmin` … `bbox_ymax` | Full extent of the white board (any board scene) |
| remaining columns | Render metadata: altitude, tilt, ground, sun, bucket, clutter, seed |

The original 4-column format (`filename,x,y,occluded`) is still accepted and
treated as all targets present.

Check a dataset, and draw its labels for a visual check:

```bash
python green_x/check_dataset.py <dataset_dir>
python green_x/visualize_labels.py --dataset <dataset_dir> --out <folder>
```

## Synthetic data

Rendered with Blender (tested with 5.2.3), from the repo root:

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b \
    --python green_x/blender/generate_green_x.py -- \
    --samples 1000 --seed 1001 --session-id blender_test_v2_seed1001 \
    --out ../data/blender_v2_test1000
```

Defaults model the SIYI ZR10 at 1x zoom: 2560×1440, 71.5° horizontal field of
view, altitude 8–40 m, camera tilt up to 30°, JPEG output. Target size (5 m
diagonal), stroke width (6 cm) and bucket size (~19 cm wide, ~16.5 cm tall)
are assumptions, not official dimensions. Each run writes `generation.json`
with its exact settings.

**Seed 1001 is the frozen test set.** Use other seeds for any training data.

## Classical baseline

`baseline_v2.py` finds a bright white quadrilateral, uses its diagonal
intersection as the center, and optionally verifies the green X in a
perspective-warped crop. Green threshold: `DEFAULT_GREEN_THRESHOLD = 0.030` in
`baseline_v2.py`, used by the command line and `evaluate.py`.

```bash
python green_x/evaluate.py --dataset <dataset_dir> --out <results.csv>
python green_x/evaluate.py --dataset <dataset_dir> --out <results.csv> --no-green
```

Outcomes: a target-present image is a **hit** (center within 10% of the board
size), **wrong location**, or **miss**; a negative is a **correct reject** or
**false positive**. Center error is reported over hits only. `--no-green`
skips green verification.

## Results on `blender_test_200` (original 256×256 set)

Center error is measured only on detected frames.

### Historical (earlier project, environment not recorded)

| Subset     | Detected | Mean error |
|------------|----------|------------|
| Unoccluded | 141/143  | 1.57 px    |
| Occluded   | 55/57    | 1.41 px    |

### Reproduced 2026-11-19

- Code: unchanged copies of the original scripts.
- Environment: macOS, Python 3.13.15, NumPy 2.5.5, OpenCV 5.1.0, Pillow 13.0.0.
- Command (from the folder above the repo):
  `python c-uasc-26-27/green_x/evaluate.py --dataset data/blender_test_200`

| Subset     | Detected | Mean error | Median  | Max     |
|------------|----------|------------|---------|---------|
| All        | 196/200  | 1.53 px    | 1.49 px | 3.08 px |
| Unoccluded | 141/143  | 1.57 px    |         |         |
| Occluded   | 55/57    | 1.41 px    |         |         |

- Misses: `frame_00069`, `frame_00077`, `frame_00141`, `frame_00190`.
- Total wall time: 1.76 s for 200 images, including Python startup.
  This is not a per-frame latency benchmark.
- The v2 `evaluate.py` gives identical numbers on this set.
- Caveat: the old generator's labels can be offset by up to 0.5 px
  (fixed in the v2 generator).

## Results on `blender_test_v2_seed1001` (2026-11-22)

- 1000 frames from generator commit `029fc43`, seed 1001: 492 targets and
  508 negatives (126 `plus`, 114 `plain`, 144 `other_color`, 124 `absent`).
  151 targets have the package on the center.
- Time is `detect()` only, on a MacBook Air (CPU).

| Metric | Green verification on | Off (geometry only) |
|---|---|---|
| Hits, all targets | 273/492 (55.5%) | 266/492 (54.1%) |
| Wrong location | 0 | 12 |
| Hits at 8–15 m | 0/126 (0%) | 0/126 (0%) |
| Hits at 15–25 m | 70/148 (47.3%) | 68/148 (45.9%) |
| Hits at 25–40 m | 203/218 (93.1%) | 198/218 (90.8%) |
| Hits, occluded | 83/151 (55.0%) | 80/151 (53.0%) |
| Center error mean / median / max | 2.25 / 1.70 / 5.47 px | 2.23 / 1.70 / 5.47 px |
| False positives, all negatives | 25/508 (4.9%) | 263/508 (51.8%) |
| … `plus` | 0/126 | 61/126 (48.4%) |
| … `plain` | 0/114 | 104/114 (91.2%) |
| … `other_color` | 25/144 (17.4%) | 72/144 (50.0%) |
| … `absent` (clutter only) | 0/124 | 26/124 (21.0%) |
| Mean time per frame | 24.5 ms | 24.3 ms |

Findings (original detector):

- Misses dominated and depended on altitude: no targets were found below 15 m.
- Green verification removed all `plus`, `plain` and clutter false positives,
  but 17% of non-green X boards still passed.
- The package on the center did not reduce recall.

### Detector updates (2026-11-27), same test set, green verification on

1. **Multiscale search:** if nothing is found at full resolution, `detect()`
   retries on ½, ¼ and ⅛ size copies (never narrower than 256 px) and maps the
   corners back to original pixels. Cause, confirmed on drawn targets: on large
   boards, the thick strokes split the white outline, and the σ = 18 px
   background blur is too small. `evaluate.py --single-scale` reproduces the
   original detector exactly.
2. **Stricter green dominance:** `g − max(r, b)` instead of `g − ½(r + b)`, so
   orange strokes no longer count as green.

| Metric | Original | + Multiscale | + Green dominance fix |
|---|---|---|---|
| Hits, all targets | 273/492 (55.5%) | 460/492 (93.5%) | 460/492 (93.5%) |
| Hits at 8–15 m | 0/126 | 103/126 (81.7%) | 103/126 (81.7%) |
| Hits at 15–25 m | 70/148 (47.3%) | 144/148 (97.3%) | 144/148 (97.3%) |
| Hits at 25–40 m | 203/218 (93.1%) | 213/218 (97.7%) | 213/218 (97.7%) |
| Center error mean / median / 90th pct | 2.25 / 1.70 / 4.07 px | 3.89 / 2.83 / 7.59 px | 3.89 / 2.83 / 7.59 px |
| Center error at 8–15 m (mean) | n/a | 7.56 px | 7.56 px |
| False positives, all negatives | 25/508 (4.9%) | 34/508 (6.7%) | 13/508 (2.6%) |
| … `other_color` | 25/144 | 34/144 | 13/144 (orange 7, red 3, blue 3) |
| … `plus`, `plain`, `absent` | 0 | 0 | 0 |
| Mean time per frame | 24.5 ms | 41.2 ms | 40.5 ms |

- `blender_test_200` (256×256): multiscale leaves it unchanged; the green
  dominance fix loses one occluded target (55/57 → 54/57), likely because the
  sub-pixel green strokes at that resolution score lower under the stricter rule.
- Low-altitude center error is larger because those targets are found on
  downscaled copies; it is still about 1% of the board width.

## Known limitations and follow-ups

- Synthetic data only; flat-colored ground with no texture. Real-image results
  are on hold.
- 13 non-green X boards still pass verification (orange 7, red 3, blue 3);
  black never does. Working hypothesis: JPEG compression leaves faint greenish
  fringes beside saturated strokes. Likely fix: check the color of the stroke
  pixels themselves, not just green evidence along the diagonals.
- Yellow strokes pass verification on drawn test boards (the generator does not
  render yellow).
- Low-altitude center accuracy: refine the corners at full resolution after a
  downscaled detection.
- Multiscale adds time when nothing is found (up to four passes).