# Phase 3 results: learned rock detector

2026-09-07. **Detector trained, evaluated and installed. Novelty calibration remains open.**

Godot supplies the pictures; YOLO26n finds rocks; ResNet18 describes each crop;
memory and policy assess novelty and decide whether visiting is worthwhile.
Common and unusual boulders both have detector class `rock`. The running BRAIN
never receives the simulator's object labels or positions.

## Dataset and training

Dev's exporter now writes single-class labels, empty background label files,
grouped manifests and separate offline novelty annotations. The old dataset YAML
that used identical training and validation images was removed.

`brain/export_rocks.py` rendered 1,500 images across ten seeded layouts, with
7,164 boxes. Whole layouts stay in one split:

| Split | Images | Boxes | Background images |
|---|---:|---:|---:|
| Training | 1,050 | 5,107 | 68 |
| Validation | 300 | 1,354 | 11 |
| Test | 150 | 703 | 4 |

The layouts reuse the same mesh families: this measures new simulator views and
layouts, not unseen rock assets or real Mars. Labels use projected bounds and
centre-ray occlusion checks, so partially hidden rocks and loose boxes remain
limitations. Pilot label overlays and test predictions were visually inspected.
Some sign backs and small features produce false positives.

Fine-tuned pretrained YOLO26n for **15 epochs**, image size 640, batch 16, seed 7,
on the RTX 5060. Epochs took approximately 9.8 minutes. The best checkpoint was
selected using validation; the held-out test layout was evaluated separately.

| Held-out metric | Value |
|---|---:|
| mAP50 | 0.8979 |
| mAP50-95 | 0.5685 |
| Precision | 0.9024 |
| Recall | 0.8288 |

This exceeds the planned mAP50 target of 0.60. Precision and recall are the
evaluator's reported operating point, not guarantees at every confidence setting.
The recipe uses the documented [Ultralytics training API](https://docs.ultralytics.com/modes/train/)
and [YOLO26 model](https://docs.ultralytics.com/models/yolo26/).

## Real runtime and installed model

The 20-second real Godot smoke test passed with **aruco+yolo+resnet18**:
100 observations and 19 valid actions. This checks learned perception and
steering, not a complete mission or discovery after warm-up. Decision-frame
perception measured median 235.2 ms and p95 328.3 ms. The full crop/encoder
pipeline can fall behind the 5 Hz camera; the existing newest-frame policy
handles that. A 1 Hz decision cadence was demonstrated.

The exact tested checkpoint is installed locally at `brain/weights/rock.pt`.
[brain/rock-model.json](brain/rock-model.json) records its SHA-256, recipe and
evidence paths. Weights, datasets and recordings are ignored local artifacts;
the recipe and model manifest are versioned. No GitHub push was performed.

- Export: `datasets/rocks-export-v1/export.jsonl`
- Prepared dataset: `datasets/rocks-v1/dataset.yaml` and `provenance.json`
- Training: `recordings/rock-train-v1/run/results.csv` and `result.json`
- Held-out test: `recordings/rock-test-v1/result.json` and plots under `run/`
- Learned live check: `recordings/godot-acceptance-20260907-154042/result.json`

All 15 epochs and per-epoch validation finished, but the library's final
standalone validation stripped the apostrophe from the absolute `IETE'26` path.
The checkpoint was intact; the recovery is recorded, and separate test evaluation
succeeded. Future training outputs must use an apostrophe-free directory such as
`C:/dev/iete-training/rock-v2`; the CLI now rejects problematic output paths early.
Runtime loading uses a hash-checked temporary cache for quoted checkpoint paths.
The installed original stays in this project.

## Remaining Phase 3 work

The independent novelty diagnostic used 100 memory crops, 64 familiar crops and
only two unusual objects. Both evaluation medians were zero; rank AUC was 0.4609.
**Useful novelty separation is not demonstrated.** See
[phase3-novelty-results.md](phase3-novelty-results.md). Runtime thresholds were
not changed to force these examples to score higher.

Next: broader unusual-object captures, memory/encoder diagnosis and calibrated
discovery after warm-up. Dev's browser PANEL and staged stay/deviate missions
also remain pending. Do not call the full phase complete.

60 Python checks pass, including new exporter, crop and path regressions. The
real export handoff, held-out evaluation and learned Godot smoke check also pass.

## Run and reproduce

Start learned BRAIN from the repository root:

```powershell
.\.venv\Scripts\python.exe brain/main.py --delay 3
```

Use `--no-yolo` for the classical rock fallback; add `--no-torch` for the lighter
histogram encoder. Godot launch instructions are in [Phase 2](phase2-integration.md).

For a new dataset/run, use fresh output directories:

```powershell
.\.venv\Scripts\python.exe brain/export_rocks.py --godot C:/dev/tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe --sim C:/dev/iete-integration/sim --output datasets/rocks-export-v2 --seed 20261101
.\.venv\Scripts\python.exe brain/rock_dataset.py datasets/rocks-export-v2/export.jsonl datasets/rocks-v2
.\.venv\Scripts\python.exe brain/train_rocks.py train --dataset datasets/rocks-v2/dataset.yaml --output C:/dev/iete-training/rock-v2 --epochs 15 --batch 16
.\.venv\Scripts\python.exe brain/train_rocks.py evaluate --dataset datasets/rocks-v2/dataset.yaml --weights C:/dev/iete-training/rock-v2/run/weights/best.pt --output recordings/rock-test-v2 --batch 16
```

The execution copy must contain the current exporter script before rendering.
