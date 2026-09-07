# Phase 3 novelty diagnostic - 2026-09-07

The first diagnostic on actual Godot scene images did **not** separate annotated unusual rocks from common rocks. Novelty calibration remains incomplete; runtime parameters were not changed.

`brain/build_novelty_crops.py` now produces a reproducible crop manifest from the SIM's offline `annotations.jsonl` files and the prepared detector dataset's provenance. It checks source image hashes against that dataset, records annotation/source/crop hashes, excludes the held-out detector test layout, and assigns independent layouts to each role. Crops must be at least 16 pixels in both dimensions. Selection uses seed 7 and at most one crop per scene object per layout, reducing repeated-frame inflation.

## Actual run

| Role | Source | Crops |
| --- | --- | ---: |
| Memory: common rocks | Seven training layouts | 100 |
| Familiar: common rocks | Validation layout-20261002 | 64 |
| Novel: unusual rocks | Validation layout-20261004 | 2 |

The existing pretrained ResNet18 encoder ran on CPU with two Torch threads while detector training used the GPU. Memory was frozen before evaluation; familiar and novel crops never entered memory. Both roles had median, 10th percentile, and 90th percentile novelty scores of **0.0**. The probability that an unusual crop outranked a familiar crop, counting ties as half, was **0.4609375** (0.5 corresponds to chance ranking). Memory contained 100 embeddings, with `d_lo=0.1717624068260193` and `tau=0.111217200756073`.

Evidence:

- Crop manifest: `datasets/novelty-v1/manifest.jsonl`
- Source and crop provenance: `datasets/novelty-v1/provenance.json`
- Complete per-crop scores: `recordings/phase3-novelty-v1.json`
- Manifest SHA-256: `74c4b94d6ec2cbdded086dd1d85279d4f281bea56d23d9ac58429ea76fa982b1`

Datasets and recordings are local ignored artifacts. The builder and this report are versionable. Four focused checks in `brain/check_novelty_crops.py` pass, covering crop bounds, minimum size, invalid boxes, layout separation, and rejection of insufficient layout groups.

## What this means

The brain compares each rock picture with pictures stored in memory. On these images, the two rocks labelled unusual still looked familiar to that comparison. This result tells us the current visual novelty signal is not yet demonstrated to be useful for this scene; it does not establish the cause.

Only two distinct unusual objects survived the chosen validation layout and crop-size rules. That is too little coverage for a reliable calibration claim. Common and unusual evaluation objects also occupy different layouts, so layout/background effects can influence the comparison. Crops use simulator annotation boxes, not detector predictions; detector crop errors are therefore outside this diagnostic. The common/unusual labels are offline evaluation annotations and never enter the rover's live observations.

Next: capture more unusual objects across independent layouts, inspect crop appearance and score overlap, then evaluate proposed memory/encoder changes on new validation captures. Preserve the held-out test layout for detector evaluation. Do not tune thresholds merely to force these two unusual examples to score higher.

## Reproduce from the repository root

Use fresh output paths to preserve existing evidence:

```powershell
.venv\Scripts\python.exe brain/build_novelty_crops.py datasets/rocks-export-v1 datasets/rocks-v1/provenance.json datasets/novelty-v2
.venv\Scripts\python.exe -c "import sys,torch; sys.path.insert(0,'brain'); torch.set_num_threads(2); from check_novelty_dataset import run; run('datasets/novelty-v2/manifest.jsonl','recordings/phase3-novelty-v2.json',device='cpu')"
.venv\Scripts\python.exe brain/check_novelty_crops.py
```
