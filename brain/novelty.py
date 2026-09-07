"""Bounded appearance memory with delayed admission and protected targets.

Score all boxes in a frame before observe() admits them. Warm-up defines normal;
post-warm-up appearances remain pending for 30 physics seconds. A committed
target is protected until completion or release, so approach does not erase it.
"""
import math
import threading
import numpy as np


class NoveltyMemory:
    def __init__(self, cap=512, scale=.1, warmup_s=60., commit_delay_s=30.):
        self.cap = cap
        self.tau_floor = max(.1, scale)
        self.warmup_s, self.commit_delay_s = warmup_s, commit_delay_s
        self.started = None
        self.now = 0.
        self._vecs = []
        self.pending = {}
        self.protected = None
        self.d_lo, self.tau = 0., self.tau_floor
        self._lock = threading.RLock()

    @staticmethod
    def normalized(v):
        v = np.asarray(v, dtype=np.float32)
        if v.ndim != 1 or not np.isfinite(v).all() or np.linalg.norm(v) <= 0:
            raise ValueError('embedding must be a finite nonzero vector')
        return v / np.linalg.norm(v)

    def advance(self, t):
        with self._lock:
            if self.started is None:
                self.started = t
            self.now = t
            for key, (due, v) in list(self.pending.items()):
                if due <= t and key != self.protected:
                    self.add(v)
                    del self.pending[key]

    def warming(self):
        return self.started is not None and self.now - self.started < self.warmup_s

    def novelty(self, v):
        with self._lock:
            if self.warming():
                return 0.  # suppress discovery decisions while defining normal
            v = self.normalized(v)
            if not self._vecs:
                return 1.
            distance = max(0., 1. - float((np.stack(self._vecs) @ v).max()))
            return 1. - math.exp(-max(0., distance - self.d_lo) / self.tau)

    def add(self, v):
        with self._lock:
            v = self.normalized(v)
            if self._vecs and float((np.stack(self._vecs) @ v).max()) >= .9999:
                return
            self._vecs.append(v.copy())
            self._vecs = self._vecs[-self.cap:]
            if len(self._vecs) >= 2:
                matrix = np.stack(self._vecs)
                distances = np.maximum(0., 1. - matrix @ matrix.T)
                np.fill_diagonal(distances, np.inf)
                nearest = distances.min(axis=1)
                self.d_lo = float(np.percentile(nearest, 90))
                self.tau = max(self.tau_floor, float(np.median(nearest)))

    def observe(self, key, v):
        with self._lock:
            if self.warming():
                self.add(v)
            elif key not in self.pending:
                if len(self.pending) >= self.cap:
                    victim = next((k for k in self.pending if k != self.protected), None)
                    if victim is not None:
                        del self.pending[victim]
                self.pending[key] = (self.now + self.commit_delay_s, self.normalized(v).copy())

    def protect(self, key):
        with self._lock:
            self.protected = key

    def complete(self, key):
        with self._lock:
            item = self.pending.pop(key, None)
            if item is not None:
                self.add(item[1])
            if self.protected == key:
                self.protected = None

    def __len__(self):
        with self._lock:
            return len(self._vecs)
