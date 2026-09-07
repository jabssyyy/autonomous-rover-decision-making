"""Check exported annotation/YOLO alignment and source-to-training provenance on CPU."""
import argparse
from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from rock_dataset import digest, inspect_export, labels, prepare, verify_prepared


def check_handoff(manifest, dataset):
    manifest = Path(manifest).resolve()
    rows = inspect_export(manifest)
    provenance = verify_prepared(dataset)
    if provenance['source_manifest_sha256'] != digest(manifest):
        raise ValueError('prepared dataset came from a different export manifest')
    key = lambda row: (row['image_sha256'], row['label_sha256'], row['group'], row['boxes'])
    if Counter(map(key, rows)) != Counter(map(key, provenance['records'])):
        raise ValueError('prepared data differs from exported images, labels, or groups')
    annotations = {}
    appearances = Counter()
    for row in rows:
        root = row['image_path'].parent.parent
        if root not in annotations:
            records = [json.loads(line) for line in (root / 'annotations.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
            mapping = {record['image']: record['objects'] for record in records}
            if len(mapping) != len(records):
                raise ValueError('duplicate annotation image')
            annotations[root] = mapping
        name = row['image_path'].relative_to(root).as_posix()
        objects = annotations[root].get(name)
        boxes = labels(row['label_path'])
        if objects is None or len(objects) != len(boxes):
            raise ValueError('missing annotation or annotation/label count mismatch')
        for obj, box in zip(objects, boxes):
            if obj['appearance'] not in {'common', 'unusual'} or len(obj['box']) != 4:
                raise ValueError('invalid appearance or box annotation')
            if not np.allclose(obj['box'], box, atol=0.00000051, rtol=0):
                raise ValueError('annotation box differs from six-decimal YOLO box')
            appearances[obj['appearance']] += 1
    return {'frames': len(rows), 'groups': len(provenance['group_assignment']),
            'counts': provenance['counts'], 'appearance_boxes': dict(appearances)}


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rows = []
        for i in range(3):
            group = f'layout-{i}'
            root = self.root / group
            (root / 'images').mkdir(parents=True)
            (root / 'labels').mkdir()
            cv2.imwrite(str(root / 'images/frame.png'), np.full((480, 640, 3), i * 60, np.uint8))
            (root / 'labels/frame.txt').write_text('0 .5 .5 .2 .2', encoding='utf-8')
            (root / 'annotations.jsonl').write_text(json.dumps({'image': 'images/frame.png', 'objects': [
                {'object': 'Rock0', 'appearance': 'common', 'box': [.5, .5, .2, .2]}]}), encoding='utf-8')
            rows.append({'image': group + '/images/frame.png', 'label': group + '/labels/frame.txt', 'group': group})
        self.manifest = self.root / 'export.jsonl'
        self.manifest.write_text('\n'.join(map(json.dumps, rows)), encoding='utf-8')
        prepare(self.manifest, self.root / 'prepared')
        self.dataset = self.root / 'prepared/dataset.yaml'

    def test_exact_source_handoff(self):
        result = check_handoff(self.manifest, self.dataset)
        self.assertEqual(result['frames'], 3)
        self.assertEqual(result['appearance_boxes'], {'common': 3})

    def test_annotation_box_drift(self):
        annotation = self.root / 'layout-0/annotations.jsonl'
        record = json.loads(annotation.read_text())
        record['objects'][0]['box'][0] = .6
        annotation.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'annotation box differs'):
            check_handoff(self.manifest, self.dataset)

    def test_wrong_export_manifest(self):
        self.manifest.write_text(self.manifest.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'different export manifest'):
            check_handoff(self.manifest, self.dataset)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--dataset', type=Path)
    args = parser.parse_args()
    if bool(args.manifest) != bool(args.dataset):
        parser.error('supply both --manifest and --dataset')
    if args.manifest:
        print(json.dumps(check_handoff(args.manifest, args.dataset), indent=2))
    else:
        unittest.main(argv=['check_export_handoff'], verbosity=2)
