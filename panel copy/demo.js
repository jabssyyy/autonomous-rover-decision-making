/* ═══════════════════════════════════════════════════════════════════════
   panel/demo.js  —  SYNTHETIC MISSION SOURCE  (?demo=1 only)

   This file exists so the panel can be built, rehearsed and demonstrated
   with NO Godot, NO BRAIN and NO Jabin. It fabricates the whole mission:
   a small procedural world, a rover driving through it, a camera that
   renders what the rover sees, a policy that produces audit records whose
   arithmetic closes, and a genuine 60-second delay line in front of all of it.

   It is deliberately kept in its own file and is only ever loaded by
   app.js when ?demo=1 is on the URL, so there is never any doubt about
   which numbers on that screen came from a real rover.
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

const DEMO = (() => {

  /* ── deterministic RNG so every rehearsal is the same run ───────────── */
  let seed = 20260907;
  const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const rrange = (a, b) => a + rnd() * (b - a);
  const r2 = (x) => Math.round(x * 100) / 100;

  /* ── constants lifted from brain/config.yaml ────────────────────────── */
  const RATE_HZ        = 5;      // capture_rate_hz
  const HFOV           = 60;     // camera_hfov_deg
  const CAM_W = 640, CAM_H = 480;
  const CAM_HEIGHT_M   = 1.15;
  const SPEED          = 0.6;    // rover_max_speed_mps
  const YAW_RATE       = 25;     // rover_yaw_rate_dps
  const WH_PER_M       = 1.5;    // drive_rate_wh_per_m
  const WH_PER_DWELL_S = 0.05;   // dwell_wh_investigate, per SIM second
  const WH_IDLE_S      = 0.002;
  const MARGIN         = 1.15;   // mission_margin
  const ARRIVE_M       = 2.5;
  const HAZARD_STOP_M  = 2.0;    // hazard_stop_m — below this SIM steers around it

  let opt = null, world = null, R = null, queue = [], timer = null, povCv = null, cropCv = null;
  let cleanCv = null, lastFrameBoxes = [], croppedIds = new Set();

  /* ═══════════════════ world ═══════════════════ */

  function buildWorld() {
    const objs = [];
    // three mission markers, spread out along a rough arc
    const markers = ['M01', 'M02', 'M03'];
    markers.forEach((id, i) => {
      const a = -20 + i * 22 + rrange(-4, 4);
      const d = 14 + i * 16 + rrange(-3, 3);
      objs.push({ id, kind: 'marker', x: Math.sin(a * Math.PI / 180) * d, y: Math.cos(a * Math.PI / 180) * d,
                  w: 1.2, h: 1.2, post: 0.9, seedbits: (i * 37 + 11) });
    });
    // Curiosity targets — the things nobody told the rover to look at.
    // Three of them sit close to the route between the markers, which is what
    // puts the policy under actual tension: a cheap novel thing right there,
    // against an expensive assigned thing still far away.
    const anom = (x, y, n) => objs.push({
      id: 'A' + String(objs.filter((o) => o.kind === 'anomaly').length + 1).padStart(2, '0'),
      kind: 'anomaly', x, y, w: rrange(.6, 1.3), h: rrange(.5, 1.0),
      novelty: r2(n), hue: rrange(150, 215), visited: false });
    objs.filter((o) => o.kind === 'marker').forEach((m, i) => {
      const t = 0.55 + i * 0.05;
      const nx = -m.y / Math.hypot(m.x, m.y), ny = m.x / Math.hypot(m.x, m.y);
      anom(m.x * t + nx * rrange(1.8, 3.2), m.y * t + ny * rrange(1.8, 3.2), rrange(.84, .95));
    });
    for (let i = 0; i < 6; i++) {
      const a = rrange(-60, 70), d = rrange(9, 70);
      anom(Math.sin(a * Math.PI / 180) * d, Math.cos(a * Math.PI / 180) * d, rrange(.42, .88));
    }
    // plain rocks — clutter the perception stack has to reject
    for (let i = 0; i < 90; i++) {
      const a = rrange(-98, 98), d = 7 + Math.pow(rnd(), 1.6) * 105;   // clustered, but never underfoot
      objs.push({ id: 'r' + i, kind: 'rock',
                  x: Math.sin(a * Math.PI / 180) * d, y: Math.cos(a * Math.PI / 180) * d,
                  w: rrange(.3, 2.1), h: rrange(.25, 1.4), grey: rrange(.3, .62), lump: rnd() });
    }
    // far ridgeline, drawn once into the sky band
    const ridge = [];
    for (let i = 0; i <= 220; i++) ridge.push(rrange(0, 1));
    return { objs, ridge };
  }

  /* ═══════════════════ rover + policy ═══════════════════ */

  function newRover() {
    return {
      x: 0, y: 0, hdg: 0, simTime: 4200,
      budget: opt.budget, capacity: Math.max(1000, opt.budget),
      gamma: opt.gamma,
      state: 'AUTONOMOUS',
      confirmed: [],
      assigned: ['M01', 'M02', 'M03'],
      mode: 'drive',           // drive | investigate | survey | hold
      targetId: 'M01',
      dwellLeft: 0,
      halted: false,
      abortFlag: false,
      seq: 0,
      lastCropSim: -1e9,
    };
  }

  /* detection confidence by kind — see the note in visible() */
  function conf(kind, rg, salt) {
    const base = kind === 'marker' ? 1.40 - rg / 25 : 1.15 - rg / 55;
    return r2(Math.max(0.05, Math.min(0.95, base + Math.sin(R.simTime / 400 + salt) * 0.04)));
  }

  const bearingTo = (o) => {
    const dx = o.x - R.x, dy = o.y - R.y;
    let b = Math.atan2(dx, dy) * 180 / Math.PI - R.hdg;
    while (b > 180) b -= 360; while (b < -180) b += 360;
    return b;
  };
  const rangeTo = (o) => Math.hypot(o.x - R.x, o.y - R.y);

  /* what the camera can actually see — THE RULE: everything the policy uses
     below is derived from something inside the frustum, never from world.objs
     at large. (This is a stand-in for BRAIN's perception stack.) */
  function visible() {
    const out = [];
    for (const o of world.objs) {
      if (o.kind === 'rock') continue;
      if (o.kind === 'marker' && R.confirmed.includes(o.id)) continue;
      if (o.kind === 'anomaly' && o.visited) continue;
      const rg = rangeTo(o), br = bearingTo(o);
      if (rg > 70 || Math.abs(br) > HFOV / 2 - 2) continue;
      const c = conf(o.kind, rg, o.x);
      out.push({ o, rg, br, c: r2(c) });
    }
    return out;
  }

  /* the audit record — same shape and same closing arithmetic as
     brain/stub_brain.py::canned_audit and interface-contract.md §5 */
  function decide() {
    const vis = visible();
    const B = Math.max(1, R.budget);

    // cost of finishing the assigned markers from here (the mission reserve)
    let Breq = 0, cursor = { x: R.x, y: R.y };
    for (const id of R.assigned) {
      if (R.confirmed.includes(id)) continue;
      const m = world.objs.find((o) => o.id === id);
      if (!m) continue;
      Breq += Math.hypot(m.x - cursor.x, m.y - cursor.y) * WH_PER_M;
      cursor = m;
    }
    Breq = r2(Math.max(1, Breq));
    const slack = r2((B - Breq) / B);
    const w_c = r2(Math.pow(Math.max(0, slack), R.gamma));

    const cands = [];
    for (const v of vis) {
      // interface-contract.md §5: cost_est is the policy's cost estimate in cost
      // units (alpha_distance * distance + beta_time * dwell), NOT raw Wh — that
      // is what makes U = value_weighted / cost_est land in the range the
      // contract's own worked example shows.
      // A marker costs the drive PLUS the confirmation manoeuvre (approach on a
      // bearing, hold, decode). An anomaly in frame costs the short approach and
      // the dwell only — which is exactly why a cheap novel thing right there can
      // beat an expensive assigned thing still far away, but only when slack is
      // high enough to give curiosity any weight at all.
      const cost = r2(Math.max(0.2, v.rg / 10 + (v.o.kind === 'anomaly' ? 0.0 : 1.5)));
      if (v.o.kind === 'marker') {
        const p = 10;
        const raw = r2(p * v.c);
        cands.push({ id: v.o.id, stream: 'mission', p, c: v.c, value_raw: raw,
                     value_weighted: raw, cost_est: cost, U: r2(raw / cost), _v: v });
      } else {
        const raw = r2(v.o.novelty * v.c);
        const wgt = r2(w_c * raw);
        cands.push({ id: v.o.id, stream: 'curiosity', n: v.o.novelty, c: v.c, value_raw: raw,
                     value_weighted: wgt, cost_est: cost, U: r2(wgt / cost), _v: v });
      }
    }
    cands.sort((a, b) => b.U - a.U);
    const top = cands.slice(0, 4);

    let chosen = top.length ? top[0] : null;

    // the gate: never spend so much that the mission stops being affordable
    let gate = { result: 'pass', post_action_reserve: 99.99, margin: MARGIN };
    if (chosen) {
      const BreqAfter = Math.max(1, chosen.stream === 'mission' ? Breq - chosen.cost_est : Breq);
      const reserve = r2(Math.min(99.99, (B - chosen.cost_est) / BreqAfter));
      gate = { result: reserve >= MARGIN ? 'pass' : 'fail', post_action_reserve: reserve, margin: MARGIN };
      if (gate.result === 'fail') {
        const fallback = top.find((c) => c.stream === 'mission' && c.id !== chosen.id);
        chosen = fallback || null;
        if (chosen) {
          const ba = Math.max(1, Breq - chosen.cost_est);
          const rs = r2(Math.min(99.99, (B - chosen.cost_est) / ba));
          gate = { result: rs >= MARGIN ? 'pass' : 'fail', post_action_reserve: rs, margin: MARGIN };
        }
      }
    }

    const audit = {
      candidates: top.map(({ _v, ...c }) => c),
      budget: { remaining: r2(R.budget), required_for_mission: Breq },
      slack, gamma: R.gamma, w_curiosity: w_c,
      gate, chosen: chosen ? chosen.id : null,
      text: sentence(chosen, top, slack, w_c, gate),
    };
    return { audit, chosen };
  }

  /* BRAIN writes this sentence, not the panel. The demo writes it in the
     same voice so the log reads the way it will on the day. */
  function sentence(chosen, top, slack, w_c, gate) {
    if (!chosen) return 'Nothing in frame clears the utility floor. Continuing on heading and widening the search.';
    const other = top.find((c) => c.id !== chosen.id);
    const g = `slack ${slack.toFixed(2)} at gamma ${R.gamma.toFixed(1)} gives curiosity weight ${w_c.toFixed(2)}`;
    if (gate.result === 'fail')
      return `${chosen.id} (U=${chosen.U.toFixed(2)}) is the best value in frame, but the reserve gate fails: ` +
             `post-action reserve ${gate.post_action_reserve.toFixed(2)} is under margin ${MARGIN}. Holding the mission line.`;
    if (chosen.stream === 'mission') {
      if (!other) return `Marker ${chosen.id} (U=${chosen.U.toFixed(2)}) is the only candidate in frame. Staying on task.`;
      return `Marker ${chosen.id} (U=${chosen.U.toFixed(2)}) over ${other.id} (U=${other.U.toFixed(2)}). ` +
             (other.stream === 'curiosity'
               ? `Anomaly raw value ${other.value_raw.toFixed(2)}, but ${g} -> weighted ${other.value_weighted.toFixed(2)}. Staying on task.`
               : `Both are mission targets; ${chosen.id} is the cheaper commitment. Staying on task.`);
    }
    return `Anomaly ${chosen.id} (U=${chosen.U.toFixed(2)})` +
           (other ? ` over ${other.id} (U=${other.U.toFixed(2)})` : '') +
           `; ${g}, so an unassigned target is worth ${chosen.value_weighted.toFixed(2)} weighted. ` +
           `Gate ${gate.result} (reserve ${gate.post_action_reserve.toFixed(2)} vs margin ${MARGIN}). Deviating to investigate.`;
  }

  /* ═══════════════════ physics ═══════════════════ */

  function step(dtReal, dtSim) {
    if (R.halted) { R.budget = Math.max(0, R.budget - WH_IDLE_S * dtSim); R.state = 'AWAITING_UPLINK'; return decide(); }

    const d = decide();
    const chosen = d.chosen;

    if (R.mode === 'investigate') {
      R.dwellLeft -= dtSim;
      R.budget = Math.max(0, R.budget - WH_PER_DWELL_S * dtSim);
      if (R.abortFlag) { R.abortFlag = false; R.mode = 'drive'; R.dwellLeft = 0; }
      if (R.dwellLeft <= 0) {
        const a = world.objs.find((o) => o.id === R.targetId);
        if (a) a.visited = true;
        R.mode = 'drive';
      }
      return d;
    }

    if (chosen) {
      R.targetId = chosen.id;
      const o = world.objs.find((x) => x.id === chosen.id);
      if (o) {
        const br = bearingTo(o), rg = rangeTo(o);
        const turn = Math.max(-YAW_RATE * dtReal, Math.min(YAW_RATE * dtReal, br));
        R.hdg = (R.hdg + turn + 360) % 360;
        if (Math.abs(br) < 25) {
          // reactive obstacle avoidance — SIM's job, never BRAIN's (contract §3):
          // steer around the rock, keep the committed target.
          let steer = 0;
          for (const rk of world.objs) {
            if (rk.kind !== 'rock') continue;
            const rr = Math.hypot(rk.x - R.x, rk.y - R.y);
            if (rr > 4.5) continue;
            let rb = Math.atan2(rk.x - R.x, rk.y - R.y) * 180 / Math.PI - R.hdg;
            while (rb > 180) rb -= 360; while (rb < -180) rb += 360;
            if (Math.abs(rb) < 30) steer += (rb >= 0 ? -1 : 1) * (4.5 - rr) * 9;
          }
          R.hdg = (R.hdg + Math.max(-YAW_RATE * dtReal, Math.min(YAW_RATE * dtReal, steer)) + 360) % 360;
          const dist = SPEED * dtReal;
          R.x += Math.sin(R.hdg * Math.PI / 180) * dist;
          R.y += Math.cos(R.hdg * Math.PI / 180) * dist;
          R.budget = Math.max(0, R.budget - dist * WH_PER_M);
        }
        if (rg < ARRIVE_M) {
          if (o.kind === 'marker') {
            if (!R.confirmed.includes(o.id)) R.confirmed.push(o.id);
          } else {
            R.mode = 'investigate';
            R.dwellLeft = 25 + rnd() * 25;     // sim seconds of dwell — short on purpose:
          }                                    // it is what makes a late ABORT land stale
        }
      }
    } else {
      R.hdg = (R.hdg + 12 * dtReal) % 360;     // survey sweep
      R.budget = Math.max(0, R.budget - WH_IDLE_S * dtSim);
    }
    return d;
  }

  /* ═══════════════════ the camera ═══════════════════ */

  function renderPOV(snap) {
    const cv = povCv, ctx = cv.getContext('2d');
    const W = CAM_W, H = CAM_H;
    const fpx = (W / 2) / Math.tan(HFOV / 2 * Math.PI / 180);
    const horizon = H * 0.42;

    /* sky */
    const sky = ctx.createLinearGradient(0, 0, 0, horizon);
    sky.addColorStop(0, '#7d6448'); sky.addColorStop(.65, '#b5906a'); sky.addColorStop(1, '#d8b48a');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, horizon);

    /* ridgeline, parallaxed by heading */
    ctx.fillStyle = '#8a6b50'; ctx.beginPath(); ctx.moveTo(0, horizon);
    for (let i = 0; i <= W; i += 8) {
      const u = (i / W + snap.hdg / 360 * 2) * 200;
      const j = Math.floor(u) % world.ridge.length;
      const k = (j + world.ridge.length) % world.ridge.length;
      ctx.lineTo(i, horizon - 6 - world.ridge[k] * 22);
    }
    ctx.lineTo(W, horizon); ctx.closePath(); ctx.fill();

    /* ground */
    const gr = ctx.createLinearGradient(0, horizon, 0, H);
    gr.addColorStop(0, '#9c7550'); gr.addColorStop(.35, '#8a6242'); gr.addColorStop(1, '#5f4028');
    ctx.fillStyle = gr; ctx.fillRect(0, horizon, W, H - horizon);

    /* ground texture: regolith speckle, denser near the camera */
    for (let i = 0; i < 900; i++) {
      const y = horizon + Math.pow(Math.random(), 1.7) * (H - horizon);
      const x = Math.random() * W;
      const s = (y - horizon) / (H - horizon);
      ctx.fillStyle = `rgba(${Math.random() > .5 ? '40,26,16' : '190,150,110'},${.05 + s * .16})`;
      ctx.fillRect(x, y, 1 + s * 2.5, 1 + s * 1.6);
    }

    /* objects, far to near */
    const draw = [];
    for (const o of world.objs) {
      const dx = o.x - snap.x, dy = o.y - snap.y;
      const rg = Math.hypot(dx, dy);
      if (rg < HAZARD_STOP_M || rg > 140) continue;   // SIM steers around anything this close
      let br = Math.atan2(dx, dy) * 180 / Math.PI - snap.hdg;
      while (br > 180) br -= 360; while (br < -180) br += 360;
      if (Math.abs(br) > HFOV / 2 + 6) continue;
      const sx = W * (0.5 + br / HFOV);
      const base = horizon + fpx * CAM_HEIGHT_M / rg;
      const px = fpx / rg;                       // pixels per metre at this range
      draw.push({ o, rg, br, sx, base, px });
    }
    draw.sort((a, b) => b.rg - a.rg);

    const boxes = [];
    const preOverlay = [];
    for (const d of draw) {
      const { o, sx, base, px, rg } = d;
      const haze = Math.min(.7, rg / 150);
      if (o.kind === 'rock') {
        const w = o.w * px, h = o.h * px;
        if (w < .7) continue;
        ctx.save();
        ctx.globalAlpha = 1;
        const g = Math.floor(o.grey * 255);
        ctx.fillStyle = `rgb(${Math.floor(g * .92)},${Math.floor(g * .74)},${Math.floor(g * .56)})`;
        blob(ctx, sx, base - h / 2, w / 2, h / 2, o.lump);
        ctx.fillStyle = `rgba(0,0,0,.22)`;
        ctx.beginPath(); ctx.ellipse(sx, base, w * .6, h * .12, 0, 0, Math.PI * 2); ctx.fill();
        ctx.globalAlpha = haze; ctx.fillStyle = '#c49a72';
        blob(ctx, sx, base - h / 2, w / 2, h / 2, o.lump);
        ctx.restore();
      } else if (o.kind === 'anomaly') {
        const w = o.w * px, h = o.h * px;
        if (w < .7) continue;
        ctx.save();
        ctx.fillStyle = `hsl(${o.hue},22%,${28 + o.novelty * 14}%)`;
        blob(ctx, sx, base - h / 2, w / 2, h / 2, o.novelty);
        ctx.fillStyle = `hsl(${o.hue},34%,52%)`;
        ctx.globalAlpha = .5; blob(ctx, sx - w * .12, base - h * .62, w / 3.4, h / 3.4, o.novelty * .7);
        ctx.globalAlpha = haze; ctx.fillStyle = '#c49a72';
        blob(ctx, sx, base - h / 2, w / 2, h / 2, o.novelty);
        ctx.restore();
        if (w > 5 && !o.visited) boxes.push({ o, x: sx - w * .75, y: base - h * 1.15, w: w * 1.5, h: h * 1.25, rg });
      } else {
        /* fiducial marker board on a post */
        const w = o.w * px, h = o.h * px, post = o.post * px;
        if (w < 2) continue;
        ctx.fillStyle = '#4a4238';
        ctx.fillRect(sx - Math.max(1, w * .06), base - post, Math.max(1.5, w * .12), post);
        const bx = sx - w / 2, by = base - post - h;
        ctx.fillStyle = '#e9e4d8'; ctx.fillRect(bx, by, w, h);
        ctx.fillStyle = '#14110d';
        const n = 6, cell = w / n, cellH = h / n;
        ctx.fillRect(bx, by, w, cellH);
        ctx.fillRect(bx, by + h - cellH, w, cellH);
        ctx.fillRect(bx, by, cell, h);
        ctx.fillRect(bx + w - cell, by, cell, h);
        let bits = o.seedbits;
        for (let i = 1; i < n - 1; i++) for (let j = 1; j < n - 1; j++) {
          bits = (bits * 1103515245 + 12345) & 0x7fffffff;
          if ((bits >> 8) & 1) ctx.fillRect(bx + i * cell, by + j * cellH, cell, cellH);
        }
        ctx.globalAlpha = haze; ctx.fillStyle = '#c49a72'; ctx.fillRect(bx, by, w, h); ctx.globalAlpha = 1;
        if (w > 4 && !R.confirmed.includes(o.id)) boxes.push({ o, x: bx - 3, y: by - 3, w: w + 6, h: h + 6, rg });
      }
    }

    /* the crop is cut from the clean frame, before BRAIN paints its own boxes on it */
    lastFrameBoxes = boxes;
    cleanCv.getContext('2d').drawImage(cv, 0, 0);

    /* perception overlay — what BRAIN drew on the frame before downlinking it */
    ctx.lineWidth = 2; ctx.font = 'bold 12px ui-monospace, monospace'; ctx.textAlign = 'left';
    for (const b of boxes) {
      const marker = b.o.kind === 'marker';
      const col = marker ? '#2fe07a' : '#c78bff';
      ctx.strokeStyle = col; ctx.strokeRect(b.x, b.y, b.w, b.h);
      const label = marker ? `${b.o.id}  c=${conf('marker', b.rg, b.o.x).toFixed(2)}`
                           : `${b.o.id}  n=${b.o.novelty.toFixed(2)}`;
      const tw = ctx.measureText(label).width + 8;
      ctx.fillStyle = 'rgba(0,0,0,.72)'; ctx.fillRect(b.x, b.y - 15, tw, 15);
      ctx.fillStyle = col; ctx.fillText(label, b.x + 4, b.y - 4);
      ctx.strokeStyle = col; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(b.x + b.w / 2 - 5, b.y + b.h / 2); ctx.lineTo(b.x + b.w / 2 + 5, b.y + b.h / 2);
      ctx.moveTo(b.x + b.w / 2, b.y + b.h / 2 - 5); ctx.lineTo(b.x + b.w / 2, b.y + b.h / 2 + 5); ctx.stroke();
      ctx.lineWidth = 2;
    }

    /* sensor artefacts + burn-in */
    for (let i = 0; i < 260; i++) {
      ctx.fillStyle = `rgba(255,255,255,${Math.random() * .05})`;
      ctx.fillRect(Math.random() * W, Math.random() * H, 1, 1);
    }
    const vg = ctx.createRadialGradient(W / 2, H / 2, H * .3, W / 2, H / 2, H * .85);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(0,0,0,.45)');
    ctx.fillStyle = vg; ctx.fillRect(0, 0, W, H);

    ctx.font = '11px ui-monospace, monospace'; ctx.fillStyle = 'rgba(180,255,220,.75)';
    ctx.textAlign = 'left';
    ctx.fillText(`RCAM-A  ${W}x${H}  HFOV ${HFOV}`, 8, 16);
    ctx.fillText(`SIM ${snap.simTime.toFixed(1)}   SEQ ${snap.seq}`, 8, H - 8);
    ctx.textAlign = 'right';
    ctx.fillText(`X ${snap.x.toFixed(1)}  Y ${snap.y.toFixed(1)}  HDG ${snap.hdg.toFixed(1)}`, W - 8, H - 8);
    ctx.fillText(snap.mode === 'investigate' ? 'DWELL' : 'DRIVE', W - 8, 16);

    return boxes;
  }

  function blob(ctx, cx, cy, rx, ry, k) {
    ctx.beginPath();
    for (let i = 0; i <= 12; i++) {
      const a = i / 12 * Math.PI * 2;
      const w = 1 + Math.sin(a * 3 + k * 9) * .16 + Math.cos(a * 5 + k * 4) * .1;
      const x = cx + Math.cos(a) * rx * w, y = cy + Math.sin(a) * ry * w;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath(); ctx.fill();
  }

  const toBlob = (cv, q) => new Promise((res) => cv.toBlob(res, 'image/jpeg', q));

  /* ═══════════════════ the delay line ═══════════════════ */

  /* Deliveries are serialised: every canvas the renderer touches is shared, so
     two overlapping deliver() calls would cut a crop out of the wrong frame. */
  let delivering = Promise.resolve();
  function enqueueDelivery(item) { delivering = delivering.then(() => deliver(item)).catch(() => {}); }

  async function deliver(item) {
    /* ── all canvas work happens synchronously, before any await ── */
    const boxes = renderPOV(item.snap);
    const atts = [{ kind: 'thumbnail', frame_ref: 'f_' + item.snap.seq }];

    // downlink a crop when perception saw something novel enough to be worth the bits
    const cand = boxes.find((b) => b.o.kind === 'anomaly' && b.o.novelty > 0.6 && b.w > 22 && !croppedIds.has(b.o.id));
    const wantCrop = cand && item.snap.simTime - R.lastCropSim > 120;
    if (wantCrop) {
      croppedIds.add(cand.o.id);
      R.lastCropSim = item.snap.simTime;
      const c = cropCv.getContext('2d');
      c.fillStyle = '#000'; c.fillRect(0, 0, cropCv.width, cropCv.height);
      // square crop around the detection, cut from the clean frame
      const side = Math.max(96, cand.w, cand.h) * 1.35;
      const ccx = cand.x + cand.w / 2, ccy = cand.y + cand.h / 2;
      const sx = Math.max(0, Math.min(CAM_W - side, ccx - side / 2));
      const sy = Math.max(0, Math.min(CAM_H - side, ccy - side / 2));
      c.imageSmoothingQuality = 'high';
      c.drawImage(cleanCv, sx, sy, side, side, 0, 0, cropCv.width, cropCv.height);
      const k = cropCv.width / side;
      c.strokeStyle = '#c78bff'; c.lineWidth = 2;
      c.strokeRect((cand.x - sx) * k, (cand.y - sy) * k, cand.w * k, cand.h * k);
      atts.push({ kind: 'anomaly_crop', id: cand.o.id, novelty: cand.o.novelty });
    }

    const blobs = [await toBlob(povCv, 0.72)];
    if (wantCrop) blobs.push(await toBlob(cropCv, 0.82));

    const nowReal = performance.now() / 1000;
    const msg = {
      type: 'telemetry',
      generated_at: item.snap.simTime,
      delivered_at: R.simTime,                       // the rover's clock right now
      pose: { x: r2(item.snap.x), y: r2(item.snap.y), heading_deg: r2(item.snap.hdg) },
      state: item.snap.state,
      audit: item.audit,
      mission: { confirmed_markers: item.snap.confirmed.slice(), total: R.assigned.length },
      attachments: atts,
      clock: {
        generated_real_s: Math.round((nowReal - opt.delay) * 1000) / 1000,
        delivered_real_s: Math.round(nowReal * 1000) / 1000,
        delay_real_s: Math.round(opt.delay * 1000) / 1000,
      },
    };
    opt.onTelemetry(msg, blobs);
  }

  /* ═══════════════════ loop ═══════════════════ */

  function tick() {
    const dtReal = 1 / RATE_HZ;
    const dtSim = dtReal * opt.timeCompression;
    R.simTime += dtSim;
    R.seq++;
    const d = step(dtReal, dtSim);
    R.state = R.halted ? 'AWAITING_UPLINK' : 'AUTONOMOUS';
    const snap = { x: R.x, y: R.y, hdg: R.hdg, simTime: R.simTime, seq: R.seq,
                   state: R.state, confirmed: R.confirmed.slice(), mode: R.mode };
    queue.push({ snap, audit: d.audit, at: performance.now() + opt.delay * 1000 });

    while (queue.length && queue[0].at <= performance.now()) enqueueDelivery(queue.shift());
  }

  /* ═══════════════════ public ═══════════════════ */

  return {
    start(o) {
      opt = o;
      world = buildWorld();
      R = newRover();
      povCv = document.createElement('canvas'); povCv.width = CAM_W; povCv.height = CAM_H;
      cropCv = document.createElement('canvas'); cropCv.width = 256; cropCv.height = 256;
      cleanCv = document.createElement('canvas'); cleanCv.width = CAM_W; cleanCv.height = CAM_H;

      /* Prime the pipe: run the mission forward for one full delay's worth of
         time before the first packet is allowed to land. The screen then starts
         populated AND genuinely 60 s behind, which is what the real link does. */
      const n = Math.round(opt.delay * RATE_HZ);
      const t0 = performance.now();
      for (let i = 0; i < n; i++) {
        const dtReal = 1 / RATE_HZ, dtSim = dtReal * opt.timeCompression;
        R.simTime += dtSim; R.seq++;
        const d = step(dtReal, dtSim);
        queue.push({
          snap: { x: R.x, y: R.y, hdg: R.hdg, simTime: R.simTime, seq: R.seq,
                  state: 'AUTONOMOUS', confirmed: R.confirmed.slice(), mode: R.mode },
          audit: d.audit,
          at: t0 + i * (1000 / RATE_HZ),
        });
      }
      opt.onEvent('t', `demo world seeded · ${world.objs.length} objects · delay ${opt.delay}s · γ ${opt.gamma}`);
      timer = setInterval(tick, 1000 / RATE_HZ);
      setInterval(() => { while (queue.length && queue[0].at <= performance.now()) enqueueDelivery(queue.shift()); }, 40);
    },

    /* An uplink lands on the rover after the delay — and the panel is told
       nothing. It finds out one further delay later, from telemetry, exactly
       as it would from a real BRAIN. */
    uplink(msg, delayReal) {
      setTimeout(() => {
        const c = msg.command, p = msg.payload || {};
        if (c === 'halt') { R.halted = true; }
        else if (c === 'abort_investigation') { R.abortFlag = true; }
        else if (c === 'set_gamma') { R.gamma = p.gamma; }
        else if (c === 'ack_report') { R.halted = false; }
        else if (c === 'force_investigate') {
          const o = world.objs.find((x) => x.id === p.target);
          if (o) { R.targetId = o.id; o.visited = false; }
        } else if (c === 'reassign_markers') { R.assigned = p.assigned_markers; }
      }, delayReal * 1000);
    },
  };
})();
