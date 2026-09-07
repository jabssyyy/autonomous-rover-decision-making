"""Build an offline novelty diagnostic from SIM annotations, excluding test layouts."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random

import cv2

from rock_dataset import digest, local_file


def crop_bounds(box, width, height, minimum=16):
    if len(box) != 4 or not all(math.isfinite(v) for v in box):
        raise ValueError('box needs four finite normalized coordinates')
    x, y, w, h = box
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
        raise ValueError('invalid normalized box')
    left, top = max(0, math.floor((x-w/2)*width)), max(0, math.floor((y-h/2)*height))
    right, bottom = min(width, math.ceil((x+w/2)*width)), min(height, math.ceil((y+h/2)*height))
    return (left, top, right, bottom) if min(right-left, bottom-top) >= minimum else None


def role_groups(assignments):
    validation = sorted(g for g, split in assignments.items() if split == 'val')
    train = sorted(g for g, split in assignments.items() if split == 'train')
    if len(validation) < 2 or not train:
        raise ValueError('need train layouts and two independent validation layouts')
    return {**{g: 'memory' for g in train}, validation[0]: 'familiar', validation[1]: 'novel'}


def build(export, provenance_path, output, limit=100, seed=7):
    export, provenance_path, output = map(lambda p: Path(p).resolve(), (export, provenance_path, output))
    if output.exists():
        raise ValueError('use a fresh output directory')
    if not 2 <= limit <= 100:
        raise ValueError('limit must be between 2 and 100 crops per role')
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    if digest(export / 'export.jsonl') != provenance['source_manifest_sha256']:
        raise ValueError('export manifest does not match prepared dataset')
    groups = role_groups(provenance['group_assignment'])
    allowed = {(r['group'], r['image_sha256']) for r in provenance['records']}
    candidates = {role: [] for role in ('memory', 'familiar', 'novel')}
    annotation_hashes = {}
    for group, role in groups.items():
        annotation = local_file(export, group + '/annotations.jsonl')
        annotation_hashes[group] = digest(annotation)
        for line in annotation.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            for obj in row['objects']:
                expected = 'unusual' if role == 'novel' else 'common'
                if obj['appearance'] == expected:
                    candidates[role].append((group, row['image'], obj))
    selected, hashes, seen_objects, seen_pixels = [], {}, set(), set()
    rng = random.Random(seed)
    for role, items in candidates.items():
        rng.shuffle(items)
        count = 0
        for group, name, obj in items:
            identity = (group, obj['object'])
            if identity in seen_objects:
                continue
            source = local_file(export, group + '/' + name)
            source_hash = hashes.setdefault(str(source), digest(source))
            if (group, source_hash) not in allowed:
                raise ValueError('annotation image is absent or changed from prepared dataset')
            pixels = cv2.imread(str(source))
            if pixels is None:
                raise ValueError('source image does not decode')
            bounds = crop_bounds(obj['box'], pixels.shape[1], pixels.shape[0])
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            crop = pixels[top:bottom, left:right].copy()
            pixel_hash = hashlib.sha256(str(crop.shape).encode() + crop.tobytes()).hexdigest()
            if pixel_hash in seen_pixels:
                continue
            selected.append(({'image': f'crops/{role}_{count:03d}.png', 'group': group, 'role': role},
                             {'source': source.relative_to(export).as_posix(), 'source_sha256': source_hash,
                              'object': obj['object'], 'appearance': obj['appearance'], 'bounds': bounds}, crop))
            seen_pixels.add(pixel_hash)
            seen_objects.add(identity)
            count += 1
            if count == limit:
                break
        if count < 2:
            raise ValueError(f'need at least two usable {role} crops')
    (output / 'crops').mkdir(parents=True)
    evidence = []
    for row, details, crop in selected:
        path = output / row['image']
        if not cv2.imwrite(str(path), crop):
            raise OSError('failed to write crop')
        evidence.append({**row, **details, 'crop_sha256': digest(path)})
    (output / 'manifest.jsonl').write_text(''.join(json.dumps(row) + '\n' for row, _, _ in selected), encoding='utf-8')
    report = {'version': 1, 'seed': seed, 'limit_per_role': limit, 'minimum_crop_pixels': 16,
              'prepared_provenance_sha256': digest(provenance_path), 'annotation_sha256': annotation_hashes,
              'groups': groups, 'selection': 'One crop per scene object per layout; shuffled before selection',
              'counts': {r: sum(row['role'] == r for row, _, _ in selected) for r in candidates}, 'crops': evidence}
    (output / 'provenance.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('provenance', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    print(json.dumps(build(args.export, args.provenance, args.output, args.limit, args.seed)['counts'], indent=2))
