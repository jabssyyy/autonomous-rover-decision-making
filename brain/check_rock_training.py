"""Offline preparation checks using synthetic fixtures, not detector accuracy tests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import cv2
import numpy as np

from rock_dataset import inspect_export, prepare, verify_prepared, split_groups
from train_rocks import parser, run


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'export.jsonl'
        self.rows = []
        for i in range(12):
            image, label = f'{i}.png', f'{i}.txt'
            cv2.imwrite(str(self.root / image), np.full((480, 640, 3), i * 15, np.uint8))
            (self.root / label).write_text('0 .5 .5 .2 .2\n' if i % 2 == 0 else '', encoding='utf-8')
            self.rows.append(dict(image=image, label=label, group=f'layout-{i // 2}'))
        self.save()

    def save(self):
        self.manifest.write_text('\n'.join(map(json.dumps, self.rows)), encoding='utf-8')

    def prepared(self):
        prepare(self.manifest, self.root / 'prepared')
        return self.root / 'prepared' / 'dataset.yaml'

    def args(self, mode='train'):
        return parser().parse_args([mode, '--dataset', str(self.prepared()), '--output', str(self.root / 'run')])

    def test_group_split_and_backgrounds(self):
        p = verify_prepared(self.prepared())
        self.assertEqual(sum(v['backgrounds'] for v in p['counts'].values()), 6)
        for group in p['group_assignment']:
            self.assertEqual(len({r['split'] for r in p['records'] if r['group'] == group}), 1)
        rows = inspect_export(self.manifest)
        self.assertEqual(split_groups(rows), split_groups(list(reversed(rows))))

    def test_bad_labels(self):
        for value in ['1 .5 .5 .2 .2', '0 nan .5 .2 .2', '0 .9 .5 .4 .2', '0 .5 .5 0 .2',
                      '0 .5 .5 .2 .2\n0 .5 .5 .2 .2']:
            with self.subTest(value=value):
                (self.root / '0.txt').write_text(value)
                with self.assertRaises(ValueError):
                    inspect_export(self.manifest)

    def test_escape_and_reuse(self):
        self.rows[0]['image'] = '../outside.png'; self.save()
        with self.assertRaises(ValueError): inspect_export(self.manifest)
        self.rows[0]['image'] = '1.png'; self.save()
        with self.assertRaises(ValueError): inspect_export(self.manifest)

    def test_duplicate_pixels(self):
        (self.root / '1.png').write_bytes((self.root / '0.png').read_bytes())
        with self.assertRaises(ValueError): inspect_export(self.manifest)

    def test_wrong_dimensions(self):
        cv2.imwrite(str(self.root / '0.png'), np.zeros((48, 64, 3), np.uint8))
        with self.assertRaises(ValueError): inspect_export(self.manifest)

    def test_insufficient_groups(self):
        for row in self.rows: row['group'] = 'same-capture'
        self.save()
        with self.assertRaises(ValueError): self.prepared()

    def test_changed_and_extra_files(self):
        dataset = self.prepared()
        label = next((dataset.parent / 'labels').rglob('*.txt'))
        original = label.read_bytes(); label.write_text('0 .5 .5 .1 .1')
        with self.assertRaises(ValueError): verify_prepared(dataset)
        label.write_bytes(original)
        (dataset.parent / 'labels' / 'train' / 'extra.txt').write_text('')
        with self.assertRaises(ValueError): verify_prepared(dataset)

    def test_no_overwrite(self):
        self.prepared()
        with self.assertRaises(ValueError): self.prepared()

    def test_dry_run_never_loads_model(self):
        args = self.args(); args.dry_run = True
        def forbidden(*a): raise AssertionError('loaded model')
        self.assertTrue(run(args, forbidden)['dry_run'])
        self.assertFalse(args.output.exists())

    def test_train_wrapper(self):
        args = self.args()
        best = self.root / 'best.pt'; best.write_bytes(b'fixture only')
        class FakeModel:
            trainer = SimpleNamespace(best=best)
            def train(model, **kwargs):
                self.assertTrue(kwargs['val'])
                self.assertNotIn('split', kwargs)
                self.assertEqual(kwargs['workers'], 0)
        result = run(args, lambda _: FakeModel())
        self.assertEqual(result['best_checkpoint'], str(best.resolve()))
        self.assertTrue((args.output / 'result.json').is_file())

    def test_held_out_evaluation(self):
        args = self.args('evaluate')
        weights = self.root / 'rock.pt'; weights.write_bytes(b'fixture only'); args.weights = str(weights)
        class FakeModel:
            names = {0: 'rock'}
            def val(model, **kwargs):
                self.assertEqual(kwargs['split'], 'test')
                return SimpleNamespace(box=SimpleNamespace(map50=.65, map=.4, mp=.7, mr=.6))
        result = run(args, lambda _: FakeModel())
        self.assertTrue(result['meets_map50_target'])
        self.assertIn('visual review', result['acceptance'])

    def test_reject_stock_classes(self):
        args = self.args('evaluate')
        weights = self.root / 'stock.pt'; weights.write_bytes(b'fixture'); args.weights = str(weights)
        with self.assertRaises(ValueError):
            run(args, lambda _: SimpleNamespace(names={0: 'person'}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
