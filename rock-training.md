> Phase 3 update (2026-09-07): frozen-memory novelty evaluation tooling is implemented
> alongside detector training preparation. See [Phase 3 status](phase3-perception.md).
> Actual scene training/calibration and Dev's PANEL remain pending; no GitHub pull
> until Jabin announces Dev's update.

# Rock detector: offline training preparation

Updated 2026-09-07. **Preparation implemented and tested; no detector trained.**
Jabin authorized independent BRAIN work while Dev updates GitHub. Phase 2 Godot
integration remains pending. Do not fetch/pull again until Jabin reports the update.
This is preparation for Phase 3, not completion of Phase 3.

## What this adds to the brain

The detector will learn where rocks appear in camera pictures. It will produce
boxes and confidence scores; the existing novelty memory and policy then decide
whether a rock is interesting and affordable to visit. Training labels are the
teacher's answer sheet, used offline only. Runtime BRAIN still receives pixels
and the existing allowed telemetry, never the scene's rock locations.

## Export Dev needs to supply

Provide 640x480 JPEG or PNG pictures and one UTF-8 text label file per picture.
Each visible rock gets a line `0 cx cy width height`: class 0 is rock, and all four
coordinates are normalized by image width/height. Clip partially visible boxes
to the image boundary. Label visible rocks consistently; a fully occluded rock
must not become a training box. Include pictures without rocks with empty label
files. Review exported boxes overlaid on pictures before preparing the dataset.

Supply `export.jsonl` in the export root, one JSON object per picture:

```json
{"image":"images/frame0001.png","label":"labels/frame0001.txt","group":"layout01-capture01"}
{"image":"images/frame0002.png","label":"labels/frame0002.txt","group":"layout01-capture01"}
```

Paths must remain inside that root. A group represents an independent scene
layout/capture family: adjacent frames and repeated views of the same layout
belong together. Renaming adjacent frames into different groups defeats the
split. Use varied independent layouts, distances, light, rock appearances and
backgrounds; three groups are the minimum to run the tool, not evidence of a
sufficient dataset. Exact decoded duplicates are rejected; near duplicates
still depend on honest grouping and visual review.

## Prepare, train, evaluate

Run these from the repository root after the export arrives. The example paths
assume Dev's export is placed in `datasets/rocks-export/`.

```powershell
.\.venv\Scripts\python.exe brain/rock_dataset.py datasets/rocks-export/export.jsonl datasets/rocks-v1
.\.venv\Scripts\python.exe brain/train_rocks.py train --dataset datasets/rocks-v1/dataset.yaml --output recordings/rock-train-v1 --dry-run
.\.venv\Scripts\python.exe brain/train_rocks.py train --dataset datasets/rocks-v1/dataset.yaml --output recordings/rock-train-v1
.\.venv\Scripts\python.exe brain/train_rocks.py evaluate --dataset datasets/rocks-v1/dataset.yaml --weights recordings/rock-train-v1/run/weights/best.pt --output recordings/rock-test-v1
```

Preparation copies files into a fresh directory and allocates approximately
70/20/10 percent of **groups**, not images, to train/validation/test (seed 7).
All splits need positive rock labels. A provenance file records membership,
counts and file hashes. Commands recheck files before work; output directories
must be fresh so previous evidence survives. Keep a prepared dataset in place:
its YAML records an absolute root. Regenerate into a new directory if relocating.

Training defaults to the pretrained `yolo26n.pt` checkpoint (downloaded on the
first real training invocation), 40 epochs, 640-pixel input, batch 8, GPU 0 and
zero loader workers for Windows. A local `.pt` checkpoint is also accepted.
Use `--device cpu` or a smaller `--batch` if needed. The CLI uses the documented
[Ultralytics training API](https://docs.ultralytics.com/modes/train/) and
[single-class detection dataset format](https://docs.ultralytics.com/datasets/detect/).

Training uses training images to learn and validation images to choose a best
checkpoint. Evaluate the selected checkpoint on the held-out test split only
after tuning is finished; repeatedly tuning against test results makes it cease
to be an independent check. `result.json` records hashes, settings and metrics.
mAP50 >= 0.60 is the planned numerical target, not sufficient acceptance alone.
Inspect false positives/missed rocks and run real Godot perception checks before
manually installing approved weights at `brain/weights/rock.pt`. Nothing here
automatically installs weights or claims the live detector works.

## Verification and remaining work

`brain/check_rock_training.py` has 12 passing checks for malformed labels,
dimensions, duplicates, path boundaries, grouping, modified files, no overwrite,
dry-run behavior, training arguments and held-out evaluation/class checks.
Images and model responses in these tests are synthetic fixtures. They establish
pipeline behavior, not accuracy, training compatibility under a real run, or
visual export quality. No real model training/evaluation has run in this step.

Pending: Dev's simulator and labeled export, visual annotation review, actual
training, held-out metrics, runtime camera calibration, and live rock detection.
