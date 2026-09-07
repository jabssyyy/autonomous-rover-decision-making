"""CPU checks for matched novelty roles and separate development/confirmation data."""
import argparse
from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from check_novelty_dataset import inspect
from rock_dataset import digest, local_file


def verify(export, dataset):
    export, dataset = Path(export).resolve(), Path(dataset).resolve()
    report = json.loads((dataset / 'provenance.json').read_text())
    if digest(export / 'export.jsonl') != report['export_manifest_sha256']:
        raise ValueError('export manifest changed')
    for group, expected in report['annotation_sha256'].items():
        if digest(local_file(export, group + '/annotations.jsonl')) != expected:
            raise ValueError('annotation changed')
    manifests = {part: inspect(dataset / (part + '.jsonl')) for part in ('dev', 'confirmation')}
    roles = {}
    for row in report['crops']:
        if report['groups'][row['group']] != row['partition']:
            raise ValueError('group crosses partitions')
        source = local_file(export, row['source'])
        target = local_file(dataset, row['image'])
        if digest(source) != row['source_sha256'] or digest(target) != row['crop_sha256']:
            raise ValueError('source or crop changed')
        x0, y0, x1, y1 = row['bounds']
        expected = cv2.imread(str(source))[y0:y1, x0:x1]
        if not np.array_equal(expected, cv2.imread(str(target))):
            raise ValueError('crop does not match source bounds')
        expected_role = 'memory' if row['partition'] == 'memory' else 'familiar' if row['appearance'] == 'common' else 'novel'
        if row['role'] != expected_role or (row['role'] == 'memory' and row['appearance'] != 'common'):
            raise ValueError('appearance and role mismatch')
        roles[(row['partition'], row['role'])] = roles.get((row['partition'], row['role']), 0) + 1
    for part, rows in manifests.items():
        key = lambda r: (r['image'], r['group'], r['role'], r.get('sha256', r.get('crop_sha256')))
        expected = [row for row in report['crops'] if row['partition'] in ('memory', part)]
        if Counter(map(key, rows)) != Counter(map(key, expected)):
            raise ValueError('manifest differs from provenance')
    dev = {r['image'] for r in manifests['dev'] if r['role'] != 'memory'}
    confirmation = {r['image'] for r in manifests['confirmation'] if r['role'] != 'memory'}
    if dev & confirmation:
        raise ValueError('development crop reused for confirmation')
    return {f'{part}/{role}': count for (part, role), count in roles.items()}


class RoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = []
        for i, role in enumerate(('memory', 'familiar', 'novel')):
            image = f'{role}.png'
            cv2.imwrite(str(self.root / image), np.full((24, 24, 3), i * 70, np.uint8))
            self.rows.append({'image': image, 'role': role, 'group': 'memory-layout' if role == 'memory' else 'matched-eval-layout'})
        self.manifest = self.root / 'manifest.jsonl'

    def save(self):
        self.manifest.write_text('\n'.join(map(json.dumps, self.rows)))

    def test_matched_evaluation_roles_allowed(self):
        self.save()
        self.assertEqual(len(inspect(self.manifest)), 3)

    def test_memory_group_leak_rejected(self):
        self.rows[1]['group'] = 'memory-layout'
        self.save()
        with self.assertRaisesRegex(ValueError, 'crosses memory and evaluation'):
            inspect(self.manifest)

    def test_duplicate_pixels_across_roles_rejected(self):
        (self.root / 'novel.png').write_bytes((self.root / 'familiar.png').read_bytes())
        self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate crop'):
            inspect(self.manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path)
    parser.add_argument('--dataset', type=Path)
    args = parser.parse_args()
    if bool(args.export) != bool(args.dataset):
        parser.error('supply both --export and --dataset')
    if args.export:
        print(json.dumps(verify(args.export, args.dataset), indent=2))
    else:
        unittest.main(argv=['check_balanced_novelty'], verbosity=2)
