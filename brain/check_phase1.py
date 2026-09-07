"""Controlled acceptance cases for Phase 1; no Godot or learned weights needed."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
import yaml

from contract import EXAMPLE_OBSERVATION, ContractViolation, validate_action, validate_telemetry
from novelty import NoveltyMemory
from perception import Detection, PerceptionResult
from perception import Observation, Perceiver
from policy import BrainState, decide, cancel_investigation

HERE = Path(__file__).resolve().parent
CFG = yaml.safe_load((HERE / 'config.yaml').read_text(encoding='utf-8'))
BCFG = yaml.safe_load((HERE / 'brain.yaml').read_text(encoding='utf-8'))


def marker(id='M01', distance=30, confidence=.6, bearing=0):
    return Detection(id, 'marker', id, confidence, (0, 0, 10, 10), bearing, distance)


def rock(id='A01', distance=6, confidence=.8, novelty=.85, bearing=0):
    return Detection(id, 'rock', 'rock', confidence, (0, 0, 10, 10), bearing, distance, novelty)


def result(dets=None, budget=400, t=0, assigned=None, confirmed=None, hazard=99, x=0):
    hdr = copy.deepcopy(EXAMPLE_OBSERVATION)
    hdr.update(seq=int(t * 5), sim_time=float(t))
    hdr['pose'] = {'x': x, 'y': 0., 'heading_deg': 0.}
    hdr['budget']['remaining'] = budget
    hdr['mission'] = {'assigned_markers': ['M01', 'M02', 'M03'] if assigned is None else assigned,
                      'confirmed_markers': confirmed or []}
    hdr['hazard']['range_m'] = hazard
    return PerceptionResult(hdr['seq'], t, hdr, 0, dets or [], b'', [])


class PolicyChecks(unittest.TestCase):
    def setUp(self):
        self.cfg, self.pol = copy.deepcopy(CFG), copy.deepcopy(BCFG['policy'])
        self.st = BrainState(gamma=1)

    def run_case(self, res):
        action, extras = decide(res, self.st, self.cfg, self.pol)
        validate_action(action)
        return action, extras

    def test_same_candidates_stay_and_deviate(self):
        for budget, gamma, expected in [(210, 2, 'M01'), (400, 1, 'A01')]:
            with self.subTest(budget=budget):
                self.st = BrainState(gamma=gamma)
                a, _ = self.run_case(result([marker(), rock()], budget=budget))
                self.assertEqual(a['audit']['chosen'], expected)
                self.assertAlmostEqual(a['audit']['budget']['required_for_mission'], 179)

    def test_confidence_jitter_both_branches(self):
        for mc in (.45, .55, .65, .75):
            for rc in (.60, .70, .80, .90):
                for budget, gamma, expected in [(210, 2, 'M01'), (400, 1, 'A01')]:
                    self.st = BrainState(gamma=gamma)
                    a, _ = self.run_case(result([marker(confidence=mc), rock(confidence=rc)], budget=budget))
                    self.assertEqual(a['audit']['chosen'], expected, (mc, rc, budget))

    def test_unaffordable_marker_fallback_holds(self):
        a, _ = self.run_case(result([marker()], budget=25, assigned=['M01']))
        self.assertEqual(a['decision'], 'hold')
        self.assertIsNone(a['target'])

    def test_rejected_curiosity_uses_checked_mission_fallback(self):
        self.pol['k_curiosity'] = 1000
        a, _ = self.run_case(result([marker(), rock(bearing=180)], budget=50, assigned=['M01']))
        self.assertEqual(a['audit']['chosen'], 'M01')
        self.assertFalse(a['audit']['candidates'][0]['eligible'])
        self.assertEqual(a['audit']['gate']['cost_wh'], 33)
        self.assertEqual(a['audit']['gate']['reserve_wh'], 17)

    def test_no_mission_still_requires_affordability(self):
        a, _ = self.run_case(result([rock(distance=0)], budget=4, assigned=[]))
        self.assertEqual(a['decision'], 'hold')
        self.assertIsNone(a['audit']['gate']['post_action_reserve'])
        a, _ = self.run_case(result([rock(distance=0)], budget=5, assigned=[], t=1))
        self.assertEqual(a['decision'], 'investigate')
        self.assertEqual(a['audit']['gate']['reserve_wh'], 0)

    def test_zero_budget_zero_gamma_and_negative_gamma(self):
        for gamma in (0, -5, 10):
            self.st = BrainState(gamma=gamma)
            a, _ = self.run_case(result([rock()], budget=0))
            self.assertEqual(a['decision'], 'hold')
            self.assertEqual(a['audit']['w_curiosity'], 0)
            self.assertTrue(.1 <= a['audit']['gamma'] <= 5)

    def test_hysteresis_ratio_and_lock(self):
        a, _ = self.run_case(result([marker(confidence=.7), marker('M02', confidence=.6)]))
        self.assertEqual(a['audit']['chosen'], 'M01')
        a, _ = self.run_case(result([marker(confidence=.65), marker('M02', confidence=.7)], t=1))
        self.assertEqual(a['audit']['chosen'], 'M01')
        a, _ = self.run_case(result([marker(confidence=.4), marker('M02', confidence=1)], t=2))
        self.assertEqual(a['audit']['chosen'], 'M01')
        a, _ = self.run_case(result([marker(confidence=.4), marker('M02', confidence=1)], t=6))
        self.assertEqual(a['audit']['chosen'], 'M02')

    def test_new_candidate_exempts_lock_but_not_ratio(self):
        self.run_case(result([marker()]))
        a, _ = self.run_case(result([marker(), rock(novelty=.01)], t=1))
        self.assertEqual(a['audit']['chosen'], 'M01')
        a, _ = self.run_case(result([marker(), rock(id='A02')], t=2))
        self.assertEqual(a['audit']['chosen'], 'A02')

    def test_active_dwell_completion_resume_and_visited_position(self):
        a, e = self.run_case(result([marker(), rock(distance=2)]))
        self.assertEqual(a['decision'], 'investigate')
        self.assertNotIn('commit_embedding', e)
        a, _ = self.run_case(result([marker()], t=1))
        self.assertEqual(a['target']['label'], 'A01')
        self.assertEqual(a['audit']['chosen'], 'A01')
        a, e = self.run_case(result([marker(), rock(id='A99', distance=2)], t=5))
        self.assertEqual(e['commit_embedding'], 'A01')
        self.assertEqual(a['target']['label'], 'M01')
        self.assertNotIn('A99', [c['id'] for c in a['audit']['candidates']])

    def test_active_dwell_rechecks_reserve(self):
        self.run_case(result([marker(), rock(distance=2)]))
        a, e = self.run_case(result([marker(), rock(distance=2)], budget=10, t=1))
        self.assertEqual(a['decision'], 'hold')
        self.assertIsNone(self.st.investigating)
        self.assertNotIn('commit_embedding', e)

    def test_abort_does_not_complete_or_immediately_restart(self):
        self.run_case(result([marker(), rock(distance=2)]))
        cancel_investigation(self.st, 'Operator abort')
        a, e = self.run_case(result([marker(), rock(distance=2)], t=1))
        self.assertEqual(a['audit']['chosen'], 'M01')
        self.assertFalse(self.st.investigated)
        self.assertNotIn('commit_embedding', e)

    def test_deferred_reentry_and_expiry(self):
        self.run_case(result([marker(), rock()], budget=210))
        a, _ = self.run_case(result([marker()], budget=400, t=6))
        self.assertEqual(a['audit']['chosen'], 'A01')
        a, _ = self.run_case(result([], budget=400, t=130))
        self.assertNotIn('A01', [c['id'] for c in a['audit']['candidates']])

    def test_remembered_nearby_target_needs_reacquisition(self):
        self.run_case(result([rock()], assigned=[]))
        a, _ = self.run_case(result([], assigned=[], t=1, x=4))
        self.assertEqual(a['decision'], 'survey')
        self.assertIsNone(a['target'])

    def test_hazard_and_halt_override_choice(self):
        for halt, hazard in [(False, .1), (True, 99)]:
            self.st = BrainState(halted=halt)
            a, _ = self.run_case(result([marker()], hazard=hazard))
            self.assertEqual(a['decision'], 'hold')
            self.assertIsNone(a['audit']['chosen'])

    def test_empty_override_and_report_cycle(self):
        self.st.assigned_override = []
        a, _ = self.run_case(result([marker()]))
        self.assertEqual(a['decision'], 'survey')
        a, _ = self.run_case(result([marker()], t=7200))
        self.assertEqual(a['decision'], 'report')
        a, _ = self.run_case(result([marker()], t=7201))
        self.assertEqual(a['decision'], 'hold')

    def test_zero_value_rocks_do_not_prevent_survey(self):
        a, _ = self.run_case(result([rock(novelty=0)]))
        self.assertEqual(a['decision'], 'survey')

    def test_audit_tampering_rejected(self):
        a, _ = self.run_case(result([marker(), rock()]))
        for field in ('cost_wh', 'reserve_wh', 'required_for_mission_after'):
            bad = copy.deepcopy(a)
            bad['audit']['gate'][field] += 1
            with self.assertRaises(ContractViolation):
                validate_action(bad)
        bad = copy.deepcopy(a)
        bad['target']['label'] = 'M99'
        with self.assertRaises(ContractViolation):
            validate_action(bad)


class MemoryChecks(unittest.TestCase):
    def test_warmup_pending_protection_completion_and_habituation(self):
        m = NoveltyMemory(cap=8, warmup_s=2, commit_delay_s=3)
        common, unusual = np.array([1., 0, 0]), np.array([0, 1., 0])
        m.advance(0)
        self.assertEqual(m.novelty(unusual), 0)
        m.observe('common', common)
        m.advance(2)
        before = m.novelty(unusual)
        self.assertGreater(before, .99)
        m.observe('new', unusual)
        m.advance(4)
        self.assertEqual(m.novelty(unusual), before)
        m.protect('new')
        m.advance(20)
        self.assertEqual(m.novelty(unusual), before)
        m.complete('new')
        self.assertAlmostEqual(m.novelty(unusual), 0)
        self.assertGreaterEqual(m.tau, .1)

    def test_pending_deadline_does_not_reset_on_repeated_frames(self):
        m = NoveltyMemory(warmup_s=0, commit_delay_s=3)
        v = np.array([1., 0])
        m.advance(0); m.observe('a', v)
        m.advance(2); m.observe('a', v)
        self.assertEqual(len(m), 0)
        m.advance(3)
        self.assertEqual(len(m), 1)

    def test_memory_pending_bounds_and_bad_vector(self):
        m = NoveltyMemory(cap=3, warmup_s=0)
        m.advance(0)
        for i in range(10):
            m.observe(str(i), np.array([1., i + 1]))
        self.assertEqual(len(m.pending), 3)
        m.advance(31)
        self.assertLessEqual(len(m), 3)
        with self.assertRaises(ValueError):
            m.novelty(np.array([float('nan'), 0]))


class PerceptionChecks(unittest.TestCase):
    def test_marker_proxy_rises_with_hits_and_falls_with_misses(self):
        import cv2
        p = Perceiver(copy.deepcopy(BCFG['perception']), use_yolo=False, use_torch=False)
        image = np.full((480, 640, 3), 255, np.uint8)
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        tag = cv2.aruco.generateImageMarker(dictionary, 2, 100)
        image[100:200, 270:370] = cv2.cvtColor(tag, cv2.COLOR_GRAY2BGR)
        _, encoded = cv2.imencode('.jpg', image)
        _, blank = cv2.imencode('.jpg', np.full_like(image, 255))
        confidences = []
        for i in range(9):
            header = result(t=i).header
            seen = p.perceive(Observation(header, blank.tobytes() if 5 <= i < 8 else encoded.tobytes(), 0))
            if seen.detections:
                confidences.append(seen.detections[0].conf)
        self.assertLess(confidences[0], confidences[4])
        self.assertEqual(confidences[4], 1)
        self.assertLess(confidences[5], confidences[4])
        header['camera']['w'] = 10
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            p.perceive(Observation(header, encoded.tobytes(), 0))


class RuntimeChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from main import Brain
        cfg, bcfg = copy.deepcopy(CFG), copy.deepcopy(BCFG)
        bcfg['ports'].update(host='127.0.0.1', sim=0, panel=0)
        args = SimpleNamespace(no_yolo=True, no_torch=True, delay=.02,
                               no_record=True, lenient=False)
        self.brain = Brain(cfg, bcfg, args)

    def tearDown(self):
        self.brain.pool.shutdown(wait=True, cancel_futures=True)

    async def test_uplink_gamma_clamped_and_empty_assignment_retained(self):
        await self.brain.apply_uplink({'command': 'set_gamma', 'payload': {'gamma': 0}, 'issued_at': 0})
        self.assertEqual(self.brain.st.gamma, .1)
        await self.brain.apply_uplink({'command': 'reassign_markers', 'payload': {'assigned_markers': []}, 'issued_at': 0})
        self.assertEqual(self.brain.st.assigned_override, [])

    async def test_duplicate_sim_rejected_without_replacing_session(self):
        class Peer:
            async def close(self, **kwargs):
                self.closed = kwargs
        original, newcomer = object(), Peer()
        self.brain.sim_ws = original
        await self.brain.sim_handler(newcomer)
        self.assertEqual(newcomer.closed['code'], 1008)
        self.assertIs(self.brain.sim_ws, original)

    async def test_missing_jpeg_is_not_paired_with_next_header(self):
        class Peer:
            remote_address = ('test', 0)
            def __aiter__(self):
                async def messages():
                    yield json.dumps(EXAMPLE_OBSERVATION)
                    yield json.dumps(EXAMPLE_OBSERVATION)
                return messages()
        with self.assertRaises(ContractViolation):
            await self.brain.sim_handler(Peer())
        self.assertTrue(self.brain.stop.is_set())
        self.assertIsNone(self.brain.sim_ws)

    async def test_worker_failure_is_propagated(self):
        async def fail():
            raise RuntimeError('test worker failure')
        self.brain.perception_worker = fail
        with self.assertRaisesRegex(RuntimeError, 'test worker failure'):
            await asyncio.wait_for(self.brain.serve(), 3)


class SimulatorChecks(unittest.TestCase):
    def test_watchdog_stops_motion_and_dwell(self):
        from stub_sim import World
        world = World(950, ['M01'])
        world.speed, world.dwell_left = .6, 5
        before = (world.x, world.y)
        with patch('stub_sim.time.monotonic', return_value=world.last_action_time + 3):
            world.step(1)
        self.assertEqual((world.x, world.y), before)
        self.assertEqual(world.dwell_left, 0)

    def test_marker_confirmation_waits_and_spends_dwell(self):
        from stub_sim import World
        world = World(950, ['M01'])
        world.x, world.y = world.markers['M01']
        world.committed, world.decision, world.speed = 'M01', 'drive_to_target', .6
        world.step(1)
        self.assertEqual(world.confirmed, [])
        world.step(1); world.step(1)
        self.assertEqual(world.confirmed, ['M01'])
        self.assertAlmostEqual(world.budget, 950 - 3 - .03)


if __name__ == '__main__':
    unittest.main(verbosity=2)
