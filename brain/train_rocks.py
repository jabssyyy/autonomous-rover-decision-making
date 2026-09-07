"""Train or evaluate rock weights using a validated, grouped offline dataset."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from rock_dataset import digest, verify_prepared


def run(args, model_factory=None):
    dataset = args.dataset.resolve()
    provenance = verify_prepared(dataset)
    if args.epochs < 1 or args.batch < 1:
        raise ValueError('epochs and batch must be positive')
    weights = Path(args.weights)
    if weights.suffix != '.pt':
        raise ValueError('weights must be a .pt checkpoint')
    if args.mode == 'evaluate' and not weights.is_file():
        raise ValueError('evaluation requires an existing trained checkpoint')
    if args.mode == 'train' and not weights.is_file() and args.weights != 'yolo26n.pt':
        raise ValueError('provide a local checkpoint or the supported yolo26n.pt download name')
    output = args.output.resolve()
    if output.exists():
        raise ValueError('use a fresh output directory to preserve earlier results')
    if output == dataset.parent or output.is_relative_to(dataset.parent):
        raise ValueError('keep training outputs outside the prepared dataset')
    evidence = {'mode': args.mode, 'dataset': str(dataset),
                'dataset_sha256': digest(dataset),
                'provenance_sha256': digest(dataset.with_name('provenance.json')),
                'counts': provenance['counts'], 'weights': str(weights),
                'input_weights_sha256': digest(weights) if weights.is_file() else None,
                'seed': 7, 'imgsz': 640, 'epochs': args.epochs, 'batch': args.batch,
                'device': args.device, 'dry_run': args.dry_run}
    if args.dry_run:
        return evidence
    if model_factory is None:
        from ultralytics import YOLO
        model_factory = YOLO
    model = model_factory(str(weights))
    output.mkdir(parents=True)
    evidence['input_weights_sha256'] = digest(weights) if weights.is_file() else evidence['input_weights_sha256']
    common = dict(data=str(dataset), imgsz=640, batch=args.batch, device=args.device,
                  workers=0, project=str(output), name='run', exist_ok=False,
                  seed=7, deterministic=True)
    if args.mode == 'train':
        model.train(**common, epochs=args.epochs, val=True)
        best = Path(model.trainer.best)
        if not best.is_file():
            raise RuntimeError('training returned without a best checkpoint')
        evidence.update(best_checkpoint=str(best.resolve()), best_sha256=digest(best))
    else:
        if model.names != {0: 'rock'}:
            raise ValueError('evaluation checkpoint must have exactly one class named rock')
        metrics = model.val(**common, split='test', plots=True)
        values = {'mAP50': float(metrics.box.map50), 'mAP50_95': float(metrics.box.map),
                  'precision': float(metrics.box.mp), 'recall': float(metrics.box.mr)}
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in values.values()):
            raise ValueError('evaluation returned invalid metrics')
        evidence.update(metrics=values, meets_map50_target=values['mAP50'] >= .6,
                        acceptance='Requires visual review and live Godot validation before installation')
    verify_prepared(dataset)
    if digest(dataset.with_name('provenance.json')) != evidence['provenance_sha256']:
        raise ValueError('provenance changed during execution')
    (output / 'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    return evidence


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['train', 'evaluate'])
    p.add_argument('--dataset', required=True, type=Path)
    p.add_argument('--weights', default='yolo26n.pt')
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--epochs', type=int, default=40)
    p.add_argument('--batch', type=int, default=8)
    p.add_argument('--device', default='0', help='CUDA index (0) or cpu')
    p.add_argument('--dry-run', action='store_true', help='Validate inputs without loading/downloading a model')
    return p


if __name__ == '__main__':
    print(json.dumps(run(parser().parse_args()), indent=2))
