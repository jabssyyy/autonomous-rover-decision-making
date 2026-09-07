"""Run real BRAIN + an imported Godot project, test disconnect/reconnect, save evidence.

Requires an existing Godot executable and imported SIM copy. No dummy brain is used.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import cv2
import yaml

from contract import validate_action, validate_observation

HERE = Path(__file__).resolve().parent


def rows(path):
    if not path.exists():
        return []
    lines = path.read_text(encoding='utf-8').splitlines()
    result = []
    for i, line in enumerate(lines):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise
    return result


def run(args):
    out = HERE.parent / 'recordings' / ('godot-acceptance-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    sim = args.sim.resolve()
    shared = Path(getattr(args, 'config', HERE / 'config.yaml')).resolve()
    run_dir = sim.parent / 'runs' / out.name
    cfg = yaml.safe_load((HERE / 'brain.yaml').read_text(encoding='utf-8-sig'))
    cfg['ports'].update(host='127.0.0.1', sim=args.port, panel=args.port + 1)
    if args.warmup_seconds is not None:
        cfg['perception']['novelty_warmup_s'] = args.warmup_seconds
    if args.rock_weights:
        if not args.rock_weights.is_file():
            raise ValueError('candidate rock checkpoint is missing')
        cfg['perception']['yolo_weights'] = str(args.rock_weights.resolve())
    (out / 'brain.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')
    startup = None
    if sys.platform == 'win32':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    processes, handles = [], []

    def launch(name, command):
        handle = (out / (name + '.log')).open('w', encoding='utf-8')
        handles.append(handle)
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, startupinfo=startup)
        processes.append(process)
        return process

    def start_brain(name):
        command = [sys.executable, '-u', str(HERE / 'main.py'), '--brain', str(out / 'brain.yaml'),
                   '--config', str(shared), '--delay', str(getattr(args, 'delay', 3)),
                   '--record-dir', str(out / name), '--tag', name]
        if not args.torch:
            command.append('--no-torch')
        if not args.rock_weights:
            command.append('--no-yolo')
        return launch(name, command)

    stopped, restarted, stop_time = False, False, None
    try:
        brain = start_brain('brain-first')
        ready_deadline = time.monotonic() + 60
        while 'BRAIN up:' not in (out / 'brain-first.log').read_text(encoding='utf-8'):
            if brain.poll() is not None or time.monotonic() > ready_deadline:
                raise RuntimeError('BRAIN failed to start; inspect brain-first.log')
            time.sleep(.1)
        godot = launch('godot', [str(args.godot.resolve()), '--path', str(sim), '--resolution', '960x540',
                               '--', '--brain=ws://127.0.0.1:' + str(args.port),
                               '--config=' + str(shared), '--record=' + out.name,
                               '--lowfx', '--exitafter=' + str(args.seconds)])
        print('Evidence:', out, flush=True)
        deadline = time.monotonic() + args.seconds + 90
        while godot.poll() is None and time.monotonic() < deadline:
            observed = rows(run_dir / 'observations.jsonl')
            t = observed[-1]['sim_time'] if observed else 0
            if t >= 12 and not stopped and not args.smoke:
                brain.terminate(); brain.wait(timeout=10)
                stopped, stop_time = True, t
                print('Stopped BRAIN at physics second', t, flush=True)
            elif stopped and not restarted and t >= stop_time + 6:
                brain = start_brain('brain-reconnected')
                restarted = True
                print('Restarted BRAIN at physics second', t, flush=True)
            time.sleep(.2)
        if godot.poll() is None:
            raise RuntimeError('Godot did not finish before the integration timeout')
        if godot.returncode:
            raise RuntimeError('Godot exited with an error; inspect godot.log')
        drain = getattr(args, 'drain_seconds', 0)
        if drain:
            print('Draining delayed telemetry for', drain, 'real seconds', flush=True)
            until = time.monotonic() + drain
            while time.monotonic() < until:
                if brain.poll() is not None:
                    raise RuntimeError('BRAIN exited before delayed telemetry drained')
                time.sleep(.2)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        for handle in handles:
            handle.close()

    observed, actions = rows(run_dir / 'observations.jsonl'), rows(run_dir / 'actions.jsonl')
    assert observed and len(actions) >= 5, 'missing observations/actions'
    assert args.smoke or restarted, 'missing reconnect'
    for original in observed:
        observation = dict(original)
        ref = observation.pop('_frame_ref'); observation.pop('_bytes')
        validate_observation(observation)
        frame = cv2.imread(str(run_dir / 'frames' / (ref + '.jpg')))
        assert frame is not None and frame.shape[:2] == (480, 640)
    for action in actions:
        validate_action(action)
    for a, b in zip(observed, observed[1:]):
        assert b['seq'] > a['seq'] and b['sim_time'] > a['sim_time']
        assert b['budget']['remaining'] <= a['budget']['remaining']
    movement = None
    if not args.smoke:
        stopped_obs = [o for o in observed if stop_time + 3 <= o['sim_time'] <= stop_time + 5.5]
        assert len(stopped_obs) >= 5
        movement = max(math.hypot(o['pose']['x'] - stopped_obs[0]['pose']['x'],
                                  o['pose']['y'] - stopped_obs[0]['pose']['y']) for o in stopped_obs)
        assert movement <= .03, f'rover moved {movement} m after watchdog deadline'
        assert any(a['sim_time'] > stop_time + 10 for a in actions), 'no actions after reconnect'
        assert observed[-1]['mission']['confirmed_markers'], 'no marker reached and confirmed'
    backend = 'aruco+' + ('yolo' if args.rock_weights else 'blobs') + ('+resnet18' if args.torch else '+hist')
    assert 'perception backend: ' + backend in (out / 'brain-first.log').read_text(encoding='utf-8')
    report = {'observations': len(observed), 'actions': len(actions), 'sim_recording': str(run_dir),
              'confirmed': observed[-1]['mission']['confirmed_markers'], 'stop_time': stop_time,
              'stationary_window_movement_m': movement, 'reconnected': restarted,
              'encoder': 'resnet18' if args.torch else 'hist', 'backend': backend,
              'mode': 'perception smoke' if args.smoke else 'marker and reconnect acceptance',
              'detector': 'trained rock' if args.rock_weights else 'classical fallback',
              'final_budget_wh': observed[-1]['budget']['remaining']}
    (out / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--godot', required=True, type=Path)
    parser.add_argument('--sim', required=True, type=Path)
    parser.add_argument('--config', type=Path, default=HERE / 'config.yaml')
    parser.add_argument('--delay', type=float, default=3)
    parser.add_argument('--drain-seconds', type=float, default=0)
    parser.add_argument('--port', type=int, default=19765)
    parser.add_argument('--seconds', type=int, default=105)
    parser.add_argument('--torch', action='store_true')
    parser.add_argument('--rock-weights', type=Path, help='Validate candidate weights without installing them')
    parser.add_argument('--smoke', action='store_true', help='Check live perception/actions only; omit marker/reconnect assertions')
    parser.add_argument('--warmup-seconds', type=float, help='Test a scene warm-up profile without changing defaults')
    args = parser.parse_args()
    if args.seconds < (15 if args.smoke else 30):
        parser.error('allow at least 15 seconds for smoke or 30 for full acceptance')
    if args.warmup_seconds is not None and args.warmup_seconds < 0:
        parser.error('warm-up seconds cannot be negative')
    run(args)
