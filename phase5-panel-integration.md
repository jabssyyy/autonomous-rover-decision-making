# Phase 5: real BRAIN and Dev's PANEL

2026-09-07. Dev's GitHub update supplied the static console in `panel copy/`.
The currently running Godot must stay running. Connecting this page to its
existing BRAIN does not require restarting Godot or launching another SIM.
The current BRAIN process uses `--no-yolo --no-torch --delay 3`: this live
session uses classical perception and a **three-second communication delay**.
The trained detector and ResNet demonstrations are preserved in the Phase 4
videos. Do not describe this existing session as the trained 60-second run.

## Open the real console

The integration task already started HTTP on port 8000 (PID 14116). Open
**http://127.0.0.1:8000/?tc=1** now. If that server is later stopped, restart
it from the repository root with:

```powershell
.\.venv\Scripts\python.exe -m http.server 8000 --bind 0.0.0.0 --directory "panel copy"
```

Open **http://127.0.0.1:8000/?tc=1** on Jabin's laptop. The page connects to
the existing BRAIN WebSocket on port **8766**. Do not start a second BRAIN
on the same port. The `tc=1` fallback matches the current real-time simulator;
received BRAIN clock stamps remain authoritative.

On Dev's second screen, use `http://<Jabin-Wi-Fi-IP>:8000/?tc=1`. The page
automatically uses that host for its WebSocket. If a second screen cannot
connect, show the same local page beside Godot on Jabin's laptop.

The current session has a three-second delay. A future run using the standard
profile has a 60-second delay. A connected console waiting
for telemetry is different from a lost link. Leave BRAIN running after the
rover stops so the queued final decisions can arrive.

## What to explain to the judges

Godot shows what the rover is doing now. PANEL shows what Earth learns later.
BRAIN uses the current camera, remembers appearances, and compares the benefit
of each candidate with its estimated energy cost and the mission reserve.
PANEL displays the resulting decision and checks its arithmetic.

Use the verified [Phase 4 stay and deviate videos](phase4-demo.md) to show the
two budget settings. The stay run notices novelty and prioritizes M02. The
deviate run spends available energy on an inspection, finishes, and resumes
the mission. Both recorded runs confirmed M02; neither completed all markers.

During a planned live interrupt rehearsal, PANEL's **A** key requests abort
investigation and **H** requests halt. These send real commands to connected
BRAIN and are subject to the communication delay. A five-second inspection
may already be finished when Earth's abort arrives, especially in the standard
60-second profile. Do not press these keys
merely to test the display during the running presentation.

## Clearly separate fallback modes

**Recorded real telemetry:** replay uses genuine Phase 4 decisions but does
not create a new live delay. Run it on a separate port to preserve the current
BRAIN and Godot:

```powershell
.\.venv\Scripts\python.exe brain/replay.py recordings/godot-acceptance-20260907-162605/brain-first/20260907_162612_brain-first --port 18766 --wait
```

Then open `http://127.0.0.1:8000/?port=18766&tc=1`. Announce that this is a
recording. Replay ignores uplink commands, so it cannot validate a live abort.

**Synthetic UI rehearsal:** `http://127.0.0.1:8000/?demo=1` fabricates data in
the browser and is labelled `SIMULATED SOURCE`. It is for rehearsing the
console; use the ordinary URL for the real rover. Demo mode is never an
automatic fallback from a disconnected real link.

## Verification status

This handoff records launch instructions and mode boundaries. Integration
checks and their measured results are recorded by the main integration task;
this document alone does not claim a completed live delayed-abort rehearsal.

## Integration checks performed

Merged origin b2e467c. Fixed audit v2 curiosity scaling and denominator epsilon,
actual decision display, time compression fallback, partial JPEG reconnect state
and command acknowledgements from explicit BRAIN audit notes. Node syntax and
isolated arithmetic/ack checks passed. All four HTTP assets return 200 with
appropriate MIME types. Three real live telemetry messages and their JPEGs
passed the contract validator (measured delay 3.000, 3.000 and 3.013 seconds).

Wi-Fi URL: http://192.168.22.70:8000/?tc=1 . Remote LAN access has not been tested.
Automated approval review blocked the headless browser launch without a more
specific reason; no visual browser pass is claimed. Open the local link for that
last check. No live abort/halt was sent. The running Godot and BRAIN processes
were preserved.
