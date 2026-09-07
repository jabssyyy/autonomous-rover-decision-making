"""policy.py -- the slack-driven utility policy from novelty.md.

    M_i = p_i x c_i                 mission value   (p = 10 marker)
    C_i = n_i x c_i                 curiosity value (n = novelty in [0,1])
    Cost_i = alpha*d_i + beta*t_i   (Wh, BRAIN's estimate of SIM's rates)
    S = (B - B_req) / B ;  w_c = max(0,S)^gamma
    U_i = (M_i + w_c*C_i) / Cost_i ;  target* = argmax U_i
    gate: accept iff B - Cost(target*) >= B_req_after * margin, else best mission target

Emits ONE contract-valid action whose audit record closes arithmetically
(contract.check_audit_arithmetic is run on every action before it leaves BRAIN).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class BrainState:
    mode: str = "AUTONOMOUS"           # AUTONOMOUS | REPORTING | AWAITING_UPLINK
    halted: bool = False
    gamma: float = 2.0
    sim_time: float = 0.0              # onboard clock, ONLY ever set from observations
    last_decision_sim: float = -1e9
    last_report_sim: float = 0.0
    committed: str | None = None
    investigating: str | None = None
    investigate_until_sim: float = 0.0
    investigated: set = field(default_factory=set)
    deferred: dict = field(default_factory=dict)   # id -> {n, c, x, y, label}  (amplifier #3)
    assigned_override: list | None = None
    notes: list = field(default_factory=list)      # one-shot sentences for the next audit text
    empty_streak: int = 0
    decisions: int = 0


def r2(x: float) -> float:
    return round(float(x), 2)


def estimate_cost(kind: str, est_range_m: float, cfg: dict, pol: dict) -> float:
    drive = cfg["alpha_distance"] * est_range_m * pol["drive_wh_per_m"]
    dwell_s = pol["investigate_dwell_sim_s"] if kind != "marker" else pol["confirm_dwell_sim_s"]
    dwell = cfg["beta_time"] * dwell_s * pol["dwell_wh_per_sim_s"]
    return max(drive + dwell, pol["cost_floor_wh"])


def world_xy(pose: dict, bearing_deg: float, range_m: float) -> tuple[float, float]:
    a = math.radians(pose["heading_deg"] + bearing_deg)
    return pose["x"] + range_m * math.cos(a), pose["y"] + range_m * math.sin(a)


def rel_from(pose: dict, x: float, y: float) -> tuple[float, float]:
    dx, dy = x - pose["x"], y - pose["y"]
    b = (math.degrees(math.atan2(dy, dx)) - pose["heading_deg"] + 180.0) % 360.0 - 180.0
    return math.hypot(dx, dy), b


def _text(decision, chosen, cands, slack, gamma, w_c, fallback_note, notes) -> str:
    parts = []
    if chosen is None:
        parts.append("Nothing worth committing to in view." if not cands else "No affordable target in view.")
    else:
        kind = "Marker" if chosen["stream"] == "mission" else "Anomaly"
        head = f"{kind} {chosen['id']} (U={chosen['U']})"
        others = [c for c in cands if c["id"] != chosen["id"]][:2]
        if others:
            head += " over " + ", ".join(
                f"{'marker' if o['stream'] == 'mission' else 'anomaly'} {o['id']} (U={o['U']})" for o in others)
        parts.append(head + ".")
        top_cur = next((c for c in cands if c["stream"] == "curiosity"), None)
        if top_cur is not None:
            if chosen["stream"] == "mission":
                parts.append(f"Anomaly {top_cur['id']} raw value {top_cur['value_raw']}, but slack {slack} at gamma "
                             f"{gamma} gives curiosity weight {w_c} -> weighted {top_cur['value_weighted']}.")
            else:
                parts.append(f"Slack {slack} at gamma {gamma} gives curiosity weight {w_c}; weighted value "
                             f"{top_cur['value_weighted']} outranks the mission stream right now.")
    if fallback_note:
        parts.append(fallback_note)
    parts.append({
        "drive_to_target": "Staying on task." if chosen and chosen["stream"] == "mission" else "Deviating to investigate.",
        "investigate": "Investigating now.", "continue": "Continuing on heading.",
        "survey": "Surveying for targets.", "report": "Entering report window.", "hold": "Holding.",
    }[decision])
    parts.extend(notes)
    return " ".join(parts)


def decide(res, st: BrainState, cfg: dict, pol: dict) -> tuple[dict, dict]:
    """res: perception.PerceptionResult. Returns (action, extras)."""
    hdr, pose = res.header, res.header["pose"]
    B = hdr["budget"]["remaining"]
    assigned = st.assigned_override or hdr["mission"]["assigned_markers"]
    confirmed = hdr["mission"]["confirmed_markers"]
    todo = [m for m in assigned if m not in confirmed]
    seen = {d.id: d for d in res.detections}
    extras: dict = {}

    # --- slack: budget beyond what the assigned markers still need -------------
    def marker_cost(m: str) -> float:
        d = seen.get(m)
        return estimate_cost("marker", d.est_range_m if d else pol["assumed_marker_range_m"], cfg, pol)
    B_req = sum(marker_cost(m) for m in todo)
    slack = r2((B - B_req) / B) if B > 0 else -1.0
    w_c = r2(max(0.0, slack) ** st.gamma)

    # --- candidates: two value streams, one cost model --------------------------
    cands: list[dict] = []
    for d in res.detections:
        if d.kind == "marker":
            if d.label not in todo:
                continue
            cost = r2(estimate_cost("marker", d.est_range_m, cfg, pol))
            raw = r2(10 * d.conf)
            cands.append({"id": d.id, "stream": "mission", "p": 10, "c": d.conf, "value_raw": raw,
                          "value_weighted": raw, "cost_est": cost, "U": r2(raw / cost),
                          "_kind": "marker", "_bearing": d.bearing_deg, "_range": d.est_range_m, "_label": d.label})
        else:
            if d.id in st.investigated:
                continue
            cost = r2(estimate_cost(d.kind, d.est_range_m, cfg, pol))
            raw = r2(d.novelty * d.conf)
            wv = r2(w_c * raw)
            cands.append({"id": d.id, "stream": "curiosity", "n": d.novelty, "c": d.conf, "value_raw": raw,
                          "value_weighted": wv, "cost_est": cost, "U": r2(wv / cost),
                          "_kind": d.kind, "_bearing": d.bearing_deg, "_range": d.est_range_m, "_label": d.label})
            st.deferred.pop(d.id, None)          # visible again: fresh numbers replace the deferred copy
    for did, dd in list(st.deferred.items()):     # deferred-target queue (novelty.md amplifier #3)
        if did in seen or did in st.investigated:
            continue
        rng, b = rel_from(pose, dd["x"], dd["y"])
        cost = r2(estimate_cost("anomaly", rng, cfg, pol))
        raw = r2(dd["n"] * dd["c"])
        wv = r2(w_c * raw)
        cands.append({"id": did, "stream": "curiosity", "n": dd["n"], "c": dd["c"], "value_raw": raw,
                      "value_weighted": wv, "cost_est": cost, "U": r2(wv / cost),
                      "_kind": "anomaly", "_bearing": r2(b), "_range": r2(rng), "_label": dd["label"], "_deferred": True})
    cands.sort(key=lambda c: -c["U"])

    # --- argmax + hard gate ------------------------------------------------------
    chosen = None
    gate = {"result": "pass", "post_action_reserve": 99.99, "margin": cfg["mission_margin"]}
    fallback_note = ""
    if cands:
        best = cands[0]
        B_req_after = B_req - (best["cost_est"] if best["stream"] == "mission" else 0.0)
        reserve = r2(min(99.99, (B - best["cost_est"]) / max(B_req_after, pol["eps"])))
        result = "pass" if reserve >= cfg["mission_margin"] else "fail"
        gate = {"result": result, "post_action_reserve": reserve, "margin": cfg["mission_margin"]}
        if result == "pass":
            chosen = best
        else:
            missions = [c for c in cands if c["stream"] == "mission"]
            chosen = missions[0] if missions else None
            if best["stream"] == "curiosity" and not best.get("_deferred"):
                x, y = world_xy(pose, best["_bearing"], best["_range"])
                st.deferred[best["id"]] = {"n": best["n"], "c": best["c"], "x": x, "y": y, "label": best["_label"]}
            fallback_note = (f"Gate failed for {best['id']} (reserve {reserve} < margin {cfg['mission_margin']}); "
                             + (f"falling back to mission target {chosen['id']}." if chosen else "no mission target in view.")
                             + (f" {best['id']} queued for later." if best["stream"] == "curiosity" else ""))

    # --- decision --------------------------------------------------------------------
    heading = pose["heading_deg"]
    decision, target, speed = "continue", None, pol["cruise_speed"]
    if st.halted or st.mode == "AWAITING_UPLINK":
        decision, speed = "hold", 0.0
    elif st.mode == "REPORTING":
        st.mode, decision, speed = "AWAITING_UPLINK", "hold", 0.0
    elif res.sim_time - st.last_report_sim >= cfg["report_interval_sim_s"]:
        st.mode, st.last_report_sim, decision, speed = "REPORTING", res.sim_time, "report", 0.0
    elif st.investigating and res.sim_time < st.investigate_until_sim:
        d = seen.get(st.investigating)
        decision, speed = "investigate", 0.0
        target = {"label": st.investigating, "kind": d.kind if d else "anomaly",
                  "bearing_deg": d.bearing_deg if d else 0.0, "est_range_m": d.est_range_m if d else 0.0}
    else:
        if st.investigating:
            st.investigated.add(st.investigating)
            st.notes.append(f"Investigation of {st.investigating} complete; resuming mission.")
            st.investigating = None
        if chosen is None:
            st.empty_streak += 1
            if st.empty_streak >= pol["survey_after_n_empty"]:
                decision, speed, st.empty_streak = "survey", 0.0, 0
        else:
            st.empty_streak = 0
            kind = chosen["_kind"]
            target = {"label": chosen["_label"] if kind == "marker" else chosen["id"], "kind": kind,
                      "bearing_deg": r2(chosen["_bearing"]), "est_range_m": r2(chosen["_range"])}
            if kind != "marker" and chosen["_range"] <= pol["investigate_range_m"] and not chosen.get("_deferred"):
                decision, speed = "investigate", 0.0
                st.investigating, st.investigate_until_sim = chosen["id"], res.sim_time + pol["investigate_dwell_sim_s"]
                extras["commit_embedding"] = chosen["id"]      # habituation: it is in memory from now on
            else:
                decision = "drive_to_target"
                heading = (pose["heading_deg"] + chosen["_bearing"]) % 360.0
            st.committed = target["label"]

    text = _text(decision, chosen, cands, slack, st.gamma, w_c, fallback_note, st.notes)
    st.notes.clear()
    shown = cands[:8]
    if chosen is not None and chosen not in shown:
        shown.append(chosen)
    audit = {
        "candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in shown],
        "budget": {"remaining": r2(B), "required_for_mission": r2(B_req)},
        "slack": slack, "gamma": st.gamma, "w_curiosity": w_c, "gate": gate,
        "chosen": chosen["id"] if chosen else None, "text": text,
    }
    action = {"type": "action", "in_reply_to_seq": res.seq, "sim_time": res.sim_time, "decision": decision,
              "target": target, "drive": {"heading_deg": r2(heading % 360.0), "speed": float(speed)}, "audit": audit}
    st.decisions += 1
    return action, extras
