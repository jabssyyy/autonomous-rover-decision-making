# Phase 3: novelty validation and live discovery

2026-09-07. BRAIN's next Phase 3 step is complete for the tested simulator
profile. The detector already worked; this step checks whether remembered rock
appearances support useful novelty decisions. PANEL and the paired stay/deviate
mission demonstration remain pending. No changes have been pushed.

## What changed

The exporter can now capture focused common/unusual rock views under the normal
simulator lighting (`--novelty`). These labels are used only for offline checks;
the running BRAIN still receives pixels and the permitted rover state.

Six new layouts produced 480 images. Two layouts supply common-rock memory,
two support encoder selection, and two are reserved for confirmation. Familiar
and unusual evaluation crops come from the same layouts. Crops retain hashes,
source boxes and object identities for reproducibility; checks reject duplicate
pixels and memory/evaluation layout overlap.

On the development split, the existing ResNet18 runtime score achieved rank AUC
0.8700, versus 0.6252 for histograms and 0.8619 for combined embeddings. We kept
ResNet18, the existing score formula, scale floor 0.1 and anomaly display threshold
0.45. The selection was recorded before evaluating the confirmation split.

| Confirmation measure | Result |
|---|---:|
| Common memory crops | 74 |
| Familiar / unusual evaluation crops | 70 / 46 |
| Familiar median novelty | 0.0000 |
| Unusual median novelty | 0.1659 |
| Runtime score rank AUC | 0.8326 |

AUC measures ranking: 0.5 is chance-level ordering and 1 is perfect ordering.
This shows useful separation in these captures, not reliable detection of every
unusual rock. Only 14.8% of development unusual crops exceeded the conservative
0.45 display threshold; policy also uses continuous novelty below that threshold.
There are only three unusual mesh families and repeated views are correlated.
Lighting changes, unseen assets and real-world transfer remain unverified.

## Live result

The previous 60-second warm-up could absorb newly revealed rocks as familiar.
The tested Dev-scene profile now uses 15 seconds of warm-up. This timing depends
on the starting scene; it is not a universal novelty calibration.

The learned Godot run recorded 375 observations and 73 actions over 75 seconds:

1. Before warm-up ended, candidate novelty stayed zero.
2. At 27.61 seconds, BRAIN began investigating appearance track R36.
3. At 33.0 seconds, its audit recorded investigation complete. Measured motion
   during the settled dwell window was 0.0283 metres, below the 0.05-metre check.
4. At 47.2 seconds, BRAIN resumed a drive-to-marker action toward M02.

R36 is a BRAIN track, not a verified simulator anomaly identity. This proves the
tested discovery/action/resumption sequence, not scientific importance or a
complete mission. No marker was confirmed within this run; reconnect was not
tested here (the earlier Phase 2 run covered it).

## Evidence and reproduction

All 67 Python regression checks passed. The actual balanced dataset also passed
its provenance/hash/crop audit, and the recorded live run passed the discovery
sequence and dwell-motion checks.

Local generated data and recordings are ignored by Git:

- `datasets/novelty-balanced-export-v1` and `datasets/novelty-balanced-v1`
- `recordings/phase3-novelty-balanced-dev-v1.json`
- `recordings/novelty-calibration-selection.json`
- `recordings/phase3-novelty-confirmation-v1.json`
- `recordings/godot-acceptance-20260907-155439/result.json`
- `recordings/phase3-discovery-acceptance.json`

```powershell
.\.venv\Scripts\python.exe brain/check_balanced_novelty.py --export datasets/novelty-balanced-export-v1 --dataset datasets/novelty-balanced-v1
.\.venv\Scripts\python.exe brain/check_discovery_run.py C:/dev/iete-integration/runs/godot-acceptance-20260907-155439
.\.venv\Scripts\python.exe brain/check_godot.py --godot C:/dev/tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe --sim C:/dev/iete-integration/sim --rock-weights brain/weights/rock.pt --torch --smoke --seconds 75 --warmup-seconds 15
```

The original tiny-sample failure remains documented in
[phase3-novelty-results.md](phase3-novelty-results.md); the raw-distance diagnosis
is in [phase3-novelty-distance-diagnosis.md](phase3-novelty-distance-diagnosis.md).

## Beginner explanation and next boundary

The detector is the rover's rock finder. ResNet describes each rock's appearance.
Memory gives the rover examples of what it has already seen. Novelty measures
how different a new appearance is. Policy then checks whether spending time and
energy on it is worthwhile. This run exercised the final step: stop to inspect,
finish the inspection, then return to the marker task.

Next is a paired demonstration: one run should stay on mission when inspection
is unaffordable, and another should deviate when the budget permits. Record the
costs, decisions and marker outcomes. Dev's browser PANEL still needs integration.
Stop here for Jabin's phase review before building that next demonstration.
