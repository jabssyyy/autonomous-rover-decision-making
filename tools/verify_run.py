"""verify_run.py -- replay a recorded SIM run through contract.py and prove it clean.

    python tools/verify_run.py runs/smoke

Reads back what SIM actually sent, validates every observation, every JPEG and every
action against interface-contract.md, re-checks the audit arithmetic, and reports the
things a judge might ask about: frame rate, JPEG sizes, budget monotonicity, distance.
Exit code is non-zero if anything failed, so it can gate a push.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))
from contract import (ContractViolation, check_audit_arithmetic, validate_action,  # noqa: E402
                      validate_jpeg, validate_observation)


def main(run_dir: Path) -> int:
    obs_path = run_dir / "observations.jsonl"
    if not obs_path.exists():
        print(f"no observations.jsonl in {run_dir}")
        return 2

    fails: list[str] = []
    obs, sizes = [], []
    for i, line in enumerate(obs_path.read_text().splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        ref, nbytes = row.pop("_frame_ref", None), row.pop("_bytes", None)
        try:
            validate_observation(row)
        except ContractViolation as e:
            fails.append(f"observations.jsonl:{i + 1}: {e}")
            continue
        obs.append(row)
        frame = run_dir / "frames" / f"{ref}.jpg"
        if not frame.exists():
            fails.append(f"observations.jsonl:{i + 1}: missing frame {ref}.jpg")
            continue
        blob = frame.read_bytes()
        try:
            validate_jpeg(blob)
        except ContractViolation as e:
            fails.append(f"{ref}.jpg: {e}")
        if nbytes is not None and nbytes != len(blob):
            fails.append(f"{ref}.jpg: recorded {nbytes} bytes, file is {len(blob)}")
        sizes.append(len(blob))

    acts = []
    act_path = run_dir / "actions.jsonl"
    if act_path.exists():
        for i, line in enumerate(act_path.read_text().splitlines()):
            if not line.strip():
                continue
            a = json.loads(line)
            try:
                validate_action(a)          # also runs check_audit_arithmetic
                check_audit_arithmetic(a["audit"])
            except ContractViolation as e:
                fails.append(f"actions.jsonl:{i + 1}: {e}")
                continue
            acts.append(a)

    # sanity that no validator covers: the story the run tells has to hold together
    if obs:
        seqs = [o["seq"] for o in obs]
        if seqs != sorted(seqs):
            fails.append("observation seq numbers are not monotonic")
        budgets = [o["budget"]["remaining"] for o in obs]
        if any(b > a + 1e-6 for a, b in zip(budgets, budgets[1:])):
            fails.append("budget.remaining increased at some point (SIM owns it; it only drains)")
        confirmed = [len(o["mission"]["confirmed_markers"]) for o in obs]
        if any(b < a for a, b in zip(confirmed, confirmed[1:])):
            fails.append("confirmed_markers shrank")
        span = obs[-1]["sim_time"] - obs[0]["sim_time"]
        dist = sum(math.dist((a["pose"]["x"], a["pose"]["y"]), (b["pose"]["x"], b["pose"]["y"]))
                   for a, b in zip(obs, obs[1:]))
        print(f"observations  {len(obs):5d}   sim span {span:8.1f} s   path {dist:6.1f} m")
        print(f"frames        {len(sizes):5d}   jpeg {min(sizes) // 1024}-{max(sizes) // 1024} KB "
              f"(mean {sum(sizes) // max(len(sizes), 1) // 1024} KB)")
        print(f"budget        {budgets[0]:.1f} -> {budgets[-1]:.1f} Wh   "
              f"markers confirmed {obs[-1]['mission']['confirmed_markers']}")
    print(f"actions       {len(acts):5d}   decisions "
          f"{sorted(set(a['decision'] for a in acts))}")

    if fails:
        print(f"\nFAILED with {len(fails)} problem(s):")
        for f in fails[:20]:
            print("  -", f)
        return 1
    print("\nOK -- every message in this run satisfies interface-contract.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "runs/smoke")))
