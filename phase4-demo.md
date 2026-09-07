# Phase 4 demo: ready to show

2026-09-07. Both recorded behavior demonstrations passed. Dev owns PANEL;
these videos can be shown now without waiting for its integration.

## Play the demo now

Open [stay video](recordings/phase4-stay.mp4), then
[deviate video](recordings/phase4-deviate.mp4). Each is approximately 90 seconds.
They show the real recorded rover camera with the corresponding BRAIN audit,
energy and marker confirmations. They are annotated recording exports, not a
screen capture of Dev's PANEL. Both files were decoded completely (898 frames
each), and representative frames were visually inspected.

Say: **The same code and world run twice. Only starting energy and gamma change.**

| Setting / result | Stay | Deviate |
|---|---:|---:|
| Starting energy | 210 Wh | 1000 Wh |
| Gamma | 5 | 2 |
| Duration | 90 s | 90 s |
| Camera observations | 450 | 450 |
| Decisions received by SIM | 85 | 81 |
| Energy spent | 45.88 Wh | 46.56 Wh |
| Confirmed markers | M02 | M02 |
| Highest observed novelty | 0.908 | 0.981 |
| Rock selected | No | Yes |

Gamma controls how strongly limited spare energy suppresses curiosity. With
less energy and gamma 5, mission work dominates. With more energy and gamma 2,
a nearby novel-looking rock can be worth investigating.

At 30.6 seconds in the stay run, BRAIN saw a candidate with novelty 0.908 but
gave it utility 0.0103; M02 had utility 3.9455. It kept driving to M02.

In the deviate run, BRAIN began inspecting R34 at 15.62 seconds, recorded
completion at 21.41 seconds, and was driving toward M02 again by 22.6 seconds.
The measured settled dwell had zero movement. Another inspection occurred later;
this is an ongoing policy, not a script limited to one detour.

R34's novelty was 0.341, below the 0.45 anomaly display threshold. Its confidence,
distance and budget-weighted novelty together made its utility 3.1243, above
the marker candidate's 1.448. The display label does not control the policy.
R34 is a visual track, not verified scientific interest or a specific SIM asset.

## Reproduce or run live

Measured shared profiles are [stay](brain/demo/stay.yaml) and
[deviate](brain/demo/deviate.yaml). The old 560/950 and 420/1000 proposals are
superseded. Main defaults were not switched to the low-budget profile.

For a fresh recorded pair (use a new output directory):

```powershell
.\.venv\Scripts\python.exe brain/run_demo_pair.py --godot C:/dev/tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe --sim C:/dev/iete-integration/sim --out recordings/demo-next
```

The wrapper snapshots both configs, runs the existing real integration harness,
checks code/model hashes for changes between runs, waits for the 60-second
downlink tail, audits the pair, and exports videos. Its component launches,
pair checker, renderer and delivery check were exercised during this checkpoint;
the combined wrapper has not yet been run end to end.

For a live presentation, open separate terminals. Replace `stay` with `deviate`
in **both** commands for the second run, restarting both processes:

```powershell
.\.venv\Scripts\python.exe brain/main.py --config brain/demo/stay.yaml --tag stay
& 'C:/dev/tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe' --path C:/dev/iete-integration/sim -- --config="C:/Users/Jabin M/OneDrive/Documents/IETE'26/brain/demo/stay.yaml" --brain=ws://127.0.0.1:8765 --record=live-stay --lowfx
```

Use the current imported SIM copy outside OneDrive. The world seed, starting
pose, camera, mission, models and policy implementation are shared. Runtime
scheduling and paths can vary; the recorded videos are the reliable fallback.

## Evidence and replay

- [Versioned metrics and hashes](brain/demo/results.json)
- `recordings/phase4-pair-acceptance.json`: full paired audit
- `C:/dev/iete-integration/runs/godot-acceptance-20260907-162347`: stay SIM data
- `C:/dev/iete-integration/runs/godot-acceptance-20260907-162605`: deviate SIM data
- `recordings/godot-acceptance-20260907-162347/brain-first/20260907_162401_brain-first`: stay BRAIN data
- `recordings/godot-acceptance-20260907-162605/brain-first/20260907_162612_brain-first`: deviate BRAIN data

Both runs preserve camera observations and decisions for disk replay. The
deviate run also drained all 81 delayed telemetry messages and checked attachment
files and at least 60 seconds of real delay. The initial stay run stopped BRAIN
with its downlink tail still pending: its camera/decision video is complete,
but its delivered-telemetry replay is partial. The new wrapper drains both tails.

Once PANEL is ready, the complete deviate telemetry recording can be replayed:

```powershell
.\.venv\Scripts\python.exe brain/replay.py recordings/godot-acceptance-20260907-162605/brain-first/20260907_162612_brain-first --wait
```

This replays previously delivered messages at their recorded cadence; it does
not demonstrate a new live 60-second delay. Live delay and the late interrupt
still require Phase 5 rehearsal with Dev's PANEL.

## Checks and limits

Eight new pair-checker rejection tests passed, including altered arithmetic,
hidden ground truth, incorrect profiles and a stay run that selects rocks.
All 900 recorded observations/JPEGs and 166 actions passed the existing wire
contract and arithmetic verifier. The pair checker verified same initial
pose/camera/mission, config differences, warm-up, strong novelty in the stay
run and the complete deviate dwell/resumption sequence.

Neither run completed all three assigned markers. The small difference in total
energy spent is not a measured detour cost: the rover follows different paths
and performs different actions. These are live demonstrations, not a controlled
causal benchmark or real-world validation. New scene/assets require restaging.

Phase 4 ends here. Next: Phase 5 PANEL connection, late-interrupt rehearsal and
pitch handoff. No message was sent to Dev or Anton and no code was pushed.
