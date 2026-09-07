"""Acceptance-checker rejection tests; synthetic fixtures do not prove SIM behavior."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from check_demo_pair import compare_configs, check_stay, load_run
from check_phase1 import CFG, BCFG, result, marker, rock
from contract import ContractViolation
from policy import BrainState, decide


class PairChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.cfg = dict(CFG, gamma=5., budget_start_wh=210.)
        self.observations, self.actions = [], []
        for t, novelty in ((.2, 0.), (20.2, .85)):
            res = result([marker(), rock(novelty=novelty)], budget=210., t=t)
            res.header['camera']['hfov_deg'] = self.cfg['camera_hfov_deg']
            action, _ = decide(res, BrainState(gamma=5.), self.cfg, BCFG['policy'])
            self.observations.append(res.header)
            self.actions.append(action)

    def save(self):
        for name, rows in (('observations', self.observations), ('actions', self.actions)):
            (self.run / (name + '.jsonl')).write_text('\n'.join(map(json.dumps, rows)), encoding='utf-8')

    def test_valid_controlled_inputs(self):
        self.save()
        obs, actions = load_run(self.run, self.cfg, 15.)
        self.assertEqual(len(obs), 2)
        self.assertEqual(check_stay(actions)['target']['kind'], 'marker')
        changes = compare_configs(self.cfg, dict(self.cfg, budget_start_wh=1000., gamma=2.))
        self.assertEqual(set(changes), {'budget_start_wh', 'gamma'})

    def test_reject_uncontrolled_world_or_equal_config(self):
        for cfg in (self.cfg, dict(self.cfg, world_seed=123), dict(self.cfg, camera_hfov_deg=70)):
            with self.assertRaises(AssertionError):
                compare_configs(self.cfg, cfg)

    def test_reject_stay_without_strong_novelty(self):
        for c in self.actions[-1]['audit']['candidates']:
            if c['stream'] == 'curiosity':
                c['n'] = .44
        with self.assertRaisesRegex(AssertionError, 'no strong novelty'):
            check_stay(self.actions)

    def test_reject_stay_with_rock_target(self):
        self.actions[-1]['target']['kind'] = 'rock'
        with self.assertRaisesRegex(AssertionError, 'chose a rock'):
            check_stay(self.actions)

    def test_reject_incorrect_profile_and_missing_observation(self):
        self.save()
        for cfg in (dict(self.cfg, gamma=2.), dict(self.cfg, budget_start_wh=1000.)):
            with self.assertRaises(AssertionError):
                load_run(self.run, cfg, 15.)
        self.actions[-1]['in_reply_to_seq'] = 9999
        self.save()
        with self.assertRaisesRegex(AssertionError, 'absent observation'):
            load_run(self.run, self.cfg, 15.)

    def test_reject_hidden_ground_truth_in_record(self):
        self.observations[-1]['_objects'] = ['unusual-rock']
        self.save()
        with self.assertRaises(ContractViolation):
            load_run(self.run, self.cfg, 15.)

    def test_reject_arithmetic_corruption(self):
        self.actions[-1]['audit']['w_curiosity'] = .99
        self.save()
        with self.assertRaises(ContractViolation):
            load_run(self.run, self.cfg, 15.)

    def test_reject_truncated_record(self):
        self.save()
        with (self.run / 'actions.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('\n{"type":')
        with self.assertRaises(json.JSONDecodeError):
            load_run(self.run, self.cfg, 15.)


if __name__ == '__main__':
    unittest.main(verbosity=2)
