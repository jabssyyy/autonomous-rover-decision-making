"""contract.py -- executable form of interface-contract.md (v1, 2026-09-07).

Every message that crosses a process boundary goes through exactly one validator
here. An unknown key at ANY depth raises ContractViolation. That is how THE RULE
("BRAIN receives pixels, its own pose, and its own budget. Nothing else.") is
enforced by code rather than by good intentions.

Pure stdlib. Imported by stub_sim.py, stub_brain.py, stub_panel.py and main.py.
Run `python contract.py` to self-test against the examples in the contract.
"""
from __future__ import annotations

import math
from typing import Any

__all__ = [
    "ContractViolation", "Opt", "Nullable",
    "DECISIONS", "STATES", "UPLINK_COMMANDS", "TARGET_KINDS",
    "validate_observation", "validate_jpeg", "validate_action",
    "validate_telemetry", "validate_uplink", "check_audit_arithmetic",
]


class ContractViolation(ValueError):
    """Raised loudly. In BRAIN, never catch-and-continue on the SIM link: a
    violation means the other side is sending something the contract forbids."""


# --- frozen enums: do not extend without both builders agreeing ---------------
DECISIONS = frozenset({"drive_to_target", "investigate", "continue", "survey", "report", "hold"})
STATES = frozenset({"AUTONOMOUS", "REPORTING", "AWAITING_UPLINK"})
UPLINK_COMMANDS = frozenset({"ack_report", "reassign_markers", "abort_investigation",
                             "force_investigate", "set_gamma", "halt"})
TARGET_KINDS = frozenset({"marker", "anomaly", "rock"})
GATE_RESULTS = frozenset({"pass", "fail"})

# Diagnostics only: if an UNKNOWN observation key contains one of these substrings
# the error says "THE RULE VIOLATED" instead of "unknown key". The whitelist
# already rejects every unknown key regardless of its name.
_RULE_TRIPWIRES = ("object", "label", "class", "truth", "scene", "entit", "rock", "anomal",
                   "novel", "world", "graph", "depth", "segment", "mask", "position",
                   "target", "distance", "ground")


class Opt:
    """Key may be absent. If present it is validated against .spec."""
    __slots__ = ("spec",)

    def __init__(self, spec: Any) -> None:
        self.spec = spec


class Nullable:
    """Value may be JSON null; otherwise validated against .spec."""
    __slots__ = ("spec",)

    def __init__(self, spec: Any) -> None:
        self.spec = spec


def _fail(path: str, msg: str) -> None:
    raise ContractViolation(f"{path}: {msg}")


def _check(value: Any, spec: Any, path: str) -> None:
    """Spec mini-language: dict = EXACT key set; [spec] = homogeneous list;
    frozenset/tuple = string enum; float/int/str/bool = scalar; callable = custom."""
    if isinstance(spec, Nullable):
        if value is None:
            return
        spec = spec.spec
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            _fail(path, f"expected object, got {type(value).__name__}")
        extra = sorted(str(k) for k in set(value) - set(spec))
        if extra:
            k = extra[0]
            if path.startswith("observation") and any(t in k.lower() for t in _RULE_TRIPWIRES):
                _fail(f"{path}.{k}", "THE RULE VIOLATED. BRAIN receives pixels, its own pose, "
                                     "and its own budget. Nothing else. Remove this key from SIM.")
            _fail(f"{path}.{k}", f"unknown key {k!r}; allowed keys are {sorted(spec)}")
        for k, sub in spec.items():
            if k not in value:
                if isinstance(sub, Opt):
                    continue
                _fail(f"{path}.{k}", "missing required key")
            _check(value[k], sub.spec if isinstance(sub, Opt) else sub, f"{path}.{k}")
        return
    if isinstance(spec, list):
        if not isinstance(value, list):
            _fail(path, f"expected list, got {type(value).__name__}")
        for i, item in enumerate(value):
            _check(item, spec[0], f"{path}[{i}]")
        return
    if isinstance(spec, (frozenset, tuple)):
        if not isinstance(value, str) or value not in spec:
            _fail(path, f"{value!r} not in {sorted(spec)}")
        return
    if spec is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail(path, f"expected number, got {type(value).__name__}")
        if not math.isfinite(value):
            _fail(path, "number is not finite")
        return
    if spec is int:
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(path, f"expected integer, got {type(value).__name__}")
        return
    if spec is str:
        if not isinstance(value, str):
            _fail(path, f"expected string, got {type(value).__name__}")
        return
    if spec is bool:
        if not isinstance(value, bool):
            _fail(path, f"expected boolean, got {type(value).__name__}")
        return
    if callable(spec):
        spec(value, path)
        return
    raise TypeError(f"bad spec at {path}: {spec!r}")


# =============================================================================
# SECTION 2 -- SIM -> BRAIN : observation.  THE WHITELIST.
# =============================================================================
_POSE = {"x": float, "y": float, "heading_deg": float}

OBSERVATION = {
    "type": ("observation",),
    "seq": int,
    "sim_time": float,
    "pose": _POSE,
    "budget": {"remaining": float, "capacity": float, "unit": ("Wh",), "simulated": bool},
    "hazard": {"range_m": float, "bearing_deg": float},
    "mission": {"assigned_markers": [str], "confirmed_markers": [str]},
    "state": STATES,
    "camera": {"w": int, "h": int, "hfov_deg": float, "encoding": ("jpeg",)},
}


def validate_observation(msg: Any) -> dict:
    """Reject anything outside interface-contract.md section 2. Returns msg."""
    if not isinstance(msg, dict):
        raise ContractViolation("observation: not a JSON object")
    _check(msg, OBSERVATION, "observation")
    if msg["seq"] < 0:
        _fail("observation.seq", "must be >= 0")
    b = msg["budget"]
    if b["remaining"] < 0 or b["remaining"] > b["capacity"] + 1e-6:
        _fail("observation.budget.remaining", "must be within [0, capacity]")
    cam = msg["camera"]
    if cam["w"] <= 0 or cam["h"] <= 0 or not (10 <= cam["hfov_deg"] <= 170):
        _fail("observation.camera", "w/h must be > 0 and hfov_deg in [10, 170]")
    return msg


def validate_jpeg(data: Any, *, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    """The binary frame that follows an observation header must be one plain JPEG."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ContractViolation("frame: expected a BINARY frame after the observation header, got text")
    b = bytes(data)
    if len(b) < 4 or b[:2] != b"\xff\xd8":
        raise ContractViolation("frame: not a JPEG (missing SOI marker FFD8)")
    if b"\xff\xd9" not in b[-16:]:
        raise ContractViolation("frame: truncated JPEG (missing EOI marker FFD9)")
    if len(b) > max_bytes:
        raise ContractViolation(f"frame: {len(b)} bytes exceeds max {max_bytes}")
    return b


# =============================================================================
# SECTION 3 + 5 -- BRAIN -> SIM : action (with audit)
# =============================================================================
_TARGET = {"label": str, "kind": TARGET_KINDS, "bearing_deg": float, "est_range_m": float}

_CAND_MISSION = {"id": str, "stream": ("mission",), "p": float, "c": float,
                 "value_raw": float, "value_weighted": float, "cost_est": float, "U": float}
_CAND_CURIOSITY = {"id": str, "stream": ("curiosity",), "n": float, "c": float,
                   "value_raw": float, "value_weighted": float, "cost_est": float, "U": float}


def _candidate(v: Any, path: str) -> None:
    if not isinstance(v, dict) or "stream" not in v:
        _fail(path, "candidate must be an object with a 'stream' key")
    if v["stream"] == "mission":
        _check(v, _CAND_MISSION, path)
    elif v["stream"] == "curiosity":
        _check(v, _CAND_CURIOSITY, path)
    else:
        _fail(f"{path}.stream", f"{v['stream']!r} not in ['curiosity', 'mission']")


AUDIT_V1 = {
    "candidates": [_candidate],
    "budget": {"remaining": float, "required_for_mission": float},
    "slack": float,
    "gamma": float,
    "w_curiosity": float,
    "gate": {"result": GATE_RESULTS, "post_action_reserve": float, "margin": float},
    "chosen": Nullable(str),
    "text": str,
}


def _candidate_v2(v, path):
    base = _CAND_MISSION if isinstance(v, dict) and v.get("stream") == "mission" else _CAND_CURIOSITY
    spec = {**base, "cost_wh": float, "eligible": bool, "required_for_mission_after": float}
    if base is _CAND_CURIOSITY:
        spec["k"] = float
    _check(v, spec, path)


AUDIT_V2 = {**AUDIT_V1, "version": int, "candidates": [_candidate_v2],
            "eps": float, "cost_unit_wh": float, "cost_est_floor": float,
            "gate": {"result": GATE_RESULTS, "post_action_reserve": Nullable(float),
                     "margin": float, "cost_wh": float,
                     "required_for_mission_after": float, "reserve_wh": float}}


def AUDIT(value, path):
    if isinstance(value, dict) and "version" in value:
        if value["version"] != 2:
            _fail(path, "unsupported audit version")
        _check(value, AUDIT_V2, path)
    else:
        _check(value, AUDIT_V1, path)  # old recordings and canned stub remain readable


def check_v2(a):
    B, required = a["budget"]["remaining"], a["budget"]["required_for_mission"]
    def equal(actual, expected, name):
        if not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8):
            _fail("audit." + name, f"{actual} != {expected}")
    if B < 0 or required < 0 or not .1 <= a["gamma"] <= 5:
        _fail("audit", "negative budget/reserve or gamma outside [0.1,5]")
    if a["eps"] <= 0 or a["cost_unit_wh"] <= 0 or a["cost_est_floor"] <= 0 or a["gate"]["margin"] < 1:
        _fail("audit", "invalid cost scaling, epsilon, or margin")
    equal(a["slack"], (B - required) / B if B > 0 else -1., "slack")
    equal(a["w_curiosity"], a["slack"] ** a["gamma"] if a["slack"] > 0 else 0., "w_curiosity")
    candidates = {}
    for c in a["candidates"]:
        if c["id"] in candidates:
            _fail("audit.candidates", "duplicate candidate id")
        candidates[c["id"]] = c
        if c["cost_wh"] < 0 or c["required_for_mission_after"] < 0 or not 0 <= c["c"] <= 1:
            _fail("audit.candidates", "invalid cost, reserve, or confidence")
        mission = c["stream"] == "mission"
        if not mission and (not 0 <= c["n"] <= 1 or c["k"] < 0):
            _fail("audit.candidates", "invalid novelty or curiosity scale")
        raw = (c["p"] if mission else c["k"] * c["n"]) * c["c"]
        equal(c["value_raw"], raw, "value_raw")
        equal(c["value_weighted"], raw if mission else raw * a["w_curiosity"], "value_weighted")
        equal(c["cost_est"], max(c["cost_wh"] / a["cost_unit_wh"], a["cost_est_floor"]), "cost_est")
        equal(c["U"], c["value_weighted"] / (c["cost_est"] + a["eps"]), "U")
        eligible = B >= c["cost_wh"] and B - c["cost_wh"] >= c["required_for_mission_after"] * a["gate"]["margin"]
        if eligible != c["eligible"]:
            _fail("audit.eligible", "does not match affordability/reserve calculation")
    chosen = candidates.get(a["chosen"])
    if a["chosen"] is not None and (chosen is None or not chosen["eligible"]):
        _fail("audit.chosen", "missing or ineligible candidate selected")
    g = a["gate"]
    equal(g["cost_wh"], chosen["cost_wh"] if chosen else 0., "gate.cost_wh")
    equal(g["required_for_mission_after"], chosen["required_for_mission_after"] if chosen else required, "gate.required_for_mission_after")
    equal(g["reserve_wh"], B - g["cost_wh"], "gate.reserve_wh")
    if g["required_for_mission_after"] > 0:
        if g["post_action_reserve"] is None:
            _fail("audit.gate", "reserve ratio required with nonzero denominator")
        equal(g["post_action_reserve"], g["reserve_wh"] / g["required_for_mission_after"], "gate.post_action_reserve")
    elif g["post_action_reserve"] is not None:
        _fail("audit.gate", "zero mission requirement must have null ratio")
    passed = g["reserve_wh"] >= 0 and g["reserve_wh"] >= g["required_for_mission_after"] * g["margin"]
    if g["result"] != ("pass" if passed else "fail"):
        _fail("audit.gate.result", "does not match Wh reserve calculation")

ACTION = {
    "type": ("action",),
    "in_reply_to_seq": int,
    "sim_time": float,
    "decision": DECISIONS,
    "target": Nullable(_TARGET),
    "drive": {"heading_deg": float, "speed": float},
    "audit": AUDIT,
}


def _close(a: float, b: float) -> bool:
    # values are emitted rounded to 2-3 decimals; allow that plus 1 % relative
    return abs(a - b) <= 0.011 + 0.01 * abs(b)


def check_audit_arithmetic(audit: dict) -> None:
    """'Arithmetic must close, and a judge may check it.' So we check it first."""
    if audit.get("version") == 2:
        check_v2(audit)
        return
    B = audit["budget"]["remaining"]
    B_req = audit["budget"]["required_for_mission"]
    if B > 0 and not _close(audit["slack"], (B - B_req) / B):
        _fail("audit.slack", f"{audit['slack']} != (remaining - required)/remaining = {(B - B_req) / B:.4f}")
    w_c = max(0.0, audit["slack"]) ** audit["gamma"]
    if not _close(audit["w_curiosity"], w_c):
        _fail("audit.w_curiosity", f"{audit['w_curiosity']} != max(0, slack)^gamma = {w_c:.4f}")
    ids = set()
    for i, c in enumerate(audit["candidates"]):
        p = f"audit.candidates[{i}]"
        mission = c["stream"] == "mission"
        raw = (c["p"] if mission else c["n"]) * c["c"]
        if not _close(c["value_raw"], raw):
            _fail(f"{p}.value_raw", f"{c['value_raw']} != {'p' if mission else 'n'} x c = {raw:.4f}")
        weighted = c["value_raw"] if mission else audit["w_curiosity"] * c["value_raw"]
        if not _close(c["value_weighted"], weighted):
            _fail(f"{p}.value_weighted", f"{c['value_weighted']} != {weighted:.4f}")
        if c["cost_est"] <= 0:
            _fail(f"{p}.cost_est", "must be > 0")
        if not _close(c["U"], c["value_weighted"] / c["cost_est"]):
            _fail(f"{p}.U", f"{c['U']} != value_weighted / cost_est = {c['value_weighted'] / c['cost_est']:.4f}")
        if c["id"] in ids:
            _fail(f"{p}.id", "duplicate candidate id")
        ids.add(c["id"])
    if audit["chosen"] is not None and audit["chosen"] not in ids:
        _fail("audit.chosen", f"{audit['chosen']!r} is not a candidate id")
    g = audit["gate"]
    expected = "pass" if g["post_action_reserve"] >= g["margin"] else "fail"
    if g["result"] != expected:
        _fail("audit.gate.result", f"{g['result']!r} but post_action_reserve {g['post_action_reserve']} "
                                   f"vs margin {g['margin']} implies {expected!r}")


def validate_action(msg: Any) -> dict:
    if not isinstance(msg, dict):
        raise ContractViolation("action: not a JSON object")
    _check(msg, ACTION, "action")
    if msg["decision"] in ("drive_to_target", "investigate") and msg["target"] is None:
        _fail("action.target", f"required when decision is {msg['decision']!r}")
    if not (0.0 <= msg["drive"]["speed"] <= 1.0):
        _fail("action.drive.speed", "must be in [0, 1]")
    check_audit_arithmetic(msg["audit"])
    if msg["audit"].get("version") == 2:
        label = msg["target"]["label"] if msg["target"] else None
        if label != msg["audit"]["chosen"]:
            _fail("action.target", "must match the audited selected target")
        if msg["decision"] in ("hold", "survey", "report") and (label is not None or msg["drive"]["speed"] != 0):
            _fail("action", "hold/survey/report must have no target and zero speed")
    return msg


# =============================================================================
# SECTION 6 -- BRAIN -> PANEL : telemetry (DELAYED)
# =============================================================================
def _attachment(v: Any, path: str) -> None:
    kind = v.get("kind") if isinstance(v, dict) else None
    if kind == "thumbnail":
        _check(v, {"kind": ("thumbnail",), "frame_ref": str}, path)
    elif kind == "anomaly_crop":
        _check(v, {"kind": ("anomaly_crop",), "id": str, "novelty": float}, path)
    else:
        _fail(path, "attachment.kind must be 'thumbnail' or 'anomaly_crop'")


TELEMETRY = {
    "type": ("telemetry",),
    "generated_at": float,
    "delivered_at": float,
    "pose": _POSE,
    "state": STATES,
    "audit": AUDIT,
    "mission": {"confirmed_markers": [str], "total": int},
    "attachments": [_attachment],
    # ADDITIVE (proposed v1.1): real-clock stamps so the panel can prove the delay
    # in REAL seconds. Optional; a panel may ignore it.
    "clock": Opt({"generated_real_s": float, "delivered_real_s": float, "delay_real_s": float}),
}


def validate_telemetry(msg: Any) -> dict:
    if not isinstance(msg, dict):
        raise ContractViolation("telemetry: not a JSON object")
    _check(msg, TELEMETRY, "telemetry")
    check_audit_arithmetic(msg["audit"])
    return msg


# =============================================================================
# SECTION 7 -- PANEL -> BRAIN : uplink (DELAYED)
# =============================================================================
def _any_object(v: Any, path: str) -> None:
    if not isinstance(v, dict):
        _fail(path, "expected object")


UPLINK = {
    "type": ("uplink",),
    "issued_at": float,
    "arrives_at": float,
    "command": UPLINK_COMMANDS,
    "payload": _any_object,
}

_PAYLOADS = {
    "reassign_markers": {"assigned_markers": [str], "reason": Opt(str)},
    "set_gamma": {"gamma": float, "reason": Opt(str)},
    "force_investigate": {"target": str, "reason": Opt(str)},
}
_PAYLOAD_DEFAULT = {"reason": Opt(str)}


def validate_uplink(msg: Any) -> dict:
    if not isinstance(msg, dict):
        raise ContractViolation("uplink: not a JSON object")
    _check(msg, UPLINK, "uplink")
    _check(msg["payload"], _PAYLOADS.get(msg["command"], _PAYLOAD_DEFAULT), "uplink.payload")
    return msg


# =============================================================================
# self-test: the literal examples from interface-contract.md must pass,
# and the things THE RULE forbids must fail loudly.
# =============================================================================
EXAMPLE_OBSERVATION = {
    "type": "observation", "seq": 1423, "sim_time": 4821.5,
    "pose": {"x": 132.4, "y": 88.1, "heading_deg": 47.2},
    "budget": {"remaining": 742.0, "capacity": 1000.0, "unit": "Wh", "simulated": True},
    "hazard": {"range_m": 3.8, "bearing_deg": 2.0},
    "mission": {"assigned_markers": ["M01", "M02", "M03"], "confirmed_markers": ["M01"]},
    "state": "AUTONOMOUS",
    "camera": {"w": 640, "h": 480, "hfov_deg": 60, "encoding": "jpeg"},
}
EXAMPLE_AUDIT = {
    "candidates": [
        {"id": "M02", "stream": "mission", "p": 10, "c": 0.58, "value_raw": 5.80,
         "value_weighted": 5.80, "cost_est": 3.31, "U": 1.75},
        {"id": "A07", "stream": "curiosity", "n": 0.82, "c": 0.71, "value_raw": 0.58,
         "value_weighted": 0.07, "cost_est": 1.14, "U": 0.06},
    ],
    "budget": {"remaining": 742.0, "required_for_mission": 490.0},
    "slack": 0.34, "gamma": 2.0, "w_curiosity": 0.12,
    "gate": {"result": "pass", "post_action_reserve": 1.52, "margin": 1.15},
    "chosen": "M02",
    "text": "Marker M02 (U=1.75) over anomaly A07 (U=0.06). Anomaly raw value 0.58, but slack 0.34 "
            "at gamma 2 gives curiosity weight 0.12 -> weighted 0.07. Staying on task.",
}
EXAMPLE_ACTION = {
    "type": "action", "in_reply_to_seq": 1423, "sim_time": 4821.5, "decision": "drive_to_target",
    "target": {"label": "M02", "kind": "marker", "bearing_deg": 12.4, "est_range_m": 18.2},
    "drive": {"heading_deg": 59.6, "speed": 0.6},
    "audit": EXAMPLE_AUDIT,
}
EXAMPLE_TELEMETRY = {
    "type": "telemetry", "generated_at": 4821.5, "delivered_at": 4881.5,
    "pose": {"x": 132.4, "y": 88.1, "heading_deg": 47.2}, "state": "AUTONOMOUS",
    "audit": EXAMPLE_AUDIT, "mission": {"confirmed_markers": ["M01"], "total": 3},
    "attachments": [{"kind": "thumbnail", "frame_ref": "f_1423"},
                    {"kind": "anomaly_crop", "id": "A07", "novelty": 0.82}],
}
EXAMPLE_UPLINK = {"type": "uplink", "issued_at": 4820.0, "arrives_at": 4880.0,
                  "command": "abort_investigation", "payload": {"reason": "operator override"}}


def _selftest() -> None:
    import copy
    validate_observation(EXAMPLE_OBSERVATION)
    validate_action(EXAMPLE_ACTION)
    validate_telemetry(EXAMPLE_TELEMETRY)
    validate_uplink(EXAMPLE_UPLINK)
    validate_jpeg(b"\xff\xd8\xff\xe0" + b"\x00" * 10 + b"\xff\xd9")

    def must_fail(fn, msg, needle):
        try:
            fn(msg)
        except ContractViolation as e:
            assert needle in str(e), f"wrong error: {e}"
            return
        raise AssertionError(f"accepted something it must reject: {needle}")

    bad = copy.deepcopy(EXAMPLE_OBSERVATION); bad["objects"] = [{"class": "rock", "x": 1}]
    must_fail(validate_observation, bad, "THE RULE VIOLATED")
    bad = copy.deepcopy(EXAMPLE_OBSERVATION); bad["pose"]["z"] = 0.0
    must_fail(validate_observation, bad, "unknown key 'z'")
    bad = copy.deepcopy(EXAMPLE_OBSERVATION); bad["mission"]["marker_positions"] = {}
    must_fail(validate_observation, bad, "THE RULE VIOLATED")
    bad = copy.deepcopy(EXAMPLE_OBSERVATION); del bad["hazard"]
    must_fail(validate_observation, bad, "missing required key")
    bad = copy.deepcopy(EXAMPLE_OBSERVATION); bad["state"] = "TELEPORTING"
    must_fail(validate_observation, bad, "not in")
    bad = copy.deepcopy(EXAMPLE_ACTION); bad["decision"] = "teleport"
    must_fail(validate_action, bad, "not in")
    bad = copy.deepcopy(EXAMPLE_ACTION); bad["audit"]["candidates"][1]["U"] = 0.5
    must_fail(validate_action, bad, "audit.candidates[1].U")
    bad = copy.deepcopy(EXAMPLE_ACTION); bad["audit"]["gate"]["result"] = "fail"
    must_fail(validate_action, bad, "audit.gate.result")
    bad = copy.deepcopy(EXAMPLE_ACTION); bad["audit"]["chosen"] = "M99"
    must_fail(validate_action, bad, "audit.chosen")
    bad = copy.deepcopy(EXAMPLE_ACTION); bad["target"] = None
    must_fail(validate_action, bad, "action.target")
    bad = copy.deepcopy(EXAMPLE_UPLINK); bad["command"] = "drive_here"
    must_fail(validate_uplink, bad, "not in")
    bad = copy.deepcopy(EXAMPLE_UPLINK); bad["command"] = "set_gamma"
    must_fail(validate_uplink, bad, "uplink.payload.gamma")
    must_fail(validate_jpeg, b"\x89PNG....", "not a JPEG")
    print("contract.py self-test: OK (contract examples pass; forbidden inputs are rejected)")


if __name__ == "__main__":
    _selftest()
