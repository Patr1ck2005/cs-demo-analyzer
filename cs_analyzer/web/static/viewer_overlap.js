// Round-overlap analysis page (回合重叠, Phase F+ rework).
//
// A dedicated page: all selected rounds of one half are drawn on one map at
// the same round-relative phase. Coloring follows each sample's LIVE side
// (warm family = T, cool = CT) so a halftime swap re-groups instead of
// mixing; number labels (1-0) anchor player identity across rounds.
// Single-player mode: pick one row → only their traces (long, arrow-tipped);
// ghost mode (default on) keeps the others at low alpha.
(function () {
  'use strict';
  const m = location.pathname.match(/\/demo\/([^/]+)\/overlap/);
  if (!m) return;
  const HASH = m[1];

  const T_PALETTE = ['#ffd54f', '#ffb02e', '#ff8f00', '#ff7043', '#f4511e'];
  const CT_PALETTE = ['#81d4fa', '#3d9bff', '#00bcd4', '#0288d1', '#1565c0'];
  const SIDE_NAME = ['T', 'CT', ''];
  const YAW_FAN_DEG = 35;
  const BREAK_DIST = 300;
  const GHOST_ALPHA = 0.14;
  const DPR = Math.min(window.devicePixelRatio || 1, 2);

  const $ = (id) => document.getElementById(id);
  let D = null;            // viewer-data payload
  let mapImg = null;
  let players = [];        // {steamid, name, num, sideFirst, color, rows}
  let cam = window.ViewerCam ? ViewerCam.create() : { cx: null, cy: null, zoom: 1 };

  const state = {
    half: 1,               // 1 = upper (first half of rounds), 2 = lower
    rounds: new Set(),     // selected round numbers within the half
    phase: 0.15,           // round-relative 0..1
    focusSid: null,        // single-player mode
    ghost: true,           // show others at low alpha in single mode
    trails: true,
    playing: false,        // phase auto-advance
    lastTs: 0,
  };

  // ---- camera helpers (mirror viewer_canvas.js) ----
  function pxPerWorldUnit() {
    const b = D.map.bounds;
    return D.map.width / Math.max(b.max_x - b.min_x, 1);
  }
  // Marker scale grows with zoom, capped: ms = min(0.36·√z, 1).
  // fit → dot r≈4px (12 overlapped rounds stay separated); zoomed → r=11px.
  function markerScale() {
    const z = cam.zoom || 1;
    return Math.min(0.36 * Math.sqrt(z), 1);
  }
  function labelFont(ms) {
    return `800 ${Math.max(12 * ms, 9)}px Consolas, monospace`;
  }
  function camScale() {
    return (drawMapLayer.geom ? drawMapLayer.geom.scale : 1) * cam.zoom;
  }
  function toScreen(wx, wy) {
    const b = D.map.bounds;
    const px = ((wx - b.min_x) / (b.max_x - b.min_x)) * D.map.width;
    const py = (1 - (wy - b.min_y) / (b.max_y - b.min_y)) * D.map.height;
    const wrap = $('ov-map-wrap');
    if (cam.cx == null) { cam.cx = D.map.width / 2; cam.cy = D.map.height / 2; }
    const S = camScale();
    return [
      wrap.clientWidth / 2 + (px - cam.cx) * S,
      wrap.clientHeight / 2 + (py - cam.cy) * S,
    ];
  }
  function setupCanvas(canvas, wCss, hCss) {
    canvas.width = Math.round(wCss * DPR);
    canvas.height = Math.round(hCss * DPR);
    canvas.style.width = wCss + 'px';
    canvas.style.height = hCss + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    return ctx;
  }
  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  function segOf(round) {
    return D.segments.find((s) => s.round === round) || null;
  }
  function fmtClock(sec) {
    const s = Math.max(0, Math.round(sec));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  // ---- half logic: rounds split into two halves (side swap in between) ----
  function halfRounds(half) {
    const total = D.segments.length;
    const cut = Math.ceil(total / 2);
    return D.segments.filter((s) => (half === 1 ? s.round <= cut : s.round > cut));
  }

  // ---- map layer ----
  function drawMapLayer() {
    const wrap = $('ov-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('map-layer'), w, h);
    ctx.fillStyle = '#07090d';
    ctx.fillRect(0, 0, w, h);
    const iw = (mapImg && mapImg.naturalWidth) || 1024;
    const ih = (mapImg && mapImg.naturalHeight) || 1024;
    const scale = Math.min(w / iw, h / ih);
    drawMapLayer.geom = { scale };
    if (!mapImg) return;
    if (window.ViewerCam) ViewerCam.resolve(cam, iw, ih);
    const S = scale * cam.zoom;
    const sx0 = w / 2 + (0 - cam.cx) * S;
    const sy0 = h / 2 + (0 - cam.cy) * S;
    ctx.globalAlpha = 0.92;
    ctx.drawImage(mapImg, sx0, sy0, iw * S, ih * S);
    ctx.globalAlpha = 1;
  }

  // ---- overlap render (main layer) ----
  function drawOverlap(tickOfRound) {
    const wrap = $('ov-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('main-layer'), w, h);
    const ms = markerScale();
    const windowT = 1.2 * D.tick_rate;
    // draw order: non-selected (ghost) first, then selected rounds, focus last
    for (const seg of halfRounds(state.half)) {
      const on = state.rounds.size === 0 || state.rounds.has(seg.round);
      const tick = tickOfRound(seg);
      if (tick == null) continue;
      for (const p of players) {
        const isFocus = state.focusSid === p.steamid;
        let alpha;
        if (state.focusSid) {
          alpha = isFocus ? 1 : (state.ghost ? GHOST_ALPHA : 0);
        } else {
          alpha = on ? 0.9 : 0.12;
        }
        if (alpha < 0.03) continue;
        const st = playerStateAt(p, tick);
        if (!st.alive) continue;
        const liveSide = SIDE_NAME[p.rows.side[st.i]] || 'CT';
        const color = liveSide === 'T'
          ? T_PALETTE[parseInt(p.num, 10) % T_PALETTE.length]
          : CT_PALETTE[parseInt(p.num, 10) % CT_PALETTE.length];
        // long trail: analysis-grade window (6s normal / 10s focused) so the
        // opening pattern is visible at any phase
        if (state.trails) {
          const rows = p.rows;
          const win = (state.focusSid ? 10 : 6) * D.tick_rate;
          let i0 = st.i;
          while (i0 > 0 && rows.t[st.i] - rows.t[i0] < win) i0--;
          ctx.lineWidth = (isFocus ? 3.2 : 2) * ms;
          let prev = null;
          for (let i = i0; i <= st.i && i < rows.t.length; i++) {
            if (!rows.alive[i]) break;
            const [sx, sy] = toScreen(rows.x[i], rows.y[i]);
            if (prev && Math.hypot(sx - prev.sx, sy - prev.sy) * (1 / drawMapLayer.geom.scale) < BREAK_DIST) {
              const f = (i - i0) / Math.max(st.i - i0, 1);
              ctx.strokeStyle = hexA(color, alpha * (0.12 + 0.85 * f));
              ctx.beginPath(); ctx.moveTo(prev.sx, prev.sy); ctx.lineTo(sx, sy); ctx.stroke();
            }
            prev = { sx, sy };
          }
          // direction arrow at the head
          if (prev && isFocus) {
            const st2 = playerStateAt(p, tick);
            const yawRad = (st2.yaw * Math.PI) / 180;
            const dx = Math.cos(yawRad), dy = -Math.sin(yawRad);
            ctx.beginPath();
            ctx.moveTo(prev.sx, prev.sy);
            ctx.lineTo(prev.sx + dx * 16 * ms, prev.sy + dy * 16 * ms);
            ctx.strokeStyle = hexA(color, alpha); ctx.lineWidth = 3 * ms; ctx.stroke();
          }
        }
        const [sx, sy] = toScreen(st.x, st.y);
        ctx.beginPath(); ctx.arc(sx, sy, 11 * ms, 0, Math.PI * 2);
        ctx.fillStyle = hexA(color, alpha); ctx.fill();
        ctx.lineWidth = 2 * ms; ctx.strokeStyle = '#000'; ctx.stroke();
        // white number on black outline — legible on any marker color
        ctx.font = labelFont(ms);
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.lineWidth = 3 * ms; ctx.strokeStyle = 'rgba(0,0,0,.95)';
        ctx.strokeText(p.num, sx, sy);
        ctx.fillStyle = alpha > 0.5 ? '#ffffff' : '#0b0e14';
        ctx.fillText(p.num, sx, sy);
        if (isFocus) {
          ctx.beginPath(); ctx.arc(sx, sy, 18 * ms, 0, Math.PI * 2);
          ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 2.4 * ms; ctx.stroke();
        }
      }
    }
  }

  function playerStateAt(p, tick) {
    const t = p.rows.t;
    let lo = 0, hi = t.length - 1;
    if (tick <= t[0]) lo = 0;
    else if (tick >= t[hi]) lo = hi;
    else while (hi - lo > 1) { const mid = (lo + hi) >> 1; (t[mid] <= tick ? lo = mid : hi = mid); }
    const i = lo;
    const out = {
      x: p.rows.x[i], y: p.rows.y[i], alive: !!p.rows.alive[i],
      i,
    };
    return out;
  }

  // ---- fx layer: nothing yet (reserved for utility zones) ----
  function drawFx() {
    const wrap = $('ov-map-wrap');
    setupCanvas($('fx-layer'), wrap.clientWidth, wrap.clientHeight);
  }

  // ---- main loop ----
  function frame(ts) {
    requestAnimationFrame(frame);
    if (!D) return;
    try {
      const dt = Math.min((ts - state.lastTs) / 1000, 0.1);
      state.lastTs = ts;
      if (state.playing) {
        state.phase += dt / 20; // 20s to sweep the phase
        if (state.phase > 1) { state.phase = 1; state.playing = false; }
        syncPhaseUI();
      }
      const segs = halfRounds(state.half);
      if (!segs.length) return;
      const span = Math.max(segs[0].end_tick - segs[0].start_tick - 2, 1);
      const tickOfRound = (seg) => seg.start_tick + state.phase * span;
      drawMapLayer();
      drawFx();
      drawOverlap(tickOfRound);
    } catch (err) {
      console.error('overlap frame error:', err);
    }
  }

  // ---- UI builders ----
  function buildHalfTabs() {
    const total = D.segments.length;
    const cut = Math.ceil(total / 2);
    const t1 = $('ov-half-tab-t'), t2 = $('ov-half-tab-ct');
    t1.textContent = `上半场 R1-${cut}`;
    t2.textContent = `下半场 R${cut + 1}-${total}`;
    t1.addEventListener('click', () => setHalf(1));
    t2.addEventListener('click', () => setHalf(2));
  }
  function setHalf(h) {
    state.half = h;
    state.rounds.clear();
    $('ov-half-tab-t').classList.toggle('active', h === 1);
    $('ov-half-tab-ct').classList.toggle('active', h === 2);
    buildRoundGrid();
    buildPlayerGrid();
  }
  function buildRoundGrid() {
    const holder = $('ov-rounds');
    holder.innerHTML = '';
    const segs = halfRounds(state.half);
    $('ov-round-count').textContent = `${segs.length} 回合 · 空选 = 全部`;
    for (const seg of segs) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip';
      chip.innerHTML = `R${seg.round}<span class="ovr-side" style="background:${seg.winner_side === 'T' ? 'var(--t)' : 'var(--ct)'}"></span>`;
      chip.title = `R${seg.round} · ${seg.winner_side} 胜`;
      chip.addEventListener('click', () => {
        if (state.rounds.has(seg.round)) state.rounds.delete(seg.round);
        else state.rounds.add(seg.round);
        syncRoundChips();
      });
      chip.dataset.round = seg.round;
      holder.appendChild(chip);
    }
    syncRoundChips();
  }
  function syncRoundChips() {
    for (const chip of document.querySelectorAll('#ov-rounds .chip')) {
      const r = Number(chip.dataset.round);
      chip.classList.toggle('on', state.rounds.size === 0 || state.rounds.has(r));
      chip.classList.toggle('off', state.rounds.size > 0 && !state.rounds.has(r));
    }
  }
  function buildPlayerGrid() {
    const holder = $('ov-players');
    holder.innerHTML = '';
    for (const p of players) {
      const row = document.createElement('div');
      row.className = 'ov-player-row';
      row.dataset.sid = p.steamid;
      const num = document.createElement('span');
      num.className = 'ob-num';
      num.style.borderColor = p.color;
      num.style.color = p.color;
      num.textContent = p.num;
      const name = document.createElement('span');
      name.className = 'ovp-name';
      name.textContent = p.name;
      const team = document.createElement('span');
      team.className = 'ovp-team';
      team.textContent = p.sideFirst === 'T' ? '开局 T' : '开局 CT';
      row.append(num, name, team);
      row.addEventListener('click', () => {
        state.focusSid = state.focusSid === p.steamid ? null : p.steamid;
        syncPlayerRows();
      });
      holder.appendChild(row);
    }
    syncPlayerRows();
  }
  function syncPlayerRows() {
    for (const row of document.querySelectorAll('.ov-player-row')) {
      row.classList.toggle('active', row.dataset.sid === state.focusSid);
    }
  }
  function syncPhaseUI() {
    const slider = $('ov-phase');
    slider.value = String(Math.round(state.phase * 1150));
    const segs = halfRounds(state.half);
    const span = segs.length ? Math.max(segs[0].end_tick - segs[0].start_tick - 2, 1) : 1;
    $('ov-phase-val').textContent = fmtClock(state.phase * span / D.tick_rate);
  }

  // ---- wiring ----
  function wire() {
    const wrap = $('ov-map-wrap');
    wrap.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (!drawMapLayer.geom) return;
      const rect = wrap.getBoundingClientRect();
      const cursor = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      ViewerCam.zoomAt(cam, cursor, Math.exp(-e.deltaY * 0.0015),
        { w: wrap.clientWidth, h: wrap.clientHeight },
        drawMapLayer.geom.scale, D.map.width, D.map.height, 1, 8);
    }, { passive: false });
    const pan = { on: false, id: -1, x: 0, y: 0, moved: false };
    wrap.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      if (e.target.closest && e.target.closest('.ov-toolbar')) return;
      pan.on = true; pan.id = e.pointerId; pan.moved = false;
      pan.x = e.clientX; pan.y = e.clientY;
    });
    wrap.addEventListener('pointermove', (e) => {
      if (!pan.on || e.pointerId !== pan.id) return;
      const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
      if (!pan.moved) {
        if (Math.hypot(dx, dy) < 4) return;
        pan.moved = true;
        try { wrap.setPointerCapture(pan.id); } catch (err) { /* gone */ }
      }
      pan.x = e.clientX; pan.y = e.clientY;
      if (!drawMapLayer.geom) return;
      ViewerCam.panBy(cam, dx, dy, { w: wrap.clientWidth, h: wrap.clientHeight },
        drawMapLayer.geom.scale, D.map.width, D.map.height);
    });
    wrap.addEventListener('pointerup', (e) => {
      if (e.pointerId !== pan.id) return;
      pan.on = false;
      try { if (wrap.hasPointerCapture(pan.id)) wrap.releasePointerCapture(pan.id); } catch (err) {}
    });
    wrap.addEventListener('dblclick', () => { ViewerCam.reset(cam); });
    $('ov-reset').addEventListener('click', () => { ViewerCam.reset(cam); });
    $('ov-zoom').addEventListener('change', (e) => {
      ViewerCam.reset(cam);
      cam.zoom = Number(e.target.value);
    });
    $('ov-phase').addEventListener('input', (e) => {
      state.phase = Number(e.target.value) / 1150;
      syncPhaseUI();
    });
    $('ov-chip-trails').addEventListener('click', (e) => {
      state.trails = !state.trails;
      e.currentTarget.classList.toggle('on', state.trails);
      // at very low phase trails are ~zero-length; nudge the phase so the
      // toggle has an immediate visible effect
      if (state.trails && state.phase < 0.08) {
        state.phase = 0.15;
        syncPhaseUI();
      }
    });
    $('ov-chip-ghost').addEventListener('click', (e) => {
      state.ghost = !state.ghost;
      e.currentTarget.classList.toggle('on', state.ghost);
    });
    $('ov-sel-all').addEventListener('click', () => {
      state.rounds.clear(); syncRoundChips(); // empty = all
    });
    $('ov-sel-none').addEventListener('click', () => {
      for (const s of halfRounds(state.half)) state.rounds.add(s.round);
      syncRoundChips();
    });
    $('ov-sel-first4').addEventListener('click', () => {
      state.rounds.clear();
      const segs = halfRounds(state.half);
      for (const s of segs.slice(0, 4)) state.rounds.add(s.round);
      syncRoundChips();
    });
    window.addEventListener('resize', () => { drawMapLayer(); });
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Escape' && state.focusSid) {
        state.focusSid = null;
        syncPlayerRows();
      } else if (e.code === 'Space') {
        e.preventDefault();
        state.playing = !state.playing;
      } else if (e.code === 'Digit1') setHalf(1);
      else if (e.code === 'Digit2') setHalf(2);
    });
  }

  // ---- load ----
  async function load() {
    try {
      const res = await fetch('/api/demo/' + HASH + '/viewer-data?v=' + Date.now());
      if (!res.ok) throw new Error('HTTP ' + res.status);
      D = await res.json();
      const sideCount = { T: 0, CT: 0 };
      players = D.players.map((rows, i) => {
        const firstCode = rows.side.find((s) => s !== 2);
        const firstSide = SIDE_NAME[firstCode] || 'CT';
        const pal = firstSide === 'T' ? T_PALETTE : CT_PALETTE;
        const idx = sideCount[firstSide]++;
        return {
          steamid: rows.steamid,
          name: (D.roster.find((r) => r.steamid === rows.steamid) || {}).name || rows.steamid,
          sideFirst: firstSide,
          num: String((i + 1) % 10),
          rows, color: pal[idx % pal.length],
        };
      });
      $('ov-half-score').textContent =
        `${D.teams?.t || 'T'} vs ${D.teams?.ct || 'CT'} · ${D.map_name}`;
      mapImg = new Image();
      mapImg.onload = () => { drawMapLayer(); };
      mapImg.src = D.map.image_url;
      $('ov-root').hidden = false;
      $('load-status').textContent = '';
      buildHalfTabs();
      setHalf(1);
      wire();
      syncPhaseUI();
      window.__ovDebug = { state, players, D };
      requestAnimationFrame((ts) => { state.lastTs = ts; frame(ts); });
    } catch (e) {
      $('load-status').textContent = '';
      $('load-error').hidden = false;
      $('load-error-msg').textContent = String(e);
    }
  }
  load();
})();
