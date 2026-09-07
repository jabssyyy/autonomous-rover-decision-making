/* ═══════════════════════════════════════════════════════════════════════
   MISSION CONTROL — EARTH   ·   panel/app.js
   Vanilla JS. No framework, no bundler, no CDN.

   Speaks interface-contract.md §6 (telemetry, DELAYED) and §7 (uplink).
   Wire format, exactly as brain/stub_brain.py emits it:
       1 JSON text frame  (type:"telemetry", attachments:[...])
       N binary frames    (one JPEG per attachment, in attachments order)

   TWO RULES THIS FILE OBEYS
     1. The delay is NEVER computed from this machine's clock. It comes from
        BRAIN's own two stamps (telemetry.clock.*). Date.now() is used only
        for the cosmetic "arrived Ns ago" counter and for local countdowns.
     2. This screen never shows a live feed. Everything here is 60 s old and
        says so. The gap between this screen and Jabin's IS the argument.
   ═══════════════════════════════════════════════════════════════════════ */
'use strict';

/* ───────────────────────── config / boot ───────────────────────── */

const QS = new URLSearchParams(location.search);

const CFG = {
  // ws:// endpoint. Priority: ?ws= → ?host= → the host that served this page.
  // NEVER hardcode localhost: the page is served from Jabin's laptop and opened
  // on the Mac, so "localhost" would point the Mac at itself (panel.md §8).
  wsUrl: (() => {
    if (QS.get('ws')) return QS.get('ws');
    const host = QS.get('host') || location.hostname || '127.0.0.1';
    const port = QS.get('port') || '8766';
    return `ws://${host}:${port}`;
  })(),
  timeCompression: Number(QS.get('tc') || 1),   // config.yaml time_compression
  fallbackDelay:   Number(QS.get('delay') || 60), // config.yaml comms_delay_real_s
  capacityWh:      Number(QS.get('cap') || 1000), // config.yaml budget_capacity_wh
  demo:            QS.get('demo') === '1',
  logMax:          80,
  cropMax:         10,
};

const $  = (id) => document.getElementById(id);
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; };
const f  = (v, n = 2) => (Number.isFinite(v) ? v.toFixed(n) : '—');
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/* ───────────────────────── mission state ───────────────────────── */

const S = {
  connected: false,
  source: 'none',            // 'live' | 'demo' | 'none'
  packets: 0,
  last: null,                // last telemetry object
  lastArrivedMs: 0,          // Date.now() of arrival — cosmetic only
  delay: null,               // authoritative, from BRAIN's stamps
  delays: [],                // history of measured delays
  trail: [],                 // [{x,y,h}] delayed ground track
  pins: [],                  // marker-confirmation positions
  trackLen: 0,
  confirmed: [],
  markerTotal: 0,
  capacity: CFG.capacityWh,
  thumbUrl: null,
  crops: [],                 // [{id, novelty, url}]
  pending: null,             // telemetry awaiting its binary frames
  pendingIdx: 0,
  flights: [],               // uplink commands in flight
  lastCard: null,
  cards: 0,
  drainRef: null,
};

/* ───────────────────────── link ───────────────────────── */

let ws = null, reconnectTimer = null, everConnected = false;

function connect() {
  if (CFG.demo) { startDemo(); return; }
  if (location.protocol === 'file:' && !QS.get('ws') && !QS.get('host')) {
    setLink('bad', 'NO LINK', 'opened from file:// — append ?demo=1 to preview, or serve from BRAIN');
    logEvent('bad', 'file:// — no websocket host. ?demo=1 for a dry run.');
    return;
  }
  setLink('', 'CONNECTING', CFG.wsUrl);
  try { ws = new WebSocket(CFG.wsUrl); } catch (e) { scheduleReconnect(); return; }
  ws.binaryType = 'blob';

  ws.onopen = () => {
    everConnected = true;
    S.connected = true; S.source = 'live';
    setLink('ok', 'LINK OK', CFG.wsUrl);
    logEvent('ok', `downlink established · ${CFG.wsUrl}`);
    toast('DOWNLINK ESTABLISHED');
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') onText(ev.data);
    else onBinary(ev.data);
  };
  ws.onclose = () => {
    if (S.connected) { logEvent('bad', 'downlink lost'); toast('DOWNLINK LOST', 'bad'); }
    S.connected = false;
    S.pending = null; S.pendingIdx = 0;
    setLink('bad', 'LINK LOST', `retrying ${CFG.wsUrl}`);
    scheduleReconnect();
  };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, 1000);   // campus wifi will drop. panel.md §7
}

function setLink(cls, state, sub) {
  const led = $('linkLed'), st = $('linkState');
  led.className = 'led' + (cls ? ' ' + cls : '');
  st.className = 'link-state' + (cls ? ' ' + cls : '');
  st.textContent = state;
  $('linkSub').textContent = sub;
}

/* ───────────────────────── inbound messages ───────────────────────── */

function onText(raw) {
  let msg;
  try { msg = JSON.parse(raw); } catch (e) { logEvent('bad', 'malformed JSON frame'); return; }

  if (msg.type === 'telemetry') { onTelemetry(msg); return; }

  // Optional, additive: if BRAIN ever reports the fate of an uplink directly,
  // its verdict beats the panel's inference.
  if (msg.type === 'uplink_ack' || msg.type === 'uplink_event') {
    resolveFlight(msg.command, msg.result === 'uplink_stale' ? 'stale' : 'applied',
                  msg.note || msg.result, null, true);
    return;
  }
  logEvent('t', `ignored message type "${msg.type}"`);
}

function onTelemetry(t) {
  if (!t.audit || !t.pose) { logEvent('bad', 'telemetry missing audit/pose'); return; }

  S.packets++;
  S.last = t;
  S.lastArrivedMs = Date.now();
  S.pending = t; S.pendingIdx = 0;

  /* ── THE DELAY. BRAIN's clock, both stamps, never ours. ────────────── */
  let d = null;
  if (t.clock && Number.isFinite(t.clock.delay_real_s)) {
    d = t.clock.delay_real_s;                                     // authoritative
  } else if (Number.isFinite(t.delivered_at) && Number.isFinite(t.generated_at)) {
    d = (t.delivered_at - t.generated_at) / CFG.timeCompression;  // sim-s → real-s
  }
  if (Number.isFinite(d) && d >= 0) {
    S.delay = d;
    S.delays.push(d); if (S.delays.length > 300) S.delays.shift();
    spawnLaneGhost(d);
  }

  /* ── ground track (from the delayed pose — the only track Earth has) ── */
  const p = t.pose;
  const prev = S.trail[S.trail.length - 1];
  if (!prev || Math.hypot(p.x - prev.x, p.y - prev.y) > 0.05) {
    if (prev) S.trackLen += Math.hypot(p.x - prev.x, p.y - prev.y);
    S.trail.push({ x: p.x, y: p.y, h: p.heading_deg });
    if (S.trail.length > 4000) S.trail.shift();
  }

  /* ── marker confirmations ── */
  const conf = (t.mission && t.mission.confirmed_markers) || [];
  for (const m of conf) {
    if (!S.confirmed.includes(m)) {
      S.confirmed.push(m);
      S.pins.push({ x: p.x, y: p.y, id: m });
      logEvent('ok', `marker ${m} CONFIRMED (as of ${fmtMet(t.generated_at)})`);
      toast(`MARKER ${m} CONFIRMED — 60 s AGO`);
    }
  }
  if (t.mission && Number.isFinite(t.mission.total)) S.markerTotal = t.mission.total;

  /* ── budget bookkeeping ── */
  const rem = t.audit.budget.remaining;
  if (rem > S.capacity) S.capacity = Math.ceil(rem / 100) * 100;
  trackDrain(t.generated_at, rem);

  renderAll(t);
  appendDecision(t);
  checkFlights(t);
}

/* binary frames arrive in the order of the preceding message's attachments */
function onBinary(blob) {
  const t = S.pending;
  if (!t || S.pendingIdx >= (t.attachments || []).length) return;   // unexpected blob
  const att = t.attachments[S.pendingIdx++];
  const url = URL.createObjectURL(blob);

  if (att.kind === 'thumbnail') {
    if (S.thumbUrl) URL.revokeObjectURL(S.thumbUrl);
    S.thumbUrl = url;
    const img = $('vpImg');
    img.src = url; img.classList.add('on');
    $('vpNoImg').style.display = 'none';
    img.onload = drawVpHud;
  } else if (att.kind === 'anomaly_crop') {
    S.crops.unshift({ id: att.id, novelty: att.novelty, url });
    while (S.crops.length > CFG.cropMax) { const c = S.crops.pop(); URL.revokeObjectURL(c.url); }
    renderCrops();
  } else {
    URL.revokeObjectURL(url);
  }
}

/* ───────────────────────── render: header ───────────────────────── */

function renderAll(t) {
  const a = t.audit;

  $('delayValue').textContent = S.delay == null ? '--.-' : f(S.delay, 1);
  $('laneDelay').textContent  = S.delay == null ? CFG.fallbackDelay : Math.round(S.delay);
  $('upDelayTxt').textContent = S.delay == null ? CFG.fallbackDelay : Math.round(S.delay);
  if (S.delays.length > 2) {
    const mn = Math.min(...S.delays), mx = Math.max(...S.delays);
    $('delaySpread').textContent = `jitter ${f(mx - mn, 2)} s over ${S.delays.length} pkt`;
  }
  $('pktCount').textContent = S.packets;
  $('clkMet').textContent = fmtMet(t.generated_at);
  $('metTag').textContent = (S.delay == null ? CFG.fallbackDelay : Math.round(S.delay)) + 's OLD';

  /* vehicle */
  $('stateBadge').textContent = t.state;
  $('stateBadge').className = 'statebadge ' + t.state;
  const kind = decisionKind(t);
  $('lastDecision').textContent = kind.label;
  $('lastDecision').style.color = kind.color;
  $('lastTarget').textContent = a.chosen || '— none —';
  $('poX').textContent = f(t.pose.x, 1);
  $('poY').textContent = f(t.pose.y, 1);
  $('poH').textContent = f(t.pose.heading_deg, 1);
  $('poD').textContent = f(S.trackLen, 1);
  drawRose(t.pose.heading_deg);

  /* power */
  const rem = a.budget.remaining, req = a.budget.required_for_mission;
  const pct = clamp(rem / S.capacity, 0, 1), reqPct = clamp(req / S.capacity, 0, 1);
  $('powWh').textContent = f(rem, 0);
  $('powCap').textContent = f(S.capacity, 0);
  $('powCapTxt').textContent = f(S.capacity, 0);
  $('powReqTxt').textContent = `mission reserve ${f(req, 0)}`;
  $('powFill').style.width = (pct * 100) + '%';
  $('powReq').style.width = (reqPct * 100) + '%';
  $('powSlack').textContent = f(a.slack, 2);
  $('powGamma').textContent = f(a.gamma, 1);
  $('powWc').textContent = f(a.w_curiosity, 3);
  const pp = $('pPower');
  pp.classList.toggle('low',  rem < req * 1.35 && rem >= req * 1.05);
  pp.classList.toggle('crit', rem < req * 1.05);
  drawCurve(a.gamma, a.slack, a.w_curiosity);

  /* mission markers */
  renderMarkers();

  /* link quality */
  if (S.delays.length) {
    const mean = S.delays.reduce((s, v) => s + v, 0) / S.delays.length;
    $('lqMean').textContent = f(mean, 2);
    $('lqMin').textContent  = f(Math.min(...S.delays), 2);
    $('lqMax').textContent  = f(Math.max(...S.delays), 2);
    $('lqJit').textContent  = f(Math.max(...S.delays) - Math.min(...S.delays), 2);
    drawSparkline();
  }

  /* viewport stamps */
  $('vpGen').textContent = 'sim ' + f(t.generated_at, 1);
  $('vpArr').textContent = '+' + f(S.delay ?? 0, 1) + 's';
  drawVpHud();
  drawMap();
}

function renderMarkers() {
  const wrap = $('markerDots');
  const total = Math.max(S.markerTotal, S.confirmed.length);
  if (wrap.childElementCount !== total) {
    wrap.innerHTML = '';
    for (let i = 0; i < total; i++) wrap.appendChild(el('div', 'mk'));
  }
  // telemetry carries the confirmed ids and a count, never the assigned list —
  // so name the ones we know and leave the rest blank rather than guessing.
  [...wrap.children].forEach((n, i) => {
    const done = i < S.confirmed.length;
    n.classList.toggle('done', done);
    n.textContent = done ? S.confirmed[i] : '· ·';
  });
  $('markerCount').textContent = `${S.confirmed.length} / ${total}`;
  $('markerList').textContent = S.confirmed.length ? S.confirmed.join(' · ') : 'none';
}

function renderCrops() {
  const strip = $('cropStrip');
  strip.innerHTML = '';
  if (!S.crops.length) { strip.appendChild(el('div', 'crop-empty', 'NO ANOMALY CROPS DOWNLINKED')); return; }
  S.crops.forEach((c, i) => {
    const d = el('div', 'crop' + (i === 0 ? ' fresh' : ''));
    const im = new Image(); im.src = c.url; d.appendChild(im);
    const m = el('div', 'crop-meta');
    m.appendChild(el('div', 'crop-id', c.id));
    m.appendChild(el('div', 'crop-n', 'novelty ' + f(c.novelty, 2)));
    const b = el('div', 'nbar'); b.style.width = clamp(c.novelty, 0, 1) * 100 + '%';
    m.appendChild(b); d.appendChild(m);
    strip.appendChild(d);
  });
}

/* ───────────────────────── the decision log ─────────────────────────
   panel.md §4: render the ARITHMETIC, not a summary. A judge must be able
   to check U = value_weighted / cost_est by hand. So the panel recomputes
   every number independently and marks each row ✓ or ✗ — if BRAIN's own
   numbers ever failed to close, this screen would say so out loud.
   ───────────────────────────────────────────────────────────────────── */

function decisionKind(t) {
  const actualDecision = t.decision || (t.audit?.version === 2 ? t.audit.text.split(':', 1)[0] : null);
  if (actualDecision) {                               // if BRAIN ever adds it, use it
    const map = {
      drive_to_target: ['COMMIT — DRIVE', 'var(--cyan)', 'drive_to_target'],
      investigate:     ['DEVIATE — INVESTIGATE', 'var(--violet)', 'investigate'],
      survey:          ['SURVEY', 'var(--amber)', 'survey'],
      report:          ['REPORT WINDOW', 'var(--blue)', 'report'],
      hold:            ['HOLD', 'var(--red)', 'hold'],
      continue:        ['CONTINUE ON HEADING', 'var(--ink-dim)', 'continue'],
    };
    const m = map[actualDecision];
    if (m) return { label: m[0], color: m[1], cls: m[2], key: actualDecision };
  }
  const a = t.audit;
  if (!a.chosen) return { label: 'CONTINUE ON HEADING', color: 'var(--ink-dim)', cls: 'continue', key: 'continue' };
  const c = a.candidates.find((x) => x.id === a.chosen);
  if (c && c.stream === 'curiosity') {
    // Only a real deviation if a mission candidate was on the table and lost.
    // With no marker in frame, choosing the anomaly gave nothing up.
    const gaveUp = a.candidates.some((x) => x.stream === 'mission');
    return gaveUp
      ? { label: 'DEVIATE — CURIOSITY', color: 'var(--violet)', cls: 'investigate', key: 'deviate' }
      : { label: 'CURIOSITY — NO MARKER IN FRAME', color: 'var(--violet)', cls: 'curiosity_only', key: 'curiosity_only' };
  }
  const contested = a.candidates.some((x) => x.stream === 'curiosity');
  return contested
    ? { label: 'STAY ON TASK — MISSION', color: 'var(--cyan)', cls: 'drive_to_target', key: 'stay' }
    : { label: 'MISSION — UNCONTESTED', color: 'var(--cyan)', cls: 'drive_to_target', key: 'mission_only' };
}

function appendDecision(t) {
  const a = t.audit;
  const kind = decisionKind(t);
  const key = kind.key + '|' + (a.chosen || '') + '|' + a.gate.result;

  const scroll = $('logScroll');
  const emptyEl = scroll.querySelector('.log-empty');
  if (emptyEl) emptyEl.remove();

  // coalesce: while the rover holds the same decision, update the card in place
  // and count the packets, instead of flooding 5 Hz of identical cards.
  const heldTooLong = S.lastCard && (S.lastCard.n >= 40 || t.generated_at - S.lastCard.tStart > 600);
  if ($('chkOnlyCommits').checked && S.lastCard && S.lastCard.key === key && !heldTooLong) {
    S.lastCard.n++;
    S.lastCard.tEnd = t.generated_at;
    fillCard(S.lastCard.node, t, kind, S.lastCard);
    return;
  }

  const node = el('div', 'card d-' + kind.cls);
  const rec = { key, n: 1, node, tStart: t.generated_at, tEnd: t.generated_at };
  fillCard(node, t, kind, rec);
  scroll.insertBefore(node, scroll.firstChild);
  S.lastCard = rec;
  S.cards++;
  $('logCount').textContent = S.cards;
  while (scroll.childElementCount > CFG.logMax) scroll.removeChild(scroll.lastChild);
}

function fillCard(node, t, kind, rec) {
  const a = t.audit;
  node.innerHTML = '';

  /* header row */
  const h = el('div', 'card-h');
  h.appendChild(el('span', 'card-t', 'sim ' + f(t.generated_at, 1)));
  h.appendChild(el('span', 'card-d', kind.label));
  const chosen = el('span', 'card-c', a.chosen || '—');
  h.appendChild(chosen);
  node.appendChild(h);

  if (rec.n > 1) {
    const held = el('div', 'card-t');
    held.textContent = `held ${rec.n} packets · sim ${f(rec.tStart, 0)} → ${f(rec.tEnd, 0)} (${f(rec.tEnd - rec.tStart, 0)} sim-s)`;
    node.appendChild(held);
  }

  /* the rover's own sentence — BRAIN writes this, not the panel */
  node.appendChild(el('div', 'card-text', a.text));

  /* candidates table: every column a judge needs to redo the arithmetic */
  const tbl = el('table', 'cand');
  const thead = el('thead');
  const hr = el('tr');
  ['CAND', 'STREAM', 'p / n', 'c', 'VAL RAW', '× w', 'VAL WGT', 'COST', 'U', ''].forEach((x) => hr.appendChild(el('th', null, x)));
  thead.appendChild(hr); tbl.appendChild(thead);

  const tb = el('tbody');
  const maxU = Math.max(1e-6, ...a.candidates.map((c) => c.U));
  for (const c of a.candidates) {
    const tr = el('tr', c.stream + (c.id === a.chosen ? ' chosen' : ''));
    const mission = c.stream === 'mission';

    // independent recomputation — the panel checks BRAIN's homework
    const rawExp = (mission ? c.p : (a.version === 2 ? c.k : 1) * c.n) * c.c;
    const wgtExp = mission ? c.value_raw : a.w_curiosity * c.value_raw;
    const uExp   = c.value_weighted / (c.cost_est + (a.version === 2 ? a.eps : 0));
    const ok = close(c.value_raw, rawExp) && close(c.value_weighted, wgtExp) && close(c.U, uExp);

    tr.appendChild(el('td', null, c.id));
    tr.appendChild(el('td', null, mission ? 'MIS' : 'CUR'));
    tr.appendChild(el('td', null, f(mission ? c.p : c.n, 2)));
    tr.appendChild(el('td', null, f(c.c, 2)));
    tr.appendChild(el('td', null, f(c.value_raw, 2)));
    tr.appendChild(el('td', mission ? null : 'wgt', mission ? '1.00' : f(a.w_curiosity, 3)));
    tr.appendChild(el('td', mission ? null : 'wgt', f(c.value_weighted, 2)));
    tr.appendChild(el('td', null, f(c.cost_est, 2)));

    const tdU = el('td', 'u');
    tdU.appendChild(document.createTextNode(f(c.U, 2)));
    const bar = el('span', 'ubar');
    bar.style.width = clamp(c.U / maxU, 0, 1) * 100 + '%';
    bar.style.color = mission ? 'var(--cyan)' : 'var(--violet)';
    tdU.appendChild(bar);
    tr.appendChild(tdU);

    tr.appendChild(el('td', ok ? 'chk-ok' : 'chk-bad', ok ? '✓' : '✗'));
    tb.appendChild(tr);
  }
  tbl.appendChild(tb);
  node.appendChild(tbl);

  /* the slack line — where the policy lives */
  const B = a.budget.remaining, Br = a.budget.required_for_mission;
  const s = el('div', 'card-slack');
  s.innerHTML =
    `slack <b>${f(a.slack, 2)}</b> = (${f(B, 0)} − ${f(Br, 0)}) / ${f(B, 0)}` +
    `<span>γ <b>${f(a.gamma, 1)}</b></span>` +
    `<span>w_cur <b>${f(a.w_curiosity, 3)}</b> = ${f(Math.max(0, a.slack), 2)}<sup>${f(a.gamma, 1)}</sup></span>`;
  node.appendChild(s);

  /* the gate */
  const g = el('div', 'card-gate');
  const pill = el('span', 'gatepill ' + a.gate.result, 'GATE ' + a.gate.result.toUpperCase());
  g.appendChild(pill);
  g.appendChild(el('span', 'dim',
    `post-action reserve ${f(a.gate.post_action_reserve, 2)} ${a.gate.post_action_reserve >= a.gate.margin ? '≥' : '<'} margin ${f(a.gate.margin, 2)}`));
  node.appendChild(g);

  if (!close(a.w_curiosity, Math.pow(Math.max(0, a.slack), a.gamma))) {
    node.appendChild(el('div', 'card-flag', '✗ w_curiosity does not equal slack^γ — arithmetic does not close'));
  }
}

/* rounded-to-2dp tolerance, matching brain/contract.py::_close */
const close = (a, b) => Math.abs(a - b) <= 0.011 + 0.01 * Math.abs(b);

/* ───────────────────────── uplink (§7) ───────────────────────── */

function sendUplink(command) {
  if (!S.last) {
    toast('NO TELEMETRY YET — CANNOT STAMP A COMMAND', 'bad');
    logEvent('bad', `uplink ${command} refused — no rover clock to issue against`);
    return;
  }
  const payload = { reason: 'operator override' };

  if (command === 'set_gamma') {
    const v = prompt('SET γ — curiosity temperament (high = cautious, low = eager)', String(S.last?.audit.gamma ?? 2.0));
    if (v === null) return;
    payload.gamma = Number(v);
    if (!Number.isFinite(payload.gamma)) { toast('γ must be a number', 'bad'); return; }
  } else if (command === 'force_investigate') {
    const guess = S.crops[0]?.id || S.last?.audit.candidates.find((c) => c.stream === 'curiosity')?.id || '';
    const v = prompt('FORCE INVESTIGATE — target id', guess);
    if (!v) return;
    payload.target = String(v);
  } else if (command === 'reassign_markers') {
    const v = prompt('REASSIGN MARKERS — comma separated', 'M01,M02,M03');
    if (!v) return;
    payload.assigned_markers = v.split(',').map((x) => x.trim()).filter(Boolean);
  }

  // The rover's clock, as of the last thing we heard. stub_panel.py does the same.
  const issued = S.last.delivered_at ?? S.last.generated_at;
  const delayReal = S.delay ?? CFG.fallbackDelay;
  const msg = {
    type: 'uplink',
    issued_at: issued,
    arrives_at: issued + delayReal * CFG.timeCompression,   // sim seconds
    command,
    payload,
  };

  if (CFG.demo) {
    DEMO.uplink(msg, delayReal);
  } else if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  } else {
    toast('NO LINK — COMMAND NOT SENT', 'bad');
    logEvent('bad', `uplink ${command} FAILED — no link`);
    return;
  }

  const now = Date.now();
  S.flights.push({
    command, payload,
    issuedSim: issued,
    sentMs: now,
    landMs: now + delayReal * 1000,
    arriveSim: msg.arrives_at,
    delayReal,
    state: 'flight',        // flight → landed → applied|stale
    note: '',
  });
  spawnLaneUplink(delayReal);
  logEvent('up', `uplink ${command} sent · lands in ${Math.round(delayReal)} s`);
  toast(`COMMAND SENT — ARRIVES IN ${Math.round(delayReal)}s`, 'warn');
  renderFlights();
}

/* Verdict. We cannot know at launch whether the command will matter; we cannot
   even know at landing. We find out one further delay later, when telemetry
   generated AFTER the arrival time finally reaches Earth. That two-delay wait
   is the honest shape of the problem and the panel shows it that way. */
function checkFlights(t) {
  for (const fl of S.flights) {
    if (fl.state === 'applied' || fl.state === 'stale') continue;
    if (CFG.demo) continue; // Synthetic source resolves its own command callbacks.

    // BRAIN publishes the command outcome in its delayed audit sentence.
    // A missing investigation cannot distinguish a successful abort from a stale one.
    const outcome = new RegExp('Uplink ' + fl.command + ' (landed stale|applied) at sim ([0-9.]+) [(]issued at ([0-9.]+)[)]').exec(t.audit.text || '');
    if (!outcome || Math.abs(Number(outcome[3]) - fl.issuedSim) > 1) continue;
    fl.arriveSim = Number(outcome[2]);
    resolveFlight(fl.command, outcome[1] === 'landed stale' ? 'stale' : 'applied', outcome[0], fl, true);
  }
}

function resolveFlight(command, verdict, note, fl, fromBrain) {
  fl = fl || S.flights.slice().reverse().find((x) => x.command === command && x.state !== 'applied' && x.state !== 'stale');
  if (!fl) return;
  fl.state = verdict; fl.note = note; fl.fromBrain = !!fromBrain;
  renderFlights();
  if (verdict === 'stale') {
    logEvent('bad', `UPLINK STALE — ${command}: ${note}`);
    showStale(fl);
  } else {
    logEvent('ok', `uplink ${command} applied — ${note}`);
    toast(`UPLINK ${command.toUpperCase()} APPLIED`);
  }
}

function showStale(fl) {
  $('staleBody').innerHTML =
    `Command <b>${fl.command}</b> was issued at rover-time <b>sim ${f(fl.issuedSim, 1)}</b> ` +
    `and reached the rover <b>${Math.round(fl.delayReal)} real seconds later</b>, at sim ${f(fl.arriveSim, 1)}.<br><br>` +
    (fl.fromBrain
      ? `BRAIN reported <b>uplink_stale</b>: ${fl.note}.<br><br>`
      : `The telemetry that has just reached Earth shows ${fl.note} — so BRAIN will have logged ` +
        `<b>uplink_stale</b> and carried on.<br><br>`) +
    `You have just learned this a further ${Math.round(fl.delayReal)} seconds after the fact.`;
  $('staleAlarm').hidden = false;
}

function renderFlights() {
  const box = $('upFlight');
  box.innerHTML = '';
  const live = S.flights.slice(-4);
  if (!live.length) { box.appendChild(el('div', 'up-idle', 'NO COMMANDS IN FLIGHT')); return; }
  for (const fl of live) {
    const d = el('div', 'flt ' + (fl.state === 'flight' ? '' : fl.state === 'landed' ? 'landed' : fl.state));
    d.appendChild(el('span', 'fc', fl.command.replace(/_/g, ' ').toUpperCase()));
    const t = el('span', 'ft');
    const bar = el('div', 'fbar'); const bi = el('i'); bar.appendChild(bi);
    if (fl.state === 'flight') {
      const left = Math.max(0, (fl.landMs - Date.now()) / 1000);
      t.textContent = 'T−' + f(left, 1) + 's';
      bi.style.width = clamp(1 - left / fl.delayReal, 0, 1) * 100 + '%';
    } else if (fl.state === 'landed') {
      t.textContent = 'LANDED';
      bi.style.width = '100%';
    } else {
      t.textContent = fl.state === 'stale' ? 'STALE' : 'APPLIED';
      bi.style.width = '100%';
    }
    d.appendChild(bar); d.appendChild(t);
    d.title = fl.note || '';
    box.appendChild(d);
  }
}

/* ───────────────────────── canvases ───────────────────────── */

function fit(cv) {
  const r = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, r.width, r.height);
  return { ctx, w: r.width, h: r.height };
}
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/* heading rose */
function drawRose(hdg) {
  const { ctx, w, h } = fit($('roseCanvas'));
  const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 3;
  ctx.strokeStyle = css('--line-hot'); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = css('--ink-faint'); ctx.font = '7px ui-monospace, monospace'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (let a = 0; a < 360; a += 30) {
    const r0 = a % 90 === 0 ? R - 5 : R - 3;
    const rad = (a - 90) * Math.PI / 180;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(rad) * r0, cy + Math.sin(rad) * r0);
    ctx.lineTo(cx + Math.cos(rad) * R, cy + Math.sin(rad) * R);
    ctx.stroke();
  }
  ctx.fillText('N', cx, cy - R + 6);
  const rad = ((hdg ?? 0) - 90) * Math.PI / 180;
  ctx.strokeStyle = css('--cyan'); ctx.fillStyle = css('--cyan'); ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + Math.cos(rad) * (R - 6), cy + Math.sin(rad) * (R - 6)); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, 2, 0, Math.PI * 2); ctx.fill();
}

/* w = slack^gamma */
function drawCurve(gamma, slack, wc) {
  const { ctx, w, h } = fit($('curveCanvas'));
  const pad = 4;
  ctx.strokeStyle = 'rgba(255,255,255,.07)'; ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = pad + (h - 2 * pad) * i / 4;
    ctx.beginPath(); ctx.moveTo(pad, y); ctx.lineTo(w - pad, y); ctx.stroke();
  }
  ctx.strokeStyle = css('--violet'); ctx.lineWidth = 1.6; ctx.beginPath();
  for (let i = 0; i <= 100; i++) {
    const s = i / 100, y = Math.pow(s, gamma || 2);
    const px = pad + s * (w - 2 * pad), py = h - pad - y * (h - 2 * pad);
    i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
  }
  ctx.stroke();
  const s = clamp(slack, 0, 1);
  const px = pad + s * (w - 2 * pad), py = h - pad - clamp(wc, 0, 1) * (h - 2 * pad);
  ctx.strokeStyle = 'rgba(180,137,255,.35)';
  ctx.beginPath(); ctx.moveTo(px, h - pad); ctx.lineTo(px, py); ctx.lineTo(pad, py); ctx.stroke();
  ctx.fillStyle = css('--violet');
  ctx.beginPath(); ctx.arc(px, py, 3, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = css('--ink-faint'); ctx.font = '8px ui-monospace, monospace';
  ctx.textAlign = 'right'; ctx.fillText('slack', w - pad, h - pad - 1);
}

/* delay sparkline */
function drawSparkline() {
  const { ctx, w, h } = fit($('lqCanvas'));
  const d = S.delays.slice(-160);
  if (d.length < 2) return;
  const target = CFG.fallbackDelay;
  const mn = Math.min(target * 0.9, ...d), mx = Math.max(target * 1.1, ...d);
  const X = (i) => (i / (d.length - 1)) * (w - 2) + 1;
  const Y = (v) => h - 2 - ((v - mn) / Math.max(1e-6, mx - mn)) * (h - 4);
  ctx.strokeStyle = 'rgba(255,182,60,.35)'; ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(0, Y(target)); ctx.lineTo(w, Y(target)); ctx.stroke(); ctx.setLineDash([]);
  ctx.strokeStyle = css('--cyan'); ctx.lineWidth = 1.4; ctx.beginPath();
  d.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v))));
  ctx.stroke();
  ctx.fillStyle = css('--ink-faint'); ctx.font = '8px ui-monospace, monospace';
  ctx.textAlign = 'left'; ctx.fillText(f(mx, 1) + 's', 3, 9);
  ctx.fillText(f(mn, 1) + 's', 3, h - 3);
}

/* ground track */
function drawMap() {
  const { ctx, w, h } = fit($('mapCanvas'));
  if (!S.trail.length) return;
  let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
  for (const p of S.trail) { minx = Math.min(minx, p.x); maxx = Math.max(maxx, p.x); miny = Math.min(miny, p.y); maxy = Math.max(maxy, p.y); }
  const pad = 14;
  const span = Math.max(20, maxx - minx, maxy - miny) * 1.25;
  const cx = (minx + maxx) / 2, cy = (miny + maxy) / 2;
  const k = (Math.min(w, h) - 2 * pad) / span;
  const X = (x) => w / 2 + (x - cx) * k;
  const Y = (y) => h / 2 - (y - cy) * k;

  /* grid at a round metre step */
  let step = 1;
  while (step * k < 26) step *= (String(step)[0] === '1' ? 2.5 : 2);
  ctx.strokeStyle = 'rgba(255,255,255,.05)'; ctx.lineWidth = 1;
  for (let gx = Math.ceil((cx - span / 2) / step) * step; gx < cx + span / 2; gx += step) {
    ctx.beginPath(); ctx.moveTo(X(gx), 0); ctx.lineTo(X(gx), h); ctx.stroke();
  }
  for (let gy = Math.ceil((cy - span / 2) / step) * step; gy < cy + span / 2; gy += step) {
    ctx.beginPath(); ctx.moveTo(0, Y(gy)); ctx.lineTo(w, Y(gy)); ctx.stroke();
  }
  $('mapScale').textContent = `GRID ${step} m`;

  /* the track */
  ctx.strokeStyle = 'rgba(63,227,255,.55)'; ctx.lineWidth = 1.6;
  ctx.beginPath();
  S.trail.forEach((p, i) => (i ? ctx.lineTo(X(p.x), Y(p.y)) : ctx.moveTo(X(p.x), Y(p.y))));
  ctx.stroke();

  /* confirmed markers */
  for (const pin of S.pins) {
    ctx.fillStyle = css('--green');
    ctx.beginPath(); ctx.arc(X(pin.x), Y(pin.y), 3.5, 0, Math.PI * 2); ctx.fill();
    ctx.font = '8px ui-monospace, monospace'; ctx.textAlign = 'left';
    ctx.fillText(pin.id, X(pin.x) + 6, Y(pin.y) + 3);
  }

  /* the rover, as of 60 s ago */
  const p = S.trail[S.trail.length - 1];
  const rad = (90 - p.h) * Math.PI / 180;
  const px = X(p.x), py = Y(p.y);
  ctx.fillStyle = 'rgba(63,227,255,.16)';
  ctx.beginPath(); ctx.moveTo(px, py);
  ctx.arc(px, py, 34, -rad - 0.52, -rad + 0.52); ctx.closePath(); ctx.fill();   // 60° fov wedge
  ctx.fillStyle = css('--cyan');
  ctx.save(); ctx.translate(px, py); ctx.rotate(-rad + Math.PI / 2);
  ctx.beginPath(); ctx.moveTo(0, -6); ctx.lineTo(4.5, 5); ctx.lineTo(-4.5, 5); ctx.closePath(); ctx.fill();
  ctx.restore();

  ctx.fillStyle = css('--ink-faint'); ctx.font = '8px ui-monospace, monospace'; ctx.textAlign = 'right';
  ctx.fillText('POSITION AS OF ' + f(S.delay ?? CFG.fallbackDelay, 0) + 's AGO', w - 4, h - 5);
}

/* viewport HUD */
function drawVpHud() {
  const cv = $('vpHud'), img = $('vpImg');
  const { ctx, w, h } = fit(cv);
  if (!S.last || !img.classList.contains('on')) return;
  const r = img.getBoundingClientRect(), s = cv.getBoundingClientRect();
  const x0 = r.left - s.left, y0 = r.top - s.top, iw = r.width, ih = r.height;

  ctx.strokeStyle = 'rgba(63,227,255,.35)'; ctx.lineWidth = 1;
  ctx.strokeRect(x0 + .5, y0 + .5, iw - 1, ih - 1);

  /* centre reticle + fov ticks (camera_hfov_deg 60, config.yaml) */
  const cx = x0 + iw / 2, cy = y0 + ih / 2;
  ctx.beginPath();
  ctx.moveTo(cx - 12, cy); ctx.lineTo(cx - 4, cy);
  ctx.moveTo(cx + 4, cy); ctx.lineTo(cx + 12, cy);
  ctx.moveTo(cx, cy - 12); ctx.lineTo(cx, cy - 4);
  ctx.moveTo(cx, cy + 4); ctx.lineTo(cx, cy + 12);
  ctx.stroke();
  ctx.fillStyle = 'rgba(63,227,255,.5)'; ctx.font = '9px ui-monospace, monospace'; ctx.textAlign = 'center';
  for (let b = -30; b <= 30; b += 10) {
    const px = x0 + iw * (0.5 + b / 60);
    ctx.beginPath(); ctx.moveTo(px, y0 + ih - 10); ctx.lineTo(px, y0 + ih - 4); ctx.stroke();
    if (b % 20 === 0) ctx.fillText((b > 0 ? '+' : '') + b + '°', px, y0 + ih - 13);
  }
}

/* ── the light-time lane ───────────────────────────────────────────────
   Each dot is one packet crossing the gap. A dot that has not reached the
   right-hand wall is something that ALREADY HAPPENED and that nobody on this
   side of the room can see yet. That is the whole argument, drawn.
   ──────────────────────────────────────────────────────────────────────── */
const lane = { down: [], up: [] };
function spawnLaneGhost(delay) { lane.down.push({ t0: performance.now(), d: Math.max(1, delay) * 1000 }); }
function spawnLaneUplink(delay) { lane.up.push({ t0: performance.now(), d: Math.max(1, delay) * 1000 }); }

function drawLane() {
  const { ctx, w, h } = fit($('laneCanvas'));
  const now = performance.now();
  ctx.strokeStyle = 'rgba(255,255,255,.05)';
  for (let i = 1; i < 10; i++) { const x = w * i / 10; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }

  const yD = h * 0.34, yU = h * 0.72;
  ctx.strokeStyle = 'rgba(63,227,255,.14)'; ctx.beginPath(); ctx.moveTo(0, yD); ctx.lineTo(w, yD); ctx.stroke();
  ctx.strokeStyle = 'rgba(255,77,94,.12)';  ctx.beginPath(); ctx.moveTo(0, yU); ctx.lineTo(w, yU); ctx.stroke();

  lane.down = lane.down.filter((p) => now - p.t0 < p.d + 900);
  let inflight = 0;
  for (const p of lane.down) {
    const u = (now - p.t0) / p.d;
    if (u <= 1) {
      inflight++;
      ctx.fillStyle = 'rgba(63,227,255,.55)';
      ctx.beginPath(); ctx.arc(u * w, yD, 3.4, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = 'rgba(63,227,255,.30)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(u * w, yD, 6, 0, Math.PI * 2); ctx.stroke();
    } else {
      const a = 1 - (now - p.t0 - p.d) / 900;
      ctx.fillStyle = `rgba(63,227,255,${a})`;
      ctx.beginPath(); ctx.arc(w - 2, yD, 3 + 7 * (1 - a), 0, Math.PI * 2); ctx.fill();
    }
  }
  $('inflightN').textContent = inflight;

  lane.up = lane.up.filter((p) => now - p.t0 < p.d + 900);
  for (const p of lane.up) {
    const u = clamp((now - p.t0) / p.d, 0, 1);
    const x = w - u * w;
    ctx.fillStyle = u < 1 ? css('--red') : 'rgba(255,77,94,.4)';
    ctx.beginPath(); ctx.arc(x, yU, 3.4, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = 'rgba(255,77,94,.35)';
    ctx.beginPath(); ctx.moveTo(x + 6, yU); ctx.lineTo(Math.min(w, x + 26), yU); ctx.stroke();
  }

  ctx.fillStyle = 'rgba(120,150,166,.5)'; ctx.font = '8px ui-monospace, monospace';
  ctx.textAlign = 'left'; ctx.fillText('DOWNLINK →', 6, yD - 8);
  ctx.textAlign = 'right'; ctx.fillText('← UPLINK', w - 6, yU + 14);
}

/* ───────────────────────── odds and ends ───────────────────────── */

function fmtMet(sim) {
  if (!Number.isFinite(sim)) return '-----';
  const sol = Math.floor(sim / 88775);
  const r = sim - sol * 88775;
  const hh = String(Math.floor(r / 3600)).padStart(2, '0');
  const mm = String(Math.floor((r % 3600) / 60)).padStart(2, '0');
  const ss = String(Math.floor(r % 60)).padStart(2, '0');
  return `SOL ${sol} ${hh}:${mm}:${ss}`;
}

function trackDrain(sim, rem) {
  if (!S.drainRef) { S.drainRef = { sim, rem }; return; }
  const dt = sim - S.drainRef.sim;
  if (dt < 120) return;                                   // 2 sim-minutes of evidence
  const rate = (S.drainRef.rem - rem) / dt * 3600;        // Wh per sim-hour
  S.drainRef = { sim, rem };
  if (!Number.isFinite(rate)) return;
  $('powDraw').textContent = f(Math.max(0, rate), 1);
  const req = S.last?.audit.budget.required_for_mission ?? 0;
  const usable = rem - req;
  $('powEnd').textContent = rate > 0.01 ? f(Math.max(0, usable / rate), 1) : '—';
}

function logEvent(kind, text) {
  const box = $('eventLog');
  const d = el('div', 'e-' + kind);
  const now = new Date();
  d.textContent = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}  ${text}`;
  box.insertBefore(d, box.firstChild);
  while (box.childElementCount > 60) box.removeChild(box.lastChild);
}

let toastN = 0;
function toast(text, cls) {
  const d = el('div', 'toast' + (cls ? ' ' + cls : ''), text);
  $('toast').appendChild(d);
  const id = ++toastN;
  setTimeout(() => { d.remove(); }, 4200 + (id % 3) * 200);
}

/* 20 Hz cosmetic loop: countdowns, lane animation, wall clock */
function tick() {
  const now = new Date();
  $('clkUtc').textContent = now.toISOString().slice(11, 19) + 'Z';

  if (S.lastArrivedMs) {
    const age = (Date.now() - S.lastArrivedMs) / 1000;    // cosmetic only — panel.md §5
    $('clkAge').textContent = f(age, 1) + 's ago';
    $('vpAgeTag').textContent = S.delay == null ? 'DELAYED' : `DELAYED ${f(S.delay, 1)}s`;
    $('delayHero').classList.toggle('stale', age > 12);
    if (age > 12 && S.connected) $('vpAgeTag').textContent = 'NO NEW FRAMES';
  }

  let dirty = false;
  for (const fl of S.flights) {
    if (fl.state === 'flight' && Date.now() >= fl.landMs) { fl.state = 'landed'; dirty = true; logEvent('up', `${fl.command} REACHED THE ROVER — effect unknown for another ${Math.round(fl.delayReal)}s`); }
    else if (fl.state === 'flight') dirty = true;
  }
  if (dirty) renderFlights();

  drawLane();
  requestAnimationFrame(tick);
}

/* ───────────────────────── demo mode ───────────────────────── */

function startDemo() {
  S.source = 'demo';
  setLink('demo', 'SIMULATED SOURCE', 'DEMO MODE — no rover, no BRAIN, synthetic telemetry');
  document.title = '[DEMO] MISSION CONTROL — EARTH';
  logEvent('up', 'DEMO MODE — every number on this screen is synthetic');
  toast('DEMO MODE — SYNTHETIC TELEMETRY', 'warn');
  DEMO.start({
    delay: CFG.fallbackDelay,
    timeCompression: CFG.timeCompression,
    gamma: Number(QS.get('gamma') || 2.0),
    budget: Number(QS.get('budget') || 1000),
    onTelemetry: (msg, blobs) => {
      onText(JSON.stringify(msg));
      for (const b of blobs) onBinary(b);
    },
    onEvent: (kind, text) => logEvent(kind, text),
    onUplinkResult: (command, result, note) => resolveFlight(command, result, note),
  });
}

/* ───────────────────────── wiring ───────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.up-buttons .btn').forEach((b) => {
    b.addEventListener('click', () => sendUplink(b.dataset.cmd));
  });
  $('staleDismiss').addEventListener('click', () => { $('staleAlarm').hidden = true; });
  $('chkOnlyCommits').addEventListener('change', () => { S.lastCard = null; });

  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.metaKey || e.ctrlKey) return;
    const k = e.key.toLowerCase();
    if (k === 'a') sendUplink('abort_investigation');
    else if (k === 'h') sendUplink('halt');
    else if (k === 'f') { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen(); }
    else if (k === 'escape') $('staleAlarm').hidden = true;
  });

  window.addEventListener('resize', () => {
    if (S.last) { drawMap(); drawRose(S.last.pose.heading_deg); drawCurve(S.last.audit.gamma, S.last.audit.slack, S.last.audit.w_curiosity); drawSparkline(); }
    drawVpHud();
  });

  $('powCap').textContent = f(S.capacity, 0);
  $('powCapTxt').textContent = f(S.capacity, 0);
  $('laneDelay').textContent = CFG.fallbackDelay;
  $('upDelayTxt').textContent = CFG.fallbackDelay;
  logEvent('t', `panel up · target ${CFG.wsUrl}`);

  requestAnimationFrame(tick);
  connect();
});
