"""Audit recorded Godot stay/deviate runs; this does not certify a complete mission."""
import argparse
import hashlib
import json
from pathlib import Path

import yaml

from check_discovery_run import check as check_discovery
from contract import validate_action, validate_observation


def compare_configs(stay, deviate):
    differences = {k for k in set(stay) | set(deviate) if stay.get(k) != deviate.get(k)}
    assert differences, 'demo configurations must differ'
    assert differences <= {'budget_start_wh', 'gamma'}, f'uncontrolled config differences: {differences}'
    return {k: {'stay': stay.get(k), 'deviate': deviate.get(k)} for k in sorted(differences)}


def load_run(run, cfg, warmup):
    run = Path(run)
    observations = [json.loads(s) for s in (run / 'observations.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    actions = [json.loads(s) for s in (run / 'actions.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert observations and actions, 'empty recording'
    previous_seq, previous_time = -1, -1.
    by_seq = {}
    for row in observations:
        # Only the two known recorder fields may sit outside the wire contract.
        validate_observation({k: v for k, v in row.items() if k not in {'_bytes', '_frame_ref'}})
        assert row['seq'] > previous_seq and row['sim_time'] > previous_time, 'unordered observations'
        previous_seq, previous_time = row['seq'], row['sim_time']
        by_seq[row['seq']] = row
    first = observations[0]
    assert first['sim_time'] <= 1., 'recording does not include the scene start'
    assert abs(first['budget']['remaining'] - cfg['budget_start_wh']) <= .05, 'starting budget does not match profile'
    assert first['budget']['capacity'] == cfg['budget_capacity_wh'], 'capacity does not match profile'
    assert first['camera']['w'] == cfg['camera_w'] and first['camera']['h'] == cfg['camera_h']
    assert abs(first['camera']['hfov_deg'] - cfg['camera_hfov_deg']) <= .01
    previous_time = -1.
    for a in actions:
        validate_action(a)
        assert a['audit'].get('version') == 2, 'expected current arithmetic audit version 2'
        assert a['sim_time'] > previous_time, 'unordered actions'
        previous_time = a['sim_time']
        assert a['audit']['gamma'] == cfg['gamma'], 'recorded gamma does not match profile'
        obs = by_seq.get(a['in_reply_to_seq'])
        assert obs is not None, 'action refers to an absent observation'
        assert abs(obs['sim_time'] - a['sim_time']) <= .01, 'action clock differs from its observation'
        if a['sim_time'] < warmup:
            assert all(c.get('n', 0) == 0 for c in a['audit']['candidates']), 'novelty active before warm-up'
    return observations, actions


def check_stay(actions, warmup=15., threshold=.45):
    assert all(a['decision'] != 'investigate' and
               (not a['target'] or a['target']['kind'] == 'marker') for a in actions), 'stay run chose a rock or investigated'
    examples = [a for a in actions if a['sim_time'] >= warmup and
                a['decision'] == 'drive_to_target' and a['target']['kind'] == 'marker' and
                any(c.get('n', 0) >= threshold for c in a['audit']['candidates'])]
    assert examples, 'no strong novelty observed while staying on mission after warm-up'
    return max(examples, key=lambda a: max(c.get('n', 0) for c in a['audit']['candidates']))


def audit_example(a):
    audit = a['audit']
    return {'sim_time': a['sim_time'], 'decision': a['decision'], 'target': a['target'],
            'budget': audit['budget'], 'slack': audit['slack'], 'gamma': audit['gamma'],
            'w_curiosity': audit['w_curiosity'], 'gate': audit['gate'],
            'mission_candidates': [c for c in audit['candidates'] if c['stream'] == 'mission'],
            'strongest_novelty_candidate': max((c for c in audit['candidates'] if c['stream'] == 'curiosity'),
                                                key=lambda c: c['n'], default=None),
            'selected_candidate': next((c for c in audit['candidates'] if c['id'] == audit['chosen']), None),
            'text': audit['text']}


def summarize(run, observations, actions):
    first, last = observations[0], observations[-1]
    return {'run': str(Path(run).resolve()), 'observations': len(observations), 'actions': len(actions),
            'start_s': first['sim_time'], 'end_s': last['sim_time'],
            'budget_start_wh': first['budget']['remaining'], 'budget_end_wh': last['budget']['remaining'],
            'budget_spent_wh': round(first['budget']['remaining'] - last['budget']['remaining'], 6),
            'confirmed_markers': last['mission']['confirmed_markers'],
            'max_novelty': max((c.get('n', 0) for a in actions for c in a['audit']['candidates']), default=0),
            'record_sha256': {name: hashlib.sha256((Path(run) / name).read_bytes()).hexdigest()
                              for name in ('observations.jsonl', 'actions.jsonl')}}


def check(stay_run, deviate_run, stay_config, deviate_config, warmup=15., threshold=.45):
    configs = [yaml.safe_load(Path(p).read_text(encoding='utf-8-sig')) for p in (stay_config, deviate_config)]
    differences = compare_configs(*configs)
    stay_obs, stay_actions = load_run(stay_run, configs[0], warmup)
    dev_obs, dev_actions = load_run(deviate_run, configs[1], warmup)
    for key in ('pose', 'camera', 'mission'):
        assert stay_obs[0][key] == dev_obs[0][key], f'different starting {key}'
    stay_example = check_stay(stay_actions, warmup, threshold)
    discovery = check_discovery(deviate_run, warmup)
    dev_example = next(a for a in dev_actions if a['decision'] == 'investigate')
    stay = summarize(stay_run, stay_obs, stay_actions)
    stay['example'] = audit_example(stay_example)
    deviate = summarize(deviate_run, dev_obs, dev_actions)
    deviate.update(example=audit_example(dev_example), discovery=discovery)
    choices = [a for a in dev_actions if a['target'] and a['target']['kind'] in ('rock', 'anomaly')
               and any(c['stream'] == 'mission' for c in a['audit']['candidates'])]
    deviate['detour_choice_with_mission_visible'] = audit_example(choices[0]) if choices else None
    return {'status': 'passed', 'config_differences': differences, 'warmup_s': warmup,
            'strong_novelty_threshold': threshold, 'stay': stay, 'deviate': deviate,
            'config_sha256': {name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                              for name, p in zip(('stay', 'deviate'), (stay_config, deviate_config))},
            'limitations': ['Same configured world seed and initial pose/camera/mission; paths and later frames diverge.',
                            'These are two live behavior demonstrations, not a deterministic causal benchmark.',
                            'Appearance novelty does not establish scientific value or ground-truth object identity.',
                            'No claim that all assigned markers or the complete mission were completed.',
                            'Recorded budget difference includes differing paths, dwell, and recording durations.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stay_run', type=Path)
    p.add_argument('deviate_run', type=Path)
    p.add_argument('--stay-config', type=Path, required=True)
    p.add_argument('--deviate-config', type=Path, required=True)
    p.add_argument('--warmup', type=float, default=15.)
    p.add_argument('--threshold', type=float, default=.45)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    assert args.warmup >= 0 and 0 < args.threshold <= 1
    result = check(args.stay_run, args.deviate_run, args.stay_config, args.deviate_config, args.warmup, args.threshold)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
