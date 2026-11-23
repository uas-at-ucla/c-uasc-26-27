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

Findings:

- **Misses dominate and depend on altitude.** No targets are found below 15 m.
  Working hypothesis (not yet verified): the background blur (σ = 18 px) was
  tuned for ~40 px targets, while low-altitude boards are hundreds of pixels wide.
- **Green verification works on shape look-alikes:** it removes all `plus`,
  `plain` and clutter false positives, but 17% of non-green X boards still pass.
- The package on the center does not reduce recall.

## Known limitations and follow-ups

- Synthetic data only; ground is flat-colored with no texture or shadows from
  objects. Real-image results are on hold.
- Low-altitude misses (see above).
- `other_color` false positives need diagnosis.