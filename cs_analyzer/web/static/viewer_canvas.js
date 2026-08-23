// Real-time 2D map replay viewer (Phase C M3): layered canvases, rAF loop,
// tick-domain timeline. Data: /api/demo/{hash}/viewer-data (8 Hz snapshots).
(function () {
  const m = location.pathname.match(/\/demo\/([^/]+)\/viewer/);
  if (!m) return;
  const HASH = m[1];

  // ---- palette (matches style.css esports tokens) ----
  const C = {
    t: '#ffb02e', ct: '#3d9bff', text: '#e8edf4', muted: '#8b98ab',
    err: '#ff4d5e', ok: '#3ddc97', warn: '#ffb02e', accent: '#4da3ff',
    smoke: 'rgba(200,205,215,', fire: 'rgba(255,110,40,', flash: 'rgba(255,255,255,',
    kill: '#ffd166', dead: '#7a8595',
  };
  const T_PALETTE = ['#ffd54f', '#ffb02e', '#ff8f00', '#ff7043', '#f4511e'];
  const CT_PALETTE = ['#81d4fa', '#3d9bff', '#00bcd4', '#0288d1', '#1565c0'];
  const YAW_FAN_DEG = 35;
  const BREAK_DIST = 300;

  const $ = (id) => document.getElementById(id);
  const statusEl = $('load-status');
  const root = $('ob-root');

  let D = null;            // viewer-data payload
  let mapImg = null;       // Image
  let totalTicks = 1;      // timeline span
  const state = {
    playing: false,
    tick: 0,
    speed: 1,
    lastTs: 0,
    holdUntil: 0,          // wall-clock ms pause at round end
  };
  const DPR = Math.min(window.devicePixelRatio || 1, 2);

  // per-player render state
  let players = [];        // {steamid,name,color,rows:{t,x,y,yaw,hp,armor,alive,side,w}}
  let killsByTick = [];

  function segOfTick(tick) {
    for (const s of D.segments) if (tick >= s.start_tick && tick <= s.end_tick) return s;
    return null;
  }

  function worldToPixel(x, y) {
    const b = D.map.bounds;
    return [
      ((x - b.min_x) / (b.max_x - b.min_x)) * D.map.width,
      (1 - (y - b.min_y) / (b.max_y - b.min_y)) * D.map.height,
    ];
  }

  function playerStateAt(p, tick) {
    // binary search the snapshot index; linear-interpolate x/y between rows.
    const t = p.rows.t;
    let lo = 0, hi = t.length - 1;
    if (tick <= t[0]) lo = 0;
    else if (tick >= t[hi]) lo = hi;
    else {
      while (hi - lo > 1) { const mid = (lo + hi) >> 1; (t[mid] <= tick ? lo = mid : hi = mid); }
    }
    const i = lo;
    const j = Math.min(i + 1, t.length - 1);
    const out = {
      x: p.rows.x[i], y: p.rows.y[i], yaw: p.rows.yaw[i], hp: p.rows.hp[i],
      armor: p.rows.armor[i], alive: p.rows.alive[i], side: p.rows.side[i], w: p.rows.w[i],
      i, j,
    };
    if (j > i && p.rows.alive[i] && p.rows.alive[j] && out.alive) {
      const f = (tick - t[i]) / Math.max(t[j] - t[i], 1);
      let dx = p.rows.x[j] - p.rows.x[i];
      let dy = p.rows.y[j] - p.rows.y[i];
      // never interpolate across teleports / respawns
      if (Math.hypot(dx, dy) < BREAK_DIST) {
        out.x = p.rows.x[i] + dx * f;
        out.y = p.rows.y[i] + dy * f;
        out.moving = true;
      }
      out.yaw = lerpAngleDeg(p.rows.yaw[i], p.rows.yaw[j], f);
    }
    return out;
  }

  function lerpAngleDeg(a, b, f) {
    let d = ((b - a + 540) % 360) - 180;
    return a + d * f;
  }

  // ---- canvas helpers ----
  function setupCanvas(canvas, wCss, hCss) {
    canvas.width = Math.round(wCss * DPR);
    canvas.height = Math.round(hCss * DPR);
    canvas.style.width = wCss + 'px';
    canvas.style.height = hCss + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    return ctx;
  }

  function drawMapLayer() {
    const wrap = document.querySelector('.ob-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('map-layer'), w, h);
    ctx.fillStyle = '#07090d';
    ctx.fillRect(0, 0, w, h);
    // geometry must exist before any frame runs (map image loads async)
    const iw = mapImg ? mapImg.width : 1024, ih = mapImg ? mapImg.height : 1024;
    const scale = Math.min(w / iw, h / ih);
    drawMapLayer.geom = { ox: (w - iw * scale) / 2, oy: (h - ih * scale) / 2, scale };
    if (!mapImg) return;
    ctx.globalAlpha = 0.92;
    ctx.drawImage(mapImg, drawMapLayer.geom.ox, drawMapLayer.geom.oy, iw * scale, ih * scale);
    ctx.globalAlpha = 1;
  }

  function toScreen(wx, wy) {
    // world coords -> map pixel space -> screen space (contain-fit + offset)
    const b = D.map.bounds;
    const px = ((wx - b.min_x) / (b.max_x - b.min_x)) * D.map.width;
    const py = (1 - (wy - b.min_y) / (b.max_y - b.min_y)) * D.map.height;
    const g = drawMapLayer.geom;
    if (!g) return [px, py]; // map layer not laid out yet; first frame draws raw
    return [g.ox + px * g.scale, g.oy + py * g.scale];
  }

  function drawFxLayer(tick) {
    const wrap = document.querySelector('.ob-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('fx-layer'), w, h);
    ctx.clearRect(0, 0, w, h);
    if (!D) return;
    const TICK = D.tick_rate;
    const u = (D.events.utilities || []);
    for (const e of u) {
      const age = tick - e.tick;
      if (age < 0) continue;
      const kind = e.kind;
      let durS, radius, color, baseA;
      if (kind === '烟雾') { durS = 18; radius = 120; color = C.smoke; baseA = 0.32; }
      else if (kind === '闪光') { durS = 2; radius = 130; color = C.flash; baseA = 0.55; }
      else if (kind === 'HE') { durS = 1; radius = 85; color = 'rgba(255,136,0,'; baseA = 0.7; }
      else { durS = 7; radius = 50; color = C.fire; baseA = 0.45; }   // 燃烧瓶/molly
      const durT = durS * TICK;
      if (age > durT) continue;
      const [sx, sy] = toScreen(e.x, e.y);
      const prog = age / durT;
      if (kind === '烟雾') {
        const grow = Math.min(age / (1.0 * TICK), 1);
        const r = radius * grow * (drawMapLayer.geom.scale / 4);
        const a = baseA * (prog > 0.85 ? (1 - prog) / 0.15 : 1);
        ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fillStyle = color + a.toFixed(3) + ')'; ctx.fill();
      } else if (kind === 'HE') {
        const r = radius * (0.4 + 0.6 * prog) * (drawMapLayer.geom.scale / 4);
        ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.strokeStyle = color + (baseA * (1 - prog)).toFixed(3) + ')';
        ctx.lineWidth = 2.5; ctx.stroke();
      } else if (kind === '闪光') {
        const r = radius * 0.7 * (drawMapLayer.geom.scale / 4);
        ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fillStyle = color + (baseA * (1 - prog)).toFixed(3) + ')'; ctx.fill();
      } else { // fire zone flicker
        const r = radius * (drawMapLayer.geom.scale / 4);
        const flick = 0.75 + 0.25 * Math.sin(tick / 3 + e.x);
        const fade = prog > 0.8 ? (1 - prog) / 0.2 : 1;
        ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fillStyle = color + (baseA * flick * fade).toFixed(3) + ')'; ctx.fill();
      }
    }
    // kill connections (1.2s)
    for (const k of killsByTick) {
      const age = tick - k.tick;
      const durT = 1.2 * TICK;
      if (age < 0 || age > durT) continue;
      const a = 0.9 * (1 - age / durT);
      const [ax, ay] = toScreen(k.ax, k.ay);
      const [vx, vy] = toScreen(k.vx, k.vy);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(vx, vy);
      ctx.strokeStyle = C.kill; ctx.globalAlpha = a; ctx.lineWidth = 1.4; ctx.stroke();
      star(ctx, ax, ay, 5); skull(ctx, vx, vy);
      ctx.globalAlpha = 1;
    }
  }

  function star(ctx, x, y, r) {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const rr = i % 2 ? r * 0.45 : r;
      const a = (Math.PI / 5) * i - Math.PI / 2;
      const px = x + rr * Math.cos(a), py = y + rr * Math.sin(a);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle = C.kill; ctx.fill();
  }

  function skull(ctx, x, y) {
    ctx.beginPath(); ctx.arc(x, y, 3.2, 0, Math.PI * 2);
    ctx.fillStyle = C.err; ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.fillRect(x - 2, y - 1.2, 1.2, 1.2); ctx.fillRect(x + 0.8, y - 1.2, 1.2, 1.2);
  }

  function drawMainLayer(tick) {
    const wrap = document.querySelector('.ob-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('main-layer'), w, h);
    if (!D) return;
    const windowT = 1.2 * D.tick_rate;
    for (const p of players) {
      const st = playerStateAt(p, tick);
      if (!st.alive) {
        // corpse marker at last position
        if (st.x || st.y) {
          const [sx, sy] = toScreen(st.x, st.y);
          skull(ctx, sx, sy);
        }
        continue;
      }
      // trail: walk back through snapshots within the window
      const rows = p.rows;
      let i0 = st.i;
      while (i0 > 0 && rows.t[st.i] - rows.t[i0] < windowT) i0--;
      ctx.lineWidth = 2.2;
      let prev = null;
      for (let i = i0; i <= st.j && i < rows.t.length; i++) {
        if (!rows.alive[i]) break;
        const [sx, sy] = toScreen(rows.x[i], rows.y[i]);
        if (prev && Math.hypot(sx - prev.sx, sy - prev.sy) * (1 / drawMapLayer.geom.scale) < BREAK_DIST) {
          const f = (i - i0) / Math.max(st.i - i0, 1);
          ctx.strokeStyle = hexA(p.color, 0.15 + 0.85 * f);
          ctx.beginPath(); ctx.moveTo(prev.sx, prev.sy); ctx.lineTo(sx, sy); ctx.stroke();
        }
        prev = { sx, sy };
      }
      // marker + yaw fan
      const [sx, sy] = toScreen(st.x, st.y);
      const yawRad = (st.yaw * Math.PI) / 180;
      // Source yaw: 0 = +X, CCW. Screen y grows south -> dir = (cos(yaw), -sin(yaw)).
      // (Verified: 12613 moving samples, yaw vs atan2(vy,vx) circ error -0.8 deg.)
      const dx = Math.cos(yawRad), dy = -Math.sin(yawRad);
      const half = (YAW_FAN_DEG * Math.PI) / 360;
      const R = 16;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.arc(sx, sy, R, Math.atan2(dy, dx) - half, Math.atan2(dy, dx) + half);
      ctx.closePath();
      ctx.fillStyle = hexA(p.color, 0.35); ctx.fill();
      ctx.beginPath(); ctx.arc(sx, sy, 5.5, 0, Math.PI * 2);
      ctx.fillStyle = p.color; ctx.fill();
      ctx.lineWidth = 1.2; ctx.strokeStyle = '#000'; ctx.stroke();
      if (state.hoverName === null) continue;
    }
  }

  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  // ---- timeline (tick domain) ----
  function drawTimeline() {
    const canvas = $('tl-canvas');
    const w = canvas.parentElement.clientWidth, h = 56;
    const ctx = setupCanvas(canvas, w, h);
    ctx.clearRect(0, 0, w, h);
    if (!D) return;
    const xOf = (t) => (t / totalTicks) * w;
    for (const s of D.segments) {
      const x0 = xOf(s.start_tick), x1 = xOf(s.end_tick);
      const col = s.winner_side === 'T' ? C.t : C.ct;
      ctx.fillStyle = hexA(col, 0.20);
      ctx.fillRect(x0, 2, Math.max(x1 - x0, 1), h - 4);
      ctx.strokeStyle = hexA(col, 0.7); ctx.lineWidth = 1;
      ctx.strokeRect(x0 + 0.5, 2.5, Math.max(x1 - x0 - 1, 1), h - 5);
      ctx.fillStyle = C.text; ctx.font = '10px "Microsoft YaHei", sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('R' + s.round, (x0 + x1) / 2, h / 2 + 3.5);
    }
    // kill dots
    ctx.fillStyle = C.err;
    for (const k of killsByTick) {
      const px = xOf(k.tick);
      ctx.beginPath(); ctx.arc(px, 8, 2.2, 0, Math.PI * 2); ctx.fill();
    }
    // playhead
    const px = xOf(state.tick);
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, h); ctx.stroke();
  }

  function seekToTickFraction(f) {
    state.tick = Math.max(0, Math.min(f * totalTicks, totalTicks));
  }

  // ---- main loop ----
  function frame(ts) {
    requestAnimationFrame(frame);
    if (!D) return;
    try {
      const dt = Math.min((ts - state.lastTs) / 1000, 0.1);
      state.lastTs = ts;
      if (state.playing && ts >= state.holdUntil) {
        state.tick += dt * state.speed * D.tick_rate;
        const seg = segOfTick(state.tick);
        if (seg && state.tick > seg.end_tick - 2 && !seg._held) {
          // brief round-end pause with result strip
          showRoundStrip(seg);
          state.holdUntil = ts + 800;
          seg._held = true;
        }
        const lastSeg = D.segments[D.segments.length - 1];
        if (state.tick >= lastSeg.end_tick) {
          state.tick = lastSeg.end_tick;
          state.playing = false;
          $('btn-play').textContent = '播放';
        }
      }
      drawMainLayer(state.tick);
      drawFxLayer(state.tick);
      drawTimeline();
      updateHudTexts();
      schedulePanelFlush(ts);
    } catch (err) {
      console.error('viewer frame error:', err);
    }
  }

  function updateHudTexts() {
    const seg = segOfTick(state.tick);
    const rl = $('round-label'), timer = $('round-timer'), cur = $('cur-tick');
    cur.textContent = 'tick ' + Math.round(state.tick);
    if (!seg) { rl.textContent = '回合 -'; timer.textContent = '-'; setScores(null); return; }
    rl.textContent = '回合 ' + seg.round;
    const remain = Math.max(D.round_clock_seconds - (state.tick - seg.start_tick) / D.tick_rate, 0);
    const mm = Math.floor(remain / 60), ss = Math.floor(remain % 60);
    timer.textContent = mm + ':' + String(ss).padStart(2, '0');
    setScores(seg);
  }

  function setScores(seg) {
    const st = $('score-t'), sc = $('score-ct');
    if (!seg) { st.textContent = '-'; sc.textContent = '-'; return; }
    st.textContent = seg.t_score; sc.textContent = seg.ct_score;
  }

  function showRoundStrip(seg) {
    const strip = $('round-strip');
    strip.hidden = false;
    strip.textContent = (seg.winner_side === 'T' ? 'T' : 'CT') + ' 获胜';
    strip.className = 'round-strip show ' + (seg.winner_side === 'T' ? 'strip-t' : 'strip-ct');
    setTimeout(() => { strip.hidden = true; strip.classList.remove('show'); }, 2200);
  }

  // ---- spectator panels (DOM, throttled) ----
  let panelRows = {};   // steamid -> row elements
  let lastFlush = 0;
  let lastVals = {};

  function buildPanels() {
    panelRows = {};
    const mkRow = (p) => {
      const li = document.createElement('li');
      li.className = 'ob-row'; li.dataset.sid = p.steamid;
      li.innerHTML =
        '<div class="ob-row-top"><span class="ob-name"></span><span class="ob-wpn"></span></div>' +
        '<div class="ob-row-bot"><div class="ob-hp"><i></i></div><span class="ob-armor"></span></div>';
      li.querySelector('.ob-name').textContent = p.name;
      panelRows[p.steamid] = li;
      return li;
    };
    for (let k = 0; k < 5; k++) { $('panel-t').appendChild(mkRow({ steamid: '_ph_t' + k, name: '' })); }
    for (let k = 0; k < 5; k++) { $('panel-ct').appendChild(mkRow({ steamid: '_ph_c' + k, name: '' })); }
    // replace placeholders with real players on first flush
    panelRows = {};
    $('panel-t').innerHTML = ''; $('panel-ct').innerHTML = '';
    for (const p of players) {
      const li = mkRow(p);
      panelRows[p.steamid] = li;
    }
    const tracked = players.length;
    const fill = (ulId, prefix, n) => {
      for (let k = 0; k < n; k++) {
        const ph = document.createElement('li');
        ph.className = 'ob-row ob-ph';
        ph.innerHTML = '<div class="ob-row-top"><span class="ob-name">无数据</span><span class="ob-wpn"></span></div>' +
                       '<div class="ob-row-bot"><div class="ob-hp"><i></i></div><span class="ob-armor"></span></div>';
        $(ulId).appendChild(ph);
      }
    };
    fill('panel-t', 't', Math.max(0, 5 - countSide('T')));
    fill('panel-ct', 'c', Math.max(0, 5 - countSide('CT')));
  }

  function countSide(side) {
    let n = 0;
    for (const p of players) {
      const s = playerStateAt(p, state.tick);
      if (s.side === side) n++;
    }
    return n;
  }

  function schedulePanelFlush(ts) {
    if (ts - lastFlush < 100) return;
    lastFlush = ts;
    flushPanels();
  }

  function flushPanels() {
    if (!players.length) return;
    const buckets = { T: [], CT: [] };
    for (const p of players) {
      const st = playerStateAt(p, state.tick);
      (buckets[st.side === 'T' ? 'T' : 'CT']).push([p, st]);
    }
    const place = (ulId, list, side) => {
      const ul = $(ulId);
      const want = list.map(([p]) => p.steamid);
      const have = [...ul.children].filter((el) => el.dataset.sid).map((el) => el.dataset.sid);
      // re-parent when membership changed
      if (JSON.stringify(want) !== JSON.stringify(have.filter((sid) => panelRows[sid]))) {
        ul.innerHTML = '';
        for (const sid of want) ul.appendChild(panelRows[sid]);
        for (let k = want.length; k < 5; k++) {
          const ph = document.createElement('li');
          ph.className = 'ob-row ob-ph';
          ph.innerHTML = '<div class="ob-row-top"><span class="ob-name">无数据</span></div>' +
                         '<div class="ob-row-bot"><div class="ob-hp"><i></i></div></div>';
          ul.appendChild(ph);
        }
      }
      // update values (write-only-changed)
      list.forEach(([p, st], idx) => {
        const li = panelRows[p.steamid];
        const key = p.steamid;
        const sig = [st.hp, st.w, st.alive, st.armor].join('|');
        if (lastVals[key] === sig) return;
        lastVals[key] = sig;
        li.querySelector('.ob-wpn').textContent = st.w || '';
        li.querySelector('.ob-armor').textContent = st.armor > 0 ? '🛡' + st.armor : '';
        const bar = li.querySelector('.ob-hp i');
        bar.style.width = st.hp + '%';
        bar.className = st.hp > 50 ? '' : st.hp > 25 ? 'mid' : 'low';
        li.classList.toggle('is-dead', !st.alive);
      });
      // dead last ordering
      const kids = [...ul.children].filter((el) => el.dataset.sid);
      kids.sort((a, b) => {
        const da = a.classList.contains('is-dead') ? 1 : 0;
        const db = b.classList.contains('is-dead') ? 1 : 0;
        return da - db;
      });
      kids.forEach((el) => ul.appendChild(el));
    };
    place('panel-t', buckets.T, 'T');
    place('panel-ct', buckets.CT, 'CT');
  }

  // ---- data load ----
  async function load() {
    try {
      const res = await fetch('/api/demo/' + HASH + '/viewer-data?v=' + Date.now());
      if (!res.ok) throw new Error('HTTP ' + res.status);
      D = await res.json();
      totalTicks = D.segments[D.segments.length - 1].end_tick;
      state.tick = D.segments[0].start_tick; // start at the first round, not tick 0

      // colors by first observed side (post-M1 roster is correct; live side bytes
      // drive panels, but marker hue stays stable per player across halves)
      const sideCount = { T: 0, CT: 0 };
      players = D.players.map((rows) => {
        const firstSide = rows.side.find((s) => s) || 'CT';
        const pal = firstSide === 'T' ? T_PALETTE : CT_PALETTE;
        const idx = sideCount[firstSide]++;
        return { steamid: rows.steamid, name: (D.roster.find(r => r.steamid === rows.steamid) || {}).name || rows.steamid, rows, color: pal[idx % pal.length] };
      });

      killsByTick = (D.events.kills || [])
        .map((k) => ({ ...k }))
        .filter((k) => Number.isFinite(k.x) && Number.isFinite(k.y))
        .sort((a, b) => a.tick - b.tick);

      mapImg = new Image();
      mapImg.onload = () => { drawMapLayer(); };
      mapImg.src = D.map.image_url;

      statusEl.textContent = '';
      root.hidden = false;
      buildPanels();

      const sel = $('sel-round');
      D.segments.forEach((s) => {
        const o = document.createElement('option');
        o.value = s.round; o.textContent = '回合 ' + s.round;
        sel.appendChild(o);
      });
      sel.addEventListener('change', () => {
        const s = D.segments.find((x) => x.round === Number(sel.value));
        if (s) { state.tick = s.start_tick; state.playing = false; $('btn-play').textContent = '播放'; }
      });

      wireControls();
      drawMapLayer(); // lay out map geometry before any frame reads it
      window.__viewerDebug = { state, players, D, playerStateAt }; // dev probe
      requestAnimationFrame((ts) => { state.lastTs = ts; frame(ts); });
    } catch (e) {
      statusEl.textContent = '';
      $('load-error').hidden = false;
      $('load-error-msg').textContent = String(e);
    }
  }

  function wireControls() {
    const btnPlay = $('btn-play');
    btnPlay.addEventListener('click', () => {
      state.playing = !state.playing;
      btnPlay.textContent = state.playing ? '暂停' : '播放';
    });
    $('sel-speed').addEventListener('change', (e) => { state.speed = Number(e.target.value); });
    const tl = $('tl-canvas');
    const tip = $('tl-tip');
    const dragging = { on: false };
    const fracOf = (e) => {
      const r = tl.getBoundingClientRect();
      return Math.max(0, Math.min((e.clientX - r.left) / r.width, 1));
    };
    tl.addEventListener('mousedown', (e) => { dragging.on = true; seekToTickFraction(fracOf(e)); });
    window.addEventListener('mousemove', (e) => { if (dragging.on) seekToTickFraction(fracOf(e)); });
    window.addEventListener('mouseup', () => { dragging.on = false; });
    tl.addEventListener('mousemove', (e) => {
      const r = tl.getBoundingClientRect();
      tip.style.display = 'block';
      const f = fracOf(e);
      tip.textContent = '回合 ' + (segOfTick(f * totalTicks)?.round ?? '-') + ' · tick ' + Math.round(f * totalTicks);
      tip.style.left = (e.clientX - r.left) + 'px';
    });
    tl.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT') return;
      if (e.code === 'Space') { e.preventDefault(); btnPlay.click(); }
      else if (e.code === 'ArrowLeft') state.tick = Math.max(0, state.tick - (e.shiftKey ? 30 : 5) * D.tick_rate);
      else if (e.code === 'ArrowRight') state.tick = Math.min(totalTicks, state.tick + (e.shiftKey ? 30 : 5) * D.tick_rate);
      else if (/^[1-8]$/.test(e.key)) { state.speed = Number(e.key); $('sel-speed').value = e.key; }
    });
    window.addEventListener('resize', () => { drawMapLayer(); });
  }

  load();
})();
