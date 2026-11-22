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

`images/` plus `labels.csv` with columns `filename,x,y,occluded`.
`x,y` are the X intersection in original image pixels; `occluded` is 0 or 1.
The format cannot yet represent target-absent frames.

### `blender_test_200`

- Copy of `output_test/dataset` from playing around in another project folder.
- Generator: `generate_green_x.py` (not yet in this repo). The exact generation
  command was not recorded.
- 200 frames (`frame_00000`–`frame_00199`), 256×256 px.
- Camera 9–26 m above the target, with varied position and angle.
- Backgrounds: concrete, soil, dry grass, asphalt.
- 57 of 200 frames include a bucket-shaped placeholder occluder.

## Classical baseline

`baseline_v2.py` finds a bright white quadrilateral, uses its diagonal
intersection as the center, and optionally verifies the green X in a
perspective-warped crop. Green threshold: `DEFAULT_GREEN_THRESHOLD = 0.030` in baseline_v2.py, used by the command line and `evaluate.py`

```bash
python green_x/check_dataset.py <dataset_dir>
python green_x/evaluate.py --dataset <dataset_dir>
```

## Results on `blender_test_200`

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

## Known limitations and follow-ups

- Synthetic 256×256 frames only; results won't transfer directly to the
  high-resolution wide camera.
- No target-absent frames yet, so false positives are not measured.