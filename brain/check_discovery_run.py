"""Check a recorded real-SIM warm-up, discovery dwell and mission-resumption sequence."""
import argparse
import json
import math
from pathlib import Path

from contract import validate_action, validate_observation


def check(run, warmup=15.):
    run = Path(run)
    observations = [json.loads(s) for s in (run / 'observations.jsonl').read_text().splitlines()]
    actions = [json.loads(s) for s in (run / 'actions.jsonl').read_text().splitlines()]
    for row in observations:
        validate_observation({k: v for k, v in row.items() if not k.startswith('_')})
    for a in actions:
        validate_action(a)
    for a in actions:
        if a['sim_time'] < warmup:
            assert all(c.get('n', 0) == 0 for c in a['audit']['candidates']), 'novelty during warm-up'
    dwell = [a for a in actions if a['decision'] == 'investigate']
    assert dwell, 'no investigation observed'
    first = dwell[0]
    label = first['target']['label']
    assert first['sim_time'] >= warmup
    complete = next(a for a in actions if a['sim_time'] > first['sim_time'] and
                    f'Investigation of {label} complete' in a['audit']['text'])
    assert complete['sim_time'] - first['sim_time'] >= 5., 'investigation ended early'
    stable = [o for o in observations if first['sim_time'] + .5 <= o['sim_time'] <= complete['sim_time'] - .2]
    assert len(stable) >= 10
    motion = max(math.hypot(o['pose']['x'] - stable[0]['pose']['x'],
                            o['pose']['y'] - stable[0]['pose']['y']) for o in stable)
    assert motion <= .05, 'rover moved during investigation dwell'
    resumed = next(a for a in actions if a['sim_time'] > complete['sim_time'] and
                   a['decision'] == 'drive_to_target' and a['target']['kind'] == 'marker')
    return {'observations': len(observations), 'actions': len(actions), 'warmup_s': warmup,
            'investigated': label, 'investigate_start_s': first['sim_time'],
            'complete_s': complete['sim_time'], 'dwell_motion_m': motion,
            'mission_resumed_s': resumed['sim_time'], 'mission_target': resumed['target']['label'],
            'limitation': 'Appearance novelty only; no ground-truth object identity or scientific value claim'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    p.add_argument('--warmup', type=float, default=15.)
    args = p.parse_args()
    print(json.dumps(check(args.run, args.warmup), indent=2))
