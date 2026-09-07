# Phase 2: Godot and real BRAIN integration

Updated 2026-09-07 after Jabin announced Dev's GitHub update.

## Source and preservation

Fetched and merged origin/main `151c4a0` (Dev's simulator, assets and test tools).
Our previous BRAIN work was preserved in local checkpoint `0e28b90`; merge
commit `8d602bf` retains it. Only .gitignore and brain/config.yaml conflicted.
Ignore rules were combined; tested BRAIN physics values were retained alongside
Dev's camera, budget and world settings. Nothing has been pushed to GitHub.

Godot 4.7.2 standard Windows was downloaded from the
[official archive](https://godotengine.org/download/archive/4.7.2-stable/).
Executable: `C:/dev/tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe`.
The imported execution copy is `C:/dev/iete-integration/sim`, outside OneDrive;
the editable source remains this repository's `sim/`. Copy changed scripts/assets
to the execution copy and reimport before testing. The acceptance command passes
the repository's current shared config explicitly.

## Integration corrections

- SIM now consumes the same 1x physics, 5 Hz observations, 0.8 m marker square,
  1 m/s maximum speed, 1 Wh/m drive, 1 Wh/s dwell and 0.01 Wh/s idle settings as BRAIN.
- Wire position remains Godot X/Z. Wire heading = internal compass heading - 90
  modulo 360; incoming command heading adds 90. Thus wire 0 = +X and 90 = +Z.
- Arrival requires the committed assigned marker and three seconds of stopped
  dwell. Hold, disconnect and timeout cancel dwell. Ground truth stays in SIM.
- Disconnect, exhausted battery and 2.5 seconds without a fresh command stop the
  rover. Replayed and stale actions are rejected. A continuing SIM can reconnect.
- BRAIN's near-target visual reacquisition rule now applies to rocks only. A
  recently seen marker can leave the close camera view during its arrival dwell.
  The existing target expiry and mission confirmation checks still apply.
- Godot preserves integer audit version 2 when recording parsed actions. A failed
  binary send closes the connection rather than leaving an unpaired header.
- Recording flushes evidence during the run. `--exitafter=N` permits bounded runs.

Dev's `tools/aruco_probe.py` and `brain/stub_brain.py` remain optional diagnostic
brains. The acceptance run uses `brain/main.py`, not either diagnostic brain.
The probe's marker-size key was updated to the shared canonical name.

## Evidence

The first real run revealed the marker-arrival bug. The corrected second run
confirmed M02 at physics second 55.4 in Dev's obstacle scene. It recorded 575
frames over 115 seconds. Energy accounting: 45.48996 Wh drive + 1.15000 Wh idle
+ 3.00227 Wh confirmation dwell = 49.64224 Wh spent. The small dwell excess is
one physics/render timing step. This was the classical detector/histogram fallback.

Camera ray measurement in the actual rendered scene: horizontal FOV 60.000 degrees.
Saved images decode to 640x480; an actual frame was visually inspected. M02 was
recognized from pixels. Simple width-derived range estimates at three approach
samples differed from approximate camera-to-marker horizontal ground truth by
1.27, 2.70 and 1.07 m. Quantization, perspective and camera offset/tilt remain
relevant; this is coarse ranging, not precision localization.

A final automated run is recorded under
`recordings/godot-acceptance-20260907-151422/`; SIM frames and messages are under
`C:/dev/iete-integration/runs/godot-acceptance-20260907-151422/`.
Its result.json is written only if frame/message validation, stop/reconnect and
marker confirmation checks all pass. See progress.md for the final result.

## Reproduce

From the repository root after copying/importing the SIM:

```powershell
.\.venv\Scripts\python.exe brain/check_godot.py --godot C:/dev/tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe --sim C:/dev/iete-integration/sim
& C:/dev/tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe --headless --path C:/dev/iete-integration/sim --script res://tests/check_integration.gd
```

The first command uses real GPU rendering, hidden test windows, isolated ports,
105 physics seconds, and a 3-second development downlink. It kills BRAIN at
12 seconds, checks stationary poses after the watchdog deadline, reconnects at
18 seconds and requires a confirmed marker. `--torch` enables pretrained ResNet18;
the default tests the lightweight fallback. The second command tests SIM heading,
dwell energy, confirmation timing, cancellation and stale/replayed commands.

For an interactive view, start BRAIN and then Godot in separate terminals:

```powershell
.\.venv\Scripts\python.exe brain/main.py --no-yolo --no-torch --delay 3
& C:/dev/tools/godot-4.7.2/Godot_v4.7.2-stable_win64_console.exe --path C:/dev/iete-integration/sim -- --lowfx
```

The manual SIM command reads the execution copy's brain/config.yaml; refresh that
copy whenever changing shared settings, or pass an absolute `--config=...` path.

## Remaining boundaries

This establishes initial real-SIM marker integration. It does not establish all
three markers completed, calibrated stay/deviate demonstrations, rock detector
accuracy or the browser PANEL/LAN delay. Earlier 60-second delay acceptance was
against Python stubs; this Godot run uses a 3-second development delay.

Phase 3 can now use the available renderer, but Dev's current labeller emits
three classes (rock/anomaly/marker), lacks our grouped manifest, and samples one
scene. Adapt it to single-class rock and independent capture groups, then review
boxes before training. No YOLO training has run and no learned weights were installed.
