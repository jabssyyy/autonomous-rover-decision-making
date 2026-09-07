"""Prepare matched common/unusual focus crops with separate development and confirmation layouts."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2

from build_novelty_crops import crop_bounds
from rock_dataset import digest, inspect_export, local_file


def build(export, output):
    export, output = Path(export).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('use a fresh output directory')
    rows = inspect_export(export / 'export.jsonl')
    groups = sorted({r['group'] for r in rows})
    if len(groups) != 6:
        raise ValueError('exactly six independent layouts required')
    assignments = {g: ('memory' if i < 2 else 'dev' if i < 4 else 'confirmation') for i, g in enumerate(groups)}
    sources = {r['image']: r for r in rows}
    crops, seen, annotations = [], set(), {}
    for group in groups:
        path = local_file(export, group + '/annotations.jsonl')
        annotations[group] = digest(path)
        for line in path.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            objects = [obj for obj in row['objects'] if obj['object'] == row['focus']]
            if not objects:
                continue
            if len(objects) != 1:
                raise ValueError('focus object must have at most one box')
            obj = objects[0]
            if obj['appearance'] not in ('common', 'unusual'):
                raise ValueError('unknown focus appearance')
            partition = assignments[group]
            if partition == 'memory' and obj['appearance'] != 'common':
                continue
            role = 'memory' if partition == 'memory' else 'familiar' if obj['appearance'] == 'common' else 'novel'
            name = group + '/' + row['image']
            source = sources[name]
            if source['group'] != group or digest(source['image_path']) != source['image_sha256']:
                raise ValueError('source image changed or belongs to another group')
            image = cv2.imread(str(source['image_path']))
            bounds = crop_bounds(obj['box'], image.shape[1], image.shape[0], minimum=24)
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            crop = image[top:bottom, left:right].copy()
            fingerprint = hashlib.sha256(str(crop.shape).encode() + crop.tobytes()).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            record = {'image': f'crops/{partition}_{len(crops):04d}.png', 'group': group, 'role': role}
            provenance = {**record, 'partition': partition, 'source': name, 'source_sha256': source['image_sha256'],
                          'object': obj['object'], 'appearance': obj['appearance'], 'bounds': bounds}
            crops.append((record, provenance, crop))
    for partition in ('memory', 'dev', 'confirmation'):
        roles = {r['role'] for r, p, _ in crops if p['partition'] == partition}
        if roles != ({'memory'} if partition == 'memory' else {'familiar', 'novel'}):
            raise ValueError('missing role in ' + partition)
    (output / 'crops').mkdir(parents=True)
    records = []
    for row, provenance, crop in crops:
        target = output / row['image']
        if not cv2.imwrite(str(target), crop):
            raise OSError('crop writing failed')
        records.append({**provenance, 'crop_sha256': digest(target)})
    for partition in ('dev', 'confirmation'):
        selected = [r for r, p, _ in crops if p['partition'] in ('memory', partition)]
        (output / (partition + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in selected), encoding='utf-8')
    report = {'version': 1, 'groups': assignments, 'export_manifest_sha256': digest(export / 'export.jsonl'),
              'annotation_sha256': annotations, 'minimum_crop_pixels': 24,
              'selection': 'One focus crop per frame; repeated views retained and object IDs recorded',
              'limitation': 'Repeated object views are correlated; simulator has only three unusual mesh families',
              'crops': records}
    (output / 'provenance.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = build(args.export, args.output)
    print(json.dumps({'groups': result['groups'], 'total_crops': len(result['crops'])}, indent=2))
