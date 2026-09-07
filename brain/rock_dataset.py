"""Validate an offline Godot export and prepare a reproducible YOLO rock dataset.

No scene labels from this module enter BRAIN's observation stream.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import shutil

import cv2
import yaml


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_file(root, name):
    if not isinstance(name, str) or not name:
        raise ValueError('manifest paths must be nonempty relative strings')
    relative = Path(name)
    if relative.is_absolute() or relative.drive or '..' in relative.parts:
        raise ValueError(f'path must stay inside export: {name}')
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'missing or out-of-export file: {name}')
    return path


def labels(path):
    """Return checked normalized boxes; empty files are legitimate backgrounds."""
    boxes = []
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5 or fields[0] != '0':
            raise ValueError(f'{path.name}:{number}: expected 0 cx cy width height (rock only)')
        try:
            x, y, w, h = map(float, fields[1:])
        except ValueError as error:
            raise ValueError(f'{path.name}:{number}: invalid box numbers') from error
        if not all(math.isfinite(v) for v in (x, y, w, h)):
            raise ValueError(f'{path.name}:{number}: non-finite box')
        if not (0 < w <= 1 and 0 < h <= 1 and 0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f'{path.name}:{number}: invalid normalized box')
        if min(x - w / 2, y - h / 2) < -1e-6 or max(x + w / 2, y + h / 2) > 1 + 1e-6:
            raise ValueError(f'{path.name}:{number}: box extends outside the image')
        box = (x, y, w, h)
        if box in boxes:
            raise ValueError(f'{path.name}:{number}: duplicate box')
        boxes.append(box)
    return boxes


def inspect_export(manifest):
    manifest = Path(manifest).resolve()
    rows, image_paths, label_paths, pixel_hashes = [], set(), set(), set()
    for number, line in enumerate(manifest.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != {'image', 'label', 'group'}:
            raise ValueError(f'line {number}: require exactly image, label, group')
        if not isinstance(row['group'], str) or not row['group'].strip():
            raise ValueError(f'line {number}: group must identify an independent capture/layout')
        image = local_file(manifest.parent, row['image'])
        label = local_file(manifest.parent, row['label'])
        if image.suffix.lower() not in {'.jpg', '.jpeg', '.png'} or label.suffix.lower() != '.txt':
            raise ValueError(f'line {number}: expected JPEG/PNG image and TXT labels')
        if image in image_paths or label in label_paths:
            raise ValueError(f'line {number}: image/label file reused')
        pixels = cv2.imread(str(image))
        if pixels is None or pixels.shape[:2] != (480, 640):
            raise ValueError(f'line {number}: image must decode at 640x480')
        pixel_hash = hashlib.sha256(pixels.tobytes()).hexdigest()
        if pixel_hash in pixel_hashes:
            raise ValueError(f'line {number}: duplicate decoded image; remove duplicates before splitting')
        image_paths.add(image); label_paths.add(label); pixel_hashes.add(pixel_hash)
        boxes = labels(label)
        rows.append({**row, 'image_path': image, 'label_path': label, 'boxes': len(boxes),
                     'image_sha256': digest(image), 'label_sha256': digest(label)})
    if not rows:
        raise ValueError('empty export manifest')
    return rows


def split_groups(rows, seed=7):
    groups = sorted({row['group'] for row in rows})
    if len(groups) < 3:
        raise ValueError('at least three independent groups are required for train/val/test')
    random.Random(seed).shuffle(groups)
    # Allocate by group, not frame; keep adjacent camera frames together.
    test_n = max(1, round(len(groups) * .1))
    val_n = max(1, round(len(groups) * .2))
    assignment = {g: 'test' if i < test_n else 'val' if i < test_n + val_n else 'train'
                  for i, g in enumerate(groups)}
    for split in ('train', 'val', 'test'):
        members = [row for row in rows if assignment[row['group']] == split]
        if not members or sum(row['boxes'] for row in members) == 0:
            raise ValueError(f'{split} needs images with positive rock labels; improve group coverage')
    return assignment


def prepare(manifest, output, seed=7):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    rows = inspect_export(manifest)
    assignments = split_groups(rows, seed)
    if output.exists():
        raise ValueError('output already exists; use a fresh directory to preserve prior evidence')
    output.mkdir(parents=True)
    records, counts = [], {}
    for split in ('train', 'val', 'test'):
        (output / 'images' / split).mkdir(parents=True)
        (output / 'labels' / split).mkdir(parents=True)
        counts[split] = {'images': 0, 'boxes': 0, 'backgrounds': 0}
    for i, row in enumerate(rows):
        split = assignments[row['group']]
        stem = f'{i:06d}_{row["image_sha256"][:12]}'
        image = Path('images') / split / (stem + row['image_path'].suffix.lower())
        label = Path('labels') / split / (stem + '.txt')
        shutil.copyfile(row['image_path'], output / image)
        shutil.copyfile(row['label_path'], output / label)
        records.append({'image': image.as_posix(), 'label': label.as_posix(), 'group': row['group'],
                        'split': split, 'boxes': row['boxes'], 'image_sha256': row['image_sha256'],
                        'label_sha256': row['label_sha256']})
        counts[split]['images'] += 1
        counts[split]['boxes'] += row['boxes']
        counts[split]['backgrounds'] += row['boxes'] == 0
    dataset = {'path': output.as_posix(), 'train': 'images/train', 'val': 'images/val',
               'test': 'images/test', 'names': {0: 'rock'}}
    (output / 'dataset.yaml').write_text(yaml.safe_dump(dataset, sort_keys=False), encoding='utf-8')
    provenance = {'version': 1, 'source_manifest_sha256': digest(manifest), 'seed': seed,
                  'group_assignment': assignments, 'counts': counts, 'records': records}
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    verify_prepared(output / 'dataset.yaml')
    return provenance


def verify_prepared(dataset):
    """Recheck files and provenance before training or measuring a checkpoint."""
    dataset = Path(dataset).resolve()
    cfg = yaml.safe_load(dataset.read_text(encoding='utf-8-sig'))
    expected = {'path': dataset.parent.as_posix(), 'train': 'images/train', 'val': 'images/val',
                'test': 'images/test', 'names': {0: 'rock'}}
    if cfg != expected:
        raise ValueError('use the dataset.yaml produced by rock_dataset.py without modification')
    provenance = json.loads(dataset.with_name('provenance.json').read_text(encoding='utf-8'))
    if provenance.get('version') != 1:
        raise ValueError('unsupported provenance version')
    seen, groups, counts = set(), {}, {s: 0 for s in ('train', 'val', 'test')}
    expected_images, expected_labels = set(), set()
    measured = {s: {'images': 0, 'boxes': 0, 'backgrounds': 0} for s in counts}
    for row in provenance['records']:
        split = row['split']
        if split not in counts:
            raise ValueError('invalid dataset split')
        image, label = local_file(dataset.parent, row['image']), local_file(dataset.parent, row['label'])
        if image.parent != dataset.parent / 'images' / split or label.parent != dataset.parent / 'labels' / split:
            raise ValueError('file does not belong to the recorded split')
        if image.stem != label.stem:
            raise ValueError('label stem mismatch')
        if digest(image) != row['image_sha256'] or digest(label) != row['label_sha256']:
            raise ValueError('dataset modified after preparation')
        pixels = cv2.imread(str(image))
        if pixels is None or pixels.shape[:2] != (480, 640):
            raise ValueError('invalid prepared image')
        identity = hashlib.sha256(pixels.tobytes()).hexdigest()
        if identity in seen or (row['group'] in groups and groups[row['group']] != split):
            raise ValueError('duplicate image or group crosses dataset splits')
        seen.add(identity); groups[row['group']] = split
        box_count = len(labels(label))
        if box_count != row['boxes'] or provenance['group_assignment'].get(row['group']) != split:
            raise ValueError('provenance box count or group assignment mismatch')
        counts[split] += box_count
        measured[split]['images'] += 1
        measured[split]['boxes'] += box_count
        measured[split]['backgrounds'] += box_count == 0
        expected_images.add(image); expected_labels.add(label)
    actual_images = {p.resolve() for p in (dataset.parent / 'images').rglob('*') if p.is_file()}
    actual_labels = {p.resolve() for p in (dataset.parent / 'labels').rglob('*.txt')}
    if measured != provenance['counts'] or groups != provenance['group_assignment']:
        raise ValueError('provenance summary mismatch')
    if actual_images != expected_images or actual_labels != expected_labels or not all(counts.values()):
        raise ValueError('untracked files or split without positive labels')
    return provenance


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    print(json.dumps(prepare(args.manifest, args.output, args.seed)['counts'], indent=2))
