"""Phase 3 offline novelty diagnostics tests; fixtures do not measure scene accuracy."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from check_novelty_dataset import inspect, evaluate, run


class NoveltyDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'crops.jsonl'
        self.rows = []
        for i, role in enumerate(('memory', 'memory', 'familiar', 'novel')):
            image = f'{i}.png'
            rng = np.random.default_rng(i)
            cv2.imwrite(str(self.root / image), rng.integers(0, 256, (24, 24, 3), dtype=np.uint8))
            self.rows.append(dict(image=image, group=f'capture-{i}', role=role))
        self.save()

    def save(self):
        self.manifest.write_text('\n'.join(map(json.dumps, self.rows)), encoding='utf-8')

    def test_hist_report_and_no_overwrite(self):
        output = self.root / 'report.json'
        report = run(self.manifest, output, 'hist')
        self.assertEqual(report['memory_size'], 2)
        self.assertEqual(len(report['scores']), 2)
        self.assertTrue(0 <= report['novel_over_familiar_rank_auc'] <= 1)
        self.assertEqual(json.loads(output.read_text())['inputs'][0]['sha256'], report['inputs'][0]['sha256'])
        with self.assertRaises(ValueError): run(self.manifest, output, 'hist')

    def test_group_leakage(self):
        self.rows[2]['group'] = self.rows[0]['group']; self.save()
        with self.assertRaises(ValueError): inspect(self.manifest)

    def test_matched_evaluation_group_allowed(self):
        self.rows[3]['group'] = self.rows[2]['group']; self.save()
        self.assertEqual(len(inspect(self.manifest)), 4)

    def test_evaluation_then_memory_leakage(self):
        self.rows[0]['group'] = self.rows[3]['group']
        self.rows.reverse(); self.save()
        with self.assertRaises(ValueError): inspect(self.manifest)

    def test_duplicate_pixels(self):
        (self.root / '2.png').write_bytes((self.root / '0.png').read_bytes())
        with self.assertRaises(ValueError): inspect(self.manifest)

    def test_missing_role_and_path_escape(self):
        self.rows[3]['role'] = 'familiar'; self.save()
        with self.assertRaises(ValueError): inspect(self.manifest)
        self.rows[3]['image'] = '../elsewhere.png'; self.save()
        with self.assertRaises(ValueError): inspect(self.manifest)

    def test_frozen_memory_and_rank_direction(self):
        class Encoder:
            name = 'fixture'
            def __call__(self, pixels): return pixels
        rows = [dict(image=str(i), group=str(i), sha256='fixture', role=role, pixels=np.array(v))
                for i, (role, v) in enumerate([('memory', [1, 0, 0]), ('memory', [.999, .04, 0]),
                                                ('familiar', [1, 0, 0]), ('novel', [0, 0, 1]),
                                                ('novel', [0, 0, 1])])]
        report = evaluate(rows, Encoder())
        self.assertEqual(report['memory_size'], 2)
        self.assertEqual(report['novel_over_familiar_rank_auc'], 1)
        self.assertEqual(report['scores'][1]['novelty'], report['scores'][2]['novelty'])
        with self.assertRaises(ValueError): evaluate(rows, Encoder(), float('nan'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
