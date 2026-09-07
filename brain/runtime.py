"""runtime.py -- the three BRAIN runtime primitives (stdlib only).

LatestSlot : single-slot mailbox. put() overwrites, take() waits for the newest.
             This is "latest frame wins": perception never queues stale frames.
DelayLine  : constant delay in REAL seconds (time.monotonic). The ONE place in the
             whole system where the comms delay exists (interface-contract.md section 6).
Recorder   : background-thread disk writer. Frames + JSONL streams. The asyncio loop
             never touches the filesystem.
"""
from __future__ import annotations

import asyncio
import collections
import json
import queue
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable


def dumps(obj: Any) -> str:
    # allow_nan=False: a NaN in an audit record must crash here, not on a judge's screen
    return json.dumps(obj, separators=(",", ":"), allow_nan=False)


class LatestSlot:
    """Newest-wins mailbox for the asyncio loop thread (no locks needed: put/take
    both run on the loop). Counts how many items were overwritten unseen."""

    def __init__(self) -> None:
        self._item: Any = None
        self._event = asyncio.Event()
        self.dropped = 0
        self._dropped_since_take = 0

    def put(self, item: Any) -> None:
        if self._item is not None:
            self.dropped += 1
            self._dropped_since_take += 1
        self._item = item
        self._event.set()

    async def take(self) -> Any:
        await self._event.wait()
        item, self._item = self._item, None
        self._event.clear()
        return item

    def take_dropped(self) -> int:
        n, self._dropped_since_take = self._dropped_since_take, 0
        return n


class DelayLine:
    """FIFO with a constant real-time delay. push() stamps release = now + delay;
    a single task releases heads in order and awaits `deliver(item)`."""

    def __init__(self, delay_s: float, deliver: Callable[[Any], Awaitable[None]]) -> None:
        self.delay_s = float(delay_s)
        self._deliver = deliver
        self._q: collections.deque = collections.deque()
        self._wake = asyncio.Event()

    def push(self, item: Any) -> float:
        release_at = time.monotonic() + self.delay_s
        self._q.append((release_at, item))
        self._wake.set()
        return release_at

    def __len__(self) -> int:
        return len(self._q)

    async def run(self) -> None:
        while True:
            if not self._q:
                self._wake.clear()
                await self._wake.wait()
                continue
            release_at, item = self._q[0]
            wait = release_at - time.monotonic()
            if wait > 0:
                await asyncio.sleep(min(wait, 0.5))  # short naps so delay_s edits take effect
                continue
            self._q.popleft()
            try:
                await self._deliver(item)
            except Exception as e:  # never let one bad delivery stop the line
                print(f"[DelayLine] deliver failed: {e!r}")


class Recorder:
    """runs/<stamp>_<tag>/ {meta.json, frames/*.jpg, <stream>.jsonl ...}
    Everything goes through a queue to one writer thread."""

    def __init__(self, root: str | Path, tag: str, meta: dict) -> None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.dir = Path(root) / f"{stamp}_{tag}"
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        (self.dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        self._q: queue.Queue = queue.Queue()
        self._files: dict[str, Any] = {}
        self._t = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._t.start()

    def frame(self, seq: int, jpeg: bytes) -> str:
        ref = f"f_{seq}"
        self._q.put(("blob", ref, jpeg))
        return ref

    def blob(self, name: str, data: bytes) -> str:
        self._q.put(("blob", name, data))
        return name

    def jsonl(self, stream: str, record: dict) -> None:
        self._q.put(("jsonl", stream, json.dumps(record, separators=(",", ":"), default=str)))

    def close(self) -> None:
        self._q.put(None)
        self._t.join(timeout=10)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                break
            kind, name, payload = item
            try:
                if kind == "blob":
                    (self.dir / "frames" / f"{name}.jpg").write_bytes(payload)
                else:
                    f = self._files.get(name)
                    if f is None:
                        f = self._files[name] = open(self.dir / f"{name}.jsonl", "a", encoding="utf-8")
                    f.write(payload + "\n")
                    f.flush()
            except Exception as e:
                print(f"[Recorder] write failed for {kind}:{name}: {e!r}")
        for f in self._files.values():
            f.close()
