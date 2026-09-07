"""Record and verify Phase 4 using one BRAIN/SIM build and two shared configs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from check_godot import run
from contract import validate_telemetry

HERE = Path(__file__).resolve().parent


def hashes(sim):
    files = list(HERE.glob('*.py')) + [HERE / 'brain.yaml', HERE / 'weights/rock.pt']
    files += list(sim.rglob('*.gd')) + list(sim.rglob('*.tscn')) + [sim / 'project.godot']
    return {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def check_delivery(evidence):
    folders = list((evidence / 'brain-first').glob('*'))
    assert len(folders) == 1, 'expected one BRAIN recording'
    folder = folders[0]
    actions = [json.loads(s) for s in (folder / 'actions.jsonl').read_text().splitlines()]
    delivered = [json.loads(s) for s in (folder / 'telemetry_delivered.jsonl').read_text().splitlines()]
    assert len(delivered) == len(actions), 'delayed telemetry tail is incomplete'
    for row in delivered:
        validate_telemetry({k: v for k, v in row.items() if not k.startswith('_')})
        assert row['clock']['delay_real_s'] >= 59.99, 'downlink delivered early'
        assert all((folder / 'frames' / (name + '.jpg')).is_file() for name in row['_blobs'])
    return {'brain_recording': str(folder), 'delivered': len(delivered), 'delay_s': 60}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--godot', required=True, type=Path)
    parser.add_argument('--sim', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--seconds', type=int, default=90)
    args = parser.parse_args()
    if args.seconds < 75:
        parser.error('allow at least 75 seconds for the discovery and mission sequence')
    args.out.mkdir(parents=True, exist_ok=False)
    before = hashes(args.sim.resolve())
    evidence = {}
    for profile in ('stay', 'deviate'):
        config = HERE / 'demo' / (profile + '.yaml')
        # Snapshot configs so the recorded run never depends on later preset edits.
        snapshot = args.out.resolve() / config.name
        snapshot.write_text(config.read_text(encoding='utf-8'), encoding='utf-8')
        result = run(SimpleNamespace(sim=args.sim, godot=args.godot, port=19765,
            config=snapshot, delay=60, drain_seconds=62, seconds=args.seconds,
            rock_weights=HERE / 'weights/rock.pt', torch=True, smoke=True, warmup_seconds=None))
        assert hashes(args.sim.resolve()) == before, 'code/model changed between demo runs'
        report = json.loads((result / 'result.json').read_text())
        evidence[profile] = {'evidence': str(result), **report, **check_delivery(result)}
        subprocess.run([sys.executable, str(HERE / 'render_demo_video.py'), report['sim_recording'],
            '--out', str(args.out / (profile + '.mp4')), '--title', profile.upper() + ' | recorded BRAIN decisions'], check=True)
    subprocess.run([sys.executable, str(HERE / 'check_demo_pair.py'),
        evidence['stay']['sim_recording'], evidence['deviate']['sim_recording'],
        '--stay-config', str(args.out / 'stay.yaml'), '--deviate-config', str(args.out / 'deviate.yaml'),
        '--output', str(args.out / 'acceptance.json')], check=True)
    (args.out / 'manifest.json').write_text(json.dumps({'runs': evidence, 'code_and_model_sha256': before}, indent=2), encoding='utf-8')
    print('Verified pair:', args.out.resolve())


if __name__ == '__main__':
    main()
