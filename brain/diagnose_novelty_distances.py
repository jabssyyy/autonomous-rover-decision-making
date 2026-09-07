"""Compare fixed encoders and raw distances without changing runtime calibration."""
import argparse
import json
from pathlib import Path

import numpy as np

from check_novelty_dataset import inspect
from novelty import NoveltyMemory
from perception import HistEmbedder, TorchEmbedder
from rock_dataset import digest


def rank_auc(familiar, novel):
    a, b = np.asarray(familiar), np.asarray(novel)
    return float(((b[:, None] > a).sum() + .5 * (b[:, None] == a).sum()) / (len(a) * len(b)))


def summarize(values):
    return {'count': len(values), 'median': float(np.median(values)),
            'p10': float(np.percentile(values, 10)), 'p90': float(np.percentile(values, 90))}


def compare(rows, vectors):
    memory, accepted = NoveltyMemory(scale=.1, warmup_s=0), []
    for row, vector in zip(rows, vectors):
        if row['role'] == 'memory':
            before = len(memory)
            memory.add(vector)
            if len(memory) > before:
                accepted.append(memory.normalized(vector))
    if len(accepted) < 2:
        raise ValueError('at least two distinct memory embeddings required')
    matrix = np.stack(accepted)
    scores = []
    for row, vector in zip(rows, vectors):
        if row['role'] != 'memory':
            distance = max(0., 1. - float((matrix @ memory.normalized(vector)).max()))
            scores.append({k: row[k] for k in ('image', 'role', 'group', 'sha256')} |
                          {'distance': distance, 'novelty': memory.novelty(vector)})
    result = {'memory_size': len(memory), 'd_lo': memory.d_lo, 'tau': memory.tau, 'scores': scores}
    for metric in ('distance', 'novelty'):
        roles = {role: [s[metric] for s in scores if s['role'] == role] for role in ('familiar', 'novel')}
        result[metric] = {role: summarize(values) for role, values in roles.items()}
        result[metric]['rank_auc'] = rank_auc(roles['familiar'], roles['novel'])
    result['clipped_to_zero'] = {role: sum(s['novelty'] == 0 for s in scores if s['role'] == role)
                                 for role in ('familiar', 'novel')}
    return result


def run(manifest, output):
    import torch
    torch.set_num_threads(2)
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('use a fresh report path')
    checkpoint = Path(__file__).resolve().parent / 'weights/cache/hub/checkpoints/resnet18-f37072fd.pth'
    if not checkpoint.is_file():
        raise ValueError('cached ResNet18 weights required; this diagnostic does not download models')
    rows = inspect(manifest)
    resnet, hist = TorchEmbedder('cpu'), HistEmbedder()
    neural = [resnet(row['pixels']) for row in rows]
    histogram = [hist(row['pixels']) for row in rows]
    combined = [NoveltyMemory.normalized(np.concatenate((a, b))) for a, b in zip(neural, histogram)]
    results = {name: compare(rows, vectors) for name, vectors in
               [('resnet18', neural), ('hist', histogram), ('resnet18_plus_hist_equal_weight', combined)]}
    report = {'manifest_sha256': digest(manifest), 'resnet18_checkpoint_sha256': digest(checkpoint),
              'method': 'Frozen common memory; raw nearest cosine distance and unchanged runtime scoring; no fitting',
              'fusion': 'Concatenate unit ResNet18 and unit histogram vectors, then normalize; equal block weight',
              'results': results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = run(args.manifest, args.output)
    print(json.dumps({name: {k: v for k, v in result.items() if k != 'scores'}
                      for name, result in report['results'].items()}, indent=2))
