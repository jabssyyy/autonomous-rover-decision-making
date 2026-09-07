"""Evaluate frozen appearance memory on offline, independently grouped crops.

Human-assigned familiar/novel roles are evaluation annotations, never runtime inputs.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from novelty import NoveltyMemory
from perception import HistEmbedder, TorchEmbedder
from rock_dataset import digest, local_file


def inspect(manifest):
    manifest = Path(manifest).resolve()
    rows, seen, groups = [], set(), {}
    for line in manifest.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != {'image', 'group', 'role'}:
            raise ValueError('each row requires exactly image, group, role')
        if row['role'] not in ('memory', 'familiar', 'novel'):
            raise ValueError('role must be memory, familiar or novel')
        if not isinstance(row['group'], str) or not row['group'].strip():
            raise ValueError('group must identify an independent capture/layout family')
        path = local_file(manifest.parent, row['image'])
        pixels = cv2.imread(str(path))
        if pixels is None or min(pixels.shape[:2]) < 8:
            raise ValueError('crop must decode and be at least 8x8 pixels')
        identity = hashlib.sha256(str(pixels.shape).encode() + pixels.tobytes()).hexdigest()
        if identity in seen:
            raise ValueError('duplicate crop')
        partition = 'memory' if row['role'] == 'memory' else 'evaluation'
        if row['group'] in groups and groups[row['group']] != partition:
            raise ValueError('capture group crosses memory and evaluation')
        seen.add(identity); groups[row['group']] = partition
        rows.append({**row, 'sha256': digest(path), 'pixels': pixels})
    if {r['role'] for r in rows} != {'memory', 'familiar', 'novel'}:
        raise ValueError('all three roles need crops')
    if sum(r['role'] == 'memory' for r in rows) > 512:
        raise ValueError('use at most 512 memory crops to match runtime capacity')
    return sorted(rows, key=lambda r: (r['role'], r['image']))


def evaluate(rows, embedder, scale=.1):
    if not math.isfinite(scale) or scale < .1:
        raise ValueError('scale must be finite and at least 0.1')
    memory = NoveltyMemory(scale=scale, warmup_s=0)
    for row in rows:
        if row['role'] == 'memory':
            memory.add(embedder(row['pixels']))
    if len(memory) < 2:
        raise ValueError('memory needs at least two distinct appearance embeddings')
    scored = []
    for row in rows:
        if row['role'] != 'memory':
            scored.append({k: row[k] for k in ('image', 'group', 'role', 'sha256')} |
                          {'novelty': memory.novelty(embedder(row['pixels']))})
    summaries = {}
    for role in ('familiar', 'novel'):
        values = [r['novelty'] for r in scored if r['role'] == role]
        summaries[role] = dict(count=len(values), median=float(np.median(values)),
                               p10=float(np.percentile(values, 10)), p90=float(np.percentile(values, 90)))
    # Rank statistic: probability a novel crop outranks a familiar crop, ties half.
    familiar = np.array([r['novelty'] for r in scored if r['role'] == 'familiar'])
    rank_sum = sum(float((r['novelty'] > familiar).sum()) + .5 * float((r['novelty'] == familiar).sum())
                   for r in scored if r['role'] == 'novel')
    return {'encoder': embedder.name, 'memory_size': len(memory), 'd_lo': memory.d_lo,
            'tau': memory.tau, 'scale_floor': scale, 'summary': summaries,
            'novel_over_familiar_rank_auc': rank_sum / (len(familiar) * summaries['novel']['count']),
            'scores': scored, 'method': 'Frozen memory; evaluation crops are never admitted',
            'acceptance': 'Diagnostic only; review scene coverage and score overlap before calibration'}


def run(manifest, output, encoder='resnet18', device='cuda:0', scale=.1):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('use a new report path to preserve previous evidence')
    rows = inspect(manifest)
    source_hash = digest(manifest)
    embedder = HistEmbedder() if encoder == 'hist' else TorchEmbedder(device)
    report = evaluate(rows, embedder, scale)
    report.update(manifest_sha256=source_hash, inputs=[{k: r[k] for k in ('image', 'group', 'role', 'sha256')} for r in rows])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--encoder', choices=['hist', 'resnet18'], default='resnet18')
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--scale', type=float, default=.1)
    args = parser.parse_args()
    result = run(args.manifest, args.output, args.encoder, args.device, args.scale)
    print(json.dumps({k: v for k, v in result.items() if k not in ('inputs', 'scores')}, indent=2))
