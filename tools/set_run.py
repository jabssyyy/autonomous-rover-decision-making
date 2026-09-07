"""set_run.py -- switch the demo between the stay run and the deviate run.

interface-contract.md S9: "The two demo runs are the same binary with different config
+ start budget. Nothing else changes -- that's what makes it a policy and not a
script, and you should say exactly that."

So there is exactly ONE config.yaml, shared by SIM and BRAIN, and this rewrites the
two lines that differ. Nothing else in the file, the world seed included, is touched.

    python tools/set_run.py deviate     # healthy budget, eager: rover goes and looks
    python tools/set_run.py stay        # thin budget, cautious: rover stays on task
    python tools/set_run.py show

Restart SIM and BRAIN afterwards -- both read the file once at startup.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CFG = Path(__file__).resolve().parents[1] / "brain" / "config.yaml"

# Starting points, not gospel. brain.md S5.3 tunes these against the real utilities;
# SIM only needs the budget to be the thing that changes.
PRESETS = {
    "deviate": {"budget_start_wh": 1000.0, "gamma": 1.0},
    "stay": {"budget_start_wh": 420.0, "gamma": 3.0},
}
KEYS = ("budget_start_wh", "gamma")


def read_values(text: str) -> dict[str, str]:
    out = {}
    for k in KEYS:
        m = re.search(rf"^{k}:\s*([^\s#]+)", text, re.M)
        out[k] = m.group(1) if m else "?"
    return out


def main() -> int:
    if not CFG.exists():
        print(f"no config at {CFG}")
        return 2
    text = CFG.read_text()
    arg = sys.argv[1] if len(sys.argv) > 1 else "show"
    if arg == "show":
        cur = read_values(text)
        print(f"config.yaml: " + "  ".join(f"{k}={v}" for k, v in cur.items()))
        for name, vals in PRESETS.items():
            match = all(abs(float(cur[k]) - v) < 1e-6 for k, v in vals.items() if cur[k] != "?")
            print(f"  {name:8s} {vals}{'   <- current' if match else ''}")
        return 0
    if arg not in PRESETS:
        print(f"unknown run {arg!r}; pick one of {sorted(PRESETS)} or 'show'")
        return 2
    before = read_values(text)
    for k, v in PRESETS[arg].items():
        text, n = re.subn(rf"^({k}:\s*)[^\s#]+", lambda m: f"{m.group(1)}{v}", text, count=1, flags=re.M)
        if n == 0:
            print(f"key {k} not found in config.yaml -- add it first")
            return 1
    CFG.write_text(text)
    after = read_values(text)
    print(f"{arg} run set:")
    for k in KEYS:
        print(f"  {k}: {before[k]} -> {after[k]}")
    print("restart SIM and BRAIN; both read config.yaml once at startup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
