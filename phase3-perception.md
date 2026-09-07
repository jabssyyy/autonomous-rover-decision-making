# Phase 3: perception upgrade

Status 2026-09-07: BRAIN tooling implemented; scene-dependent work pending.
Jabin requested Phase 3 while Dev prepares GitHub. Do not fetch/pull until Jabin
announces the update. Phase 2 remains unverified; Phase 3 is not yet complete.

## What this adds

Rock detection answers "where is a rock?"; appearance memory answers "how
different does it look from what I have learned?". Policy then weighs novelty
against the mission and battery. Training tools cover the first question;
see [rock-training.md](rock-training.md).

`brain/check_novelty_dataset.py` now covers the second question. It uses the
same ResNet18 or histogram encoder and NoveltyMemory calculation as BRAIN.
It fills memory with common-rock crops, freezes memory, then scores separate
familiar and unusual crops. Test pictures never enter memory during evaluation.
This measures static appearance separation. Live tracking, warm-up and delayed
admission still need real scene validation.

## Inputs and commands

Export tightly cropped visible rocks as JPEG/PNG files. Supply `crops.jsonl`,
with paths relative to its directory:

```json
{"image":"crops/common01.png","group":"layout01","role":"memory"}
{"image":"crops/common02.png","group":"layout02","role":"memory"}
{"image":"crops/common-heldout.png","group":"layout03","role":"familiar"}
{"image":"crops/unusual-heldout.png","group":"layout04","role":"novel"}
```

Use all three roles, at least two distinct memory embeddings, no more than 512
memory crops, and crops at least 8x8 pixels. Exact duplicates and capture/layout
groups crossing roles are rejected. Keep related views together: near duplicates
are not automatically detected. Human familiar/novel labels are offline review
judgments, never runtime observations.

```powershell
.\.venv\Scripts\python.exe brain/check_novelty_dataset.py datasets/novelty/crops.jsonl recordings/novelty-v1.json
.\.venv\Scripts\python.exe brain/check_phase3.py
```

Defaults are pretrained ResNet18 and CUDA 0. Use `--encoder hist` for the fallback
or `--device cpu` for CPU ResNet18. Reports require new output paths and include
input hashes, encoder identity, memory size, d_lo, tau, per-crop scores and score
percentiles. The rank statistic is 1 when every unusual crop outranks every
familiar crop; 0.5 means no overall rank advantage. It is a diagnostic, not an
automatic acceptance threshold or proof of scientific interest.

Review crops and score overlap. Improve common-memory coverage if needed.
`--scale` explores the novelty scale floor (default 0.1), without changing live
configuration. Reserve untouched captures for confirmation after tuning.

## Verification and remaining work

Five new checks pass: histogram report/no overwrite, group leakage, duplicate
pixels, missing roles/path escape, and frozen-memory/rank behavior. The actual
pretrained ResNet18 GPU diagnostic also executed on synthetic fixture pictures:
`recordings/phase3-fixture-20260907-144535/novelty.json`. This proves execution,
not accuracy on rocks. No real scene calibration or YOLO training has run.

Pending: roughly 1,500 labeled SIM frames, real YOLO training and held-out metrics,
visual label review, scene-based novelty calibration, approved weight installation
and live detection/fallback checks. Dev's browser PANEL is also pending and remains
his lane. Stop after this BRAIN-side increment until Jabin supplies the update/data.
