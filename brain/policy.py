"""Budget-aware act-or-stay policy. Positions come only from vision and odometry."""
from __future__ import annotations
import math
from dataclasses import dataclass, field

@dataclass
class BrainState:
    mode: str = 'AUTONOMOUS'
    halted: bool = False
    gamma: float = 2.
    sim_time: float = 0.
    last_decision_sim: float = -1e9
    last_report_sim: float = 0.
    committed: str | None = None
    committed_at: float = -1e9
    investigating: str | None = None
    investigate_until_sim: float = 0.
    investigation: dict | None = None
    investigated: set = field(default_factory=set)
    visited: list = field(default_factory=list)
    aborted: list = field(default_factory=list)
    deferred: dict = field(default_factory=dict)
    marker_positions: dict = field(default_factory=dict)
    targets: dict = field(default_factory=dict)
    known_ids: set = field(default_factory=set)
    assigned_override: list | None = None
    notes: list = field(default_factory=list)
    decisions: int = 0

def clamp_gamma(value):
    if not math.isfinite(value):
        raise ValueError('gamma must be finite')
    return min(5., max(.1, float(value)))

def world_xy(pose, bearing_deg, range_m):
    a = math.radians(pose['heading_deg'] + bearing_deg)
    return pose['x'] + range_m * math.cos(a), pose['y'] + range_m * math.sin(a)

def rel_from(pose, x, y):
    dx, dy = x - pose['x'], y - pose['y']
    return math.hypot(dx, dy), (math.degrees(math.atan2(dy, dx)) - pose['heading_deg'] + 180) % 360 - 180

def estimate_cost(kind, est_range_m, cfg, pol):
    dwell = cfg['confirm_dwell_sim_s'] if kind == 'marker' else cfg['investigate_dwell_sim_s']
    return cfg['drive_rate_wh_per_m'] * max(0, est_range_m) + cfg['dwell_rate_wh_per_s'] * dwell

def cancel_investigation(st, reason):
    # An abort is not a completed observation, so it does not admit a memory.
    if st.investigation:
        st.aborted.append((st.investigation['xy'], st.sim_time + 30.))
    st.investigating, st.investigation, st.committed = None, None, None
    st.notes.append(reason)

def decide(res, st, cfg, pol):
    hdr, t = res.header, res.sim_time
    st.sim_time = t
    pose, B = hdr['pose'], float(hdr['budget']['remaining'])
    st.gamma = clamp_gamma(st.gamma)
    assigned = st.assigned_override if st.assigned_override is not None else hdr['mission']['assigned_markers']
    todo = [m for m in assigned if m not in hdr['mission']['confirmed_markers']]
    extras = {'protect_embedding': None}
    notes, st.notes = st.notes, []
    def visited(xy):
        return (any(math.dist(xy, old) <= pol['visited_radius_m'] for old in st.visited)
                or any(t < until and math.dist(xy, old) <= pol['visited_radius_m'] for old, until in st.aborted))
    # Complete first: the finished rock must not be chosen again this tick.
    if st.investigating and t >= st.investigate_until_sim:
        st.investigated.add(st.investigating)
        st.visited.append(st.investigation['xy'])
        extras['commit_embedding'] = st.investigating
        notes.append(f'Investigation of {st.investigating} complete; resuming mission.')
        st.deferred.pop(st.investigating, None)
        st.investigating, st.investigation, st.committed = None, None, None
    fresh, visible = set(), {}
    for d in res.detections:
        if not all(math.isfinite(v) for v in (d.conf, d.novelty, d.est_range_m, d.bearing_deg)):
            continue
        if not 0 <= d.est_range_m <= pol['max_target_range_m']:
            continue
        if d.kind == 'marker' and d.label not in todo:
            continue
        xy = world_xy(pose, d.bearing_deg, d.est_range_m)
        if d.kind != 'marker' and (d.id in st.investigated or visited(xy)):
            continue
        item = {'id': d.id, 'kind': d.kind, 'label': d.label, 'xy': xy,
                'c': min(1., max(0., d.conf)), 'n': min(1., max(0., d.novelty)), 'seen_at': t}
        visible[d.id] = st.targets[d.id] = item
        if d.kind == 'marker':
            st.marker_positions[d.label] = xy
        else:
            st.deferred[d.id] = item
        if d.id not in st.known_ids:
            fresh.add(d.id)
        st.known_ids.add(d.id)
    st.targets = {k: v for k, v in st.targets.items() if t - v['seen_at'] <= pol['target_ttl_s']}
    st.deferred = {k: v for k, v in st.deferred.items()
                   if t - v['seen_at'] <= pol['deferred_ttl_s'] and not visited(v['xy'])}
    def mission_required(origin, exclude=None):
        # Sum of straight-line estimates, not a route or a guarantee of real cost.
        total = 0.
        for marker in todo:
            if marker == exclude:
                continue
            xy = st.marker_positions.get(marker)
            distance = math.dist(origin, xy) if xy is not None else pol['assumed_marker_range_m']
            total += estimate_cost('marker', distance, cfg, pol)
        return total
    B_req = mission_required((pose['x'], pose['y']))
    slack = (B - B_req) / B if B > 0 else -1.
    wc = slack ** st.gamma if slack > 0 else 0.
    items = dict(st.deferred)
    if st.committed in st.targets:
        items[st.committed] = st.targets[st.committed]
    items.update(visible)
    if st.investigating:
        items[st.investigating] = st.investigation
    candidates = []
    for item in items.values():
        mission = item['kind'] == 'marker'
        if mission and item['label'] not in todo:
            continue
        distance, bearing = rel_from(pose, *item['xy'])
        if distance > pol['max_target_range_m']:
            continue
        cost = estimate_cost(item['kind'], distance, cfg, pol)
        if item['id'] == st.investigating:
            cost = max(0., st.investigate_until_sim - t) * cfg['dwell_rate_wh_per_s']
        req_after = mission_required(item['xy'], item['label'] if mission else None)
        eligible = B >= cost and B - cost >= req_after * cfg['mission_margin']
        raw = (10. if mission else pol['k_curiosity'] * item['n']) * item['c']
        weighted = raw if mission else wc * raw
        normalized = max(cost / pol['cost_unit_wh'], pol['cost_est_floor'])
        candidates.append({'id': item['id'], 'stream': 'mission' if mission else 'curiosity',
            **({'p': 10.} if mission else {'n': item['n'], 'k': pol['k_curiosity']}),
            'c': item['c'], 'value_raw': raw, 'value_weighted': weighted,
            'cost_wh': cost, 'cost_est': normalized, 'U': weighted / (normalized + pol['eps']),
            'eligible': eligible, 'required_for_mission_after': req_after,
            '_item': item, '_range': distance, '_bearing': bearing})
    candidates.sort(key=lambda c: (-c['U'], c['id']))
    eligible = [c for c in candidates if c['eligible'] and c['U'] > 0]
    chosen = eligible[0] if eligible else None
    if candidates and not candidates[0]['eligible']:
        notes.append(f"Reserve/affordability gate rejected {candidates[0]['id']}; every fallback was checked too.")
    current = next((c for c in eligible if c['id'] == st.committed), None)
    if current and chosen and current is not chosen:
        locked = t - st.committed_at < pol['commit_lock_s'] and chosen['id'] not in fresh
        if locked or chosen['U'] < current['U'] * pol['switch_ratio']:
            chosen = current
            notes.append('Keeping commitment: challenger did not satisfy the switch ratio/lock.')
    decision, speed = 'survey', 0.
    if st.halted or st.mode == 'AWAITING_UPLINK':
        chosen, decision = None, 'hold'
        if st.investigating:
            cancel_investigation(st, 'Investigation stopped by hold.')
    elif hdr['hazard']['range_m'] <= pol['hazard_stop_m'] or B <= 0:
        chosen, decision = None, 'hold'
        notes.append('Safety stop: close hazard or exhausted budget.')
        if st.investigating:
            cancel_investigation(st, 'Investigation stopped by safety veto.')
    elif st.investigating:
        chosen = next((c for c in candidates if c['id'] == st.investigating and c['eligible']), None)
        if chosen:
            decision = 'investigate'
        else:
            cancel_investigation(st, 'Investigation aborted: remaining dwell would violate reserve.')
            decision = 'hold'
    elif st.mode == 'REPORTING':
        st.mode, chosen, decision = 'AWAITING_UPLINK', None, 'hold'
    elif t - st.last_report_sim >= cfg['report_interval_sim_s']:
        st.mode, st.last_report_sim, chosen, decision = 'REPORTING', t, None, 'report'
    elif chosen:
        item = chosen['_item']
        if item['kind'] != 'marker' and chosen['id'] not in visible and chosen['_range'] <= pol['investigate_range_m']:
            chosen = None
            notes.append('Remembered target is nearby: survey to visually reacquire before acting.')
        elif item['kind'] != 'marker' and chosen['_range'] <= pol['investigate_range_m']:
            st.investigating, st.investigation = chosen['id'], dict(item)
            st.investigate_until_sim = t + cfg['investigate_dwell_sim_s']
            decision = 'investigate'
        else:
            decision, speed = 'drive_to_target', pol['cruise_speed']
    elif any(c['U'] > 0 for c in candidates) and not eligible:
        decision = 'hold'
        notes.append('No positive-value target passes the budget gate.')
    else:
        notes.append('No target in view; surveying.')
    heading, target = pose['heading_deg'], None
    if chosen:
        if st.committed != chosen['id']:
            st.committed, st.committed_at = chosen['id'], t
        item = chosen['_item']
        target = {'label': item['label'] if item['kind'] == 'marker' else chosen['id'],
                  'kind': item['kind'], 'bearing_deg': chosen['_bearing'], 'est_range_m': chosen['_range']}
        heading = (heading + chosen['_bearing']) % 360
        if item['kind'] != 'marker':
            extras['protect_embedding'] = chosen['id']
    else:
        st.committed = None
    cost = chosen['cost_wh'] if chosen else 0.
    req_after = chosen['required_for_mission_after'] if chosen else B_req
    reserve = B - cost
    gate = {'result': 'pass' if reserve >= req_after * cfg['mission_margin'] and reserve >= 0 else 'fail',
            'post_action_reserve': reserve / req_after if req_after > 0 else None,
            'margin': cfg['mission_margin'], 'cost_wh': cost,
            'required_for_mission_after': req_after, 'reserve_wh': reserve}
    text = (f"{decision}: {chosen['id']} (U={chosen['U']:.4f}). " if chosen else f'{decision}: no selected target. ')
    text += (f'Budget {B:.2f} Wh; mission estimate {B_req:.2f} Wh; slack {slack:.4f}; '
             f'curiosity weight {wc:.4f}. After selected cost {cost:.2f} Wh: '
             f"reserve {reserve:.2f} Wh vs required {req_after:.2f} x margin {cfg['mission_margin']:.2f}. ")
    text += ' '.join(notes + st.notes)
    st.notes.clear()
    audit = {'version': 2, 'candidates': [{k: v for k, v in c.items() if not k.startswith('_')} for c in candidates],
             'budget': {'remaining': B, 'required_for_mission': B_req}, 'slack': slack,
             'gamma': st.gamma, 'w_curiosity': wc, 'eps': pol['eps'],
             'cost_unit_wh': pol['cost_unit_wh'], 'cost_est_floor': pol['cost_est_floor'],
             'gate': gate, 'chosen': chosen['id'] if chosen else None, 'text': text}
    st.decisions += 1
    return {'type': 'action', 'in_reply_to_seq': res.seq, 'sim_time': t, 'decision': decision,
            'target': target, 'drive': {'heading_deg': heading % 360, 'speed': float(speed)}, 'audit': audit}, extras
