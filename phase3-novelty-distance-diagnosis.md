# Novelty distance diagnosis - 2026-09-07

Both score clipping and weak raw visual separation contributed to the first novelty diagnostic. No runtime encoder, memory rule, or threshold has been changed.

`brain/diagnose_novelty_distances.py` compares three fixed representations on the existing `datasets/novelty-v1` crops: pretrained ResNet18, the existing histogram/texture fallback, and equal-weight concatenation of their unit vectors followed by normalization. It compares raw nearest cosine distance with the unchanged runtime novelty formula. Common memory remains frozen, all memory-derived thresholds are calculated independently of evaluation labels, and no fitting or downloads occur. The script uses the cached checkpoint and CPU with two Torch threads.

| Representation | Raw distance rank AUC | Runtime score rank AUC | Familiar / unusual clipped to zero |
| --- | ---: | ---: | --- |
| ResNet18 | 0.609375 | 0.4609375 | 59/64 and 2/2 |
| Histogram/texture | 0.640625 | 0.6875 | 54/64 and 1/2 |
| Equal-weight ResNet18 + histogram | 0.8125 | 0.66796875 | 57/64 and 1/2 |

Rank AUC is the probability that an unusual crop outranks a familiar crop, counting ties as half. For ResNet18, the common raw-distance median was 0.1105043 and unusual median was 0.1218790. Both unusual distances fell below the memory-derived `d_lo=0.1717624`, causing zero scores. Common distances also overlapped those unusual distances substantially. Removing clipping would therefore preserve some ranking information but would not establish a reliable detector of unusual appearance.

The combined representation had a stronger raw ranking on these particular crops. This is exploratory evidence only: there are just two distinct unusual evaluation objects, and common/unusual evaluation crops came from different layouts. Comparing alternatives on this sample cannot establish generalization or justify selecting a new runtime encoder. Balanced independent captures with matched layout conditions are needed before making that decision. The detector's held-out test layout remains unused.

Evidence: `recordings/phase3-novelty-distance-v1.json` contains per-crop raw distances and scores, source hashes, cached checkpoint hash, memory sizes, thresholds, and summary statistics. The original crop provenance is unchanged. Two focused tests pass in `brain/check_novelty_distances.py`, checking rank ties and a fixture where raw separation is lost through clipping.

Reproduce using a fresh report path:

```powershell
.venv\Scripts\python.exe brain/diagnose_novelty_distances.py datasets/novelty-v1/manifest.jsonl recordings/phase3-novelty-distance-v2.json
.venv\Scripts\python.exe brain/check_novelty_distances.py
```

In beginner terms: the brain can see some visual difference, but its current rule treats many of those differences as too small to count. We have measured that effect without changing the rule to suit these few examples.
