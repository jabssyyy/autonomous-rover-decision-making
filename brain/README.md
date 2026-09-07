> **Integration update, 2026-09-07:** Dev's `151c4a0` is merged locally.
> Real Godot + BRAIN acceptance passed: 525 frames, 96 validated actions,
> M02 confirmed, disconnect stop and reconnect verified. See
> [phase2-integration.md](../phase2-integration.md). Initial marker integration
> is established; all-marker missions, browser PANEL and trained rocks remain pending.

# Running the BRAIN baseline

**Phase 1 update:** the shared config now uses 1x physics time and audit v2.
Run `python brain/check_phase1.py` with the project venv for policy, memory,
runtime, and watchdog checks. The older Phase 0 evidence folders retain their
original configuration and may not run with the corrected Phase 1 code.

Use the repository's `.venv` (Python 3.13). Commands below start at the repository
root. The CPU baseline uses real OpenCV marker detection, simple rock proposals,
and histogram-based appearance memory. It does not load a trained rock detector.

## Reproduce Phase 0

```powershell
.\.venv\Scripts\python.exe brain/check_foundation.py
.\.venv\Scripts\python.exe brain/check_phase0.py --delay 3
.\.venv\Scripts\python.exe brain/check_phase0.py --delay 3 --uplink
.\.venv\Scripts\python.exe brain/check_phase0.py --delay 3 --torch
.\.venv\Scripts\python.exe brain/check_phase1.py
# Full real-time downlink check; takes a little over one minute:
.\.venv\Scripts\python.exe brain/check_phase0.py --delay 60
```

The phase check verifies JPEG marker detection, bearings and ranges, GPU matrix
and convolution execution, and starts three real processes: BRAIN, stub SIM, and
stub PANEL. It checks recorded actions, movement, budget drain, delayed telemetry,
and decoded panel images. Each run saves its report, configs, logs, and images
under `recordings/phase0-<timestamp>/`. Test processes are stopped afterward.

It uses free localhost ports and a temporary **1x time** configuration, with
camera frames at 5 Hz and decisions no faster than once per physics second.
Shared `brain/config.yaml` now uses the same 1x profile and shared energy/dwell
rates. Dev must use this revision during integration. A passing baseline is not proof that
the two stay/deviate mission demonstrations work.

## Start the three processes manually

Open three PowerShell terminals at the repository root. These use the current
shared config and standard ports. No evidence-folder placeholders are needed.

BRAIN:

```powershell
.\.venv\Scripts\python.exe brain/main.py --no-yolo --no-torch --record-dir recordings/manual --tag baseline
```

SIM and PANEL:

```powershell
.\.venv\Scripts\python.exe brain/stub_sim.py --brain ws://127.0.0.1:8765 --hz 5
.\.venv\Scripts\python.exe brain/stub_panel.py --url ws://127.0.0.1:8766
```

Stop each terminal with Ctrl+C. The PANEL is currently a console stub, not Dev's
browser interface. An empty panel during the first delay interval is expected.
Omit `--no-torch` to use pretrained ResNet18; its cached weights are under
`brain/weights/cache/hub/`. There is no trained rock detector yet: `--no-yolo`
makes that explicit. Without it, BRAIN only loads local single-class rock weights
if available. `--delay 3` on BRAIN shortens the link for development.

## Prepare rock training while SIM is pending

See [rock-training.md](../rock-training.md) for Dev's export format, preparation,
training and held-out evaluation commands. The tools are ready; no rock model
has been trained. Run their offline checks with:

```powershell
.\.venv\Scripts\python.exe brain/check_rock_training.py
```

## Recreate the environment

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r brain/requirements-win-cuda.txt
.\.venv\Scripts\python.exe -m pip check
```

`requirements-win-lock.txt` records all installed package versions. For an exact
package-version reinstall, use that file with
`--extra-index-url https://download.pytorch.org/whl/cu130`. GPU wheels come from
the [official PyTorch index](https://download.pytorch.org/whl/cu130/); see the
[PyTorch installation guide](https://pytorch.org/get-started/locally/) for the
platform selection process. The installed versions and actual GPU execution,
rather than the version claims in older notes, are the evidence for this machine.
