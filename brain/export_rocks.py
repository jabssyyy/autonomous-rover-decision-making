"""Render independent seeded Godot layouts into the grouped rock export format."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

import yaml

from rock_dataset import inspect_export


def run(args):
    output = args.output.resolve()
    if output.exists():
        raise ValueError('use a fresh output directory')
    output.mkdir(parents=True)
    cfg = yaml.safe_load((Path(__file__).parent / 'config.yaml').read_text(encoding='utf-8-sig'))
    startup = None
    if hasattr(subprocess, 'STARTUPINFO'):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    records = []
    for i in range(args.groups):
        seed = args.seed + i
        group = f'layout-{seed}'
        cfg['world_seed'] = seed
        config = output / (group + '.yaml')
        config.write_text(yaml.safe_dump(cfg), encoding='utf-8')
        name = output.name + '-' + group
        with (output / (group + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run([str(args.godot.resolve()), '--path', str(args.sim.resolve()),
                            '--resolution', '640x480', '--', '--lowfx', '--label=' + str(args.frames),
                            '--label-name=' + name, '--config=' + str(config)],
                           stdout=log, stderr=subprocess.STDOUT, startupinfo=startup, timeout=180, check=True)
        source = args.sim.resolve().parent / 'runs' / name
        rows = inspect_export(source / 'export.jsonl')
        if len(rows) != args.frames:
            raise ValueError(f'{group}: incomplete export')
        shutil.copytree(source, output / group)
        records.extend({'image': group + '/' + r['image'], 'label': group + '/' + r['label'], 'group': group}
                       for r in rows)
        print(f'{group}: {len(rows)} frames, {sum(r["boxes"] for r in rows)} boxes', flush=True)
    (output / 'export.jsonl').write_text('\n'.join(map(json.dumps, records)), encoding='utf-8')
    inspect_export(output / 'export.jsonl')
    print('Validated export:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--godot', required=True, type=Path)
    parser.add_argument('--sim', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--groups', type=int, default=10)
    parser.add_argument('--frames', type=int, default=150)
    parser.add_argument('--seed', type=int, default=20261001)
    args = parser.parse_args()
    if args.groups < 1 or args.frames < 1:
        parser.error('groups and frames must be positive')
    run(args)
