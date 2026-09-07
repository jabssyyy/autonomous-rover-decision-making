"""Preserve checkpoint bytes when a dependency cannot handle apostrophes in paths."""
import hashlib
from pathlib import Path
import shutil
import tempfile


def loadable_checkpoint(path):
    source = Path(path).resolve()
    if "'" not in str(source):
        return str(source)
    identity = hashlib.sha256(source.read_bytes()).hexdigest()
    cache = Path(tempfile.gettempdir()) / 'iete-rover-weights'
    if "'" in str(cache):
        raise ValueError('checkpoint cache must have an apostrophe-free path')
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (identity + '.pt')
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != identity:
        shutil.copyfile(source, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != identity:
        raise ValueError('checkpoint cache hash mismatch')
    return str(target)
