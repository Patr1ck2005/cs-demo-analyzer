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
  // v2 payload: side snapshot codes 0=T / 1=CT / 2=unknown; weapons interned
  const SIDE_NAME = ['T', 'CT', ''];
  // zone lifetime defaults (game seconds) when the payload has no real duration
  const DEFAULT_DUR_S = { smoke: 18, flash: 2, he: 1, fire: 7 };

  const $ = (id) => document.getElementById(id);
  const statusEl = $('load-status');
  const root = $('ob-root');

  let D = null;            // viewer-data payload
  let mapImg = null;       // Image
  let totalTicks = 1;      // timeline span
  const TOGGLE_DEFAULTS = { trails: true, kills: true, nades: true, shots: false, blinds: true, bombs: true, control: false, ctrl3d: false };
  const state = {
    playing: false,
    tick: 0,
    speed: 1,
    lastTs: 0,
    holdUntil: 0,          // wall-clock ms pause at round end
    toggles: Object.assign({}, TOGGLE_DEFAULTS),  // overlay switches (persisted)
    lastLinkedRound: null, // last round written to the deep-link URL
    focusSid: null,        // clicked player (highlight; others dimmed)
  };
  try { // restore persisted overlay toggles
    const saved = JSON.parse(localStorage.getItem('csa-viewer-toggles') || '{}');
    Object.assign(state.toggles, saved);
  } catch (e) { /* fresh profile */ }
  const DPR = Math.min(window.devicePixelRatio || 1, 2);

  // per-player render state
  let players = [];        // {steamid,name,sideFirst,color,rows:{t,x,y,yaw,hp,armor,alive,side,w}}
  let killTicks = [];      // every kill (timeline dots; coords-independent)
  let killMarks = [];      // kills with attacker+victim coordinates (map lines)
  let layersData = null;   // lazy /viewer-layers payload (shots/economy)

  // ---- camera (Phase E M4): wheel zoom-to-cursor + drag pan ----
  const cam = window.ViewerCam ? ViewerCam.create() : { cx: 0, cy: 0, zoom: 1 };
  // world units -> map pixels conversion factor (replaces the old scale/4 fudge)
  function pxPerWorldUnit() {
    const b = D.map.bounds;
    return D.map.width / Math.max(b.max_x - b.min_x, 1);
  }

  function camScale() {
    return (drawMapLayer.geom ? drawMapLayer.geom.scale : 1) * cam.zoom;
  }

  function toScreen(wx, wy) {
    // world coords -> map pixel space -> screen space through the camera
    const b = D.map.bounds;
    const px = ((wx - b.min_x) / (b.max_x - b.min_x)) * D.map.width;
    const py = (1 - (wy - b.min_y) / (b.max_y - b.min_y)) * D.map.height;
    const wrap = document.querySelector('.ob-map-wrap');
    if (cam.cx == null) { cam.cx = D.map.width / 2; cam.cy = D.map.height / 2; }
    const S = camScale();
    return [
      wrap.clientWidth / 2 + (px - cam.cx) * S,
      wrap.clientHeight / 2 + (py - cam.cy) * S,
    ];
  }

  function segOfTick(tick) {
    for (const s of D.segments) if (tick >= s.start_tick && tick <= s.end_tick) return s;
    return null;
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
      armor: p.rows.armor[i], alive: p.rows.alive[i],
      side: SIDE_NAME[p.rows.side[i]] || '',
      w: (D.weapon_table || [])[p.rows.w[i]] || '',
      // v3 ammo/reload (absent rows resolve to undefined -> client guards)
      ammo: p.rows.am ? p.rows.am[i] : undefined,
      reload: p.rows.rl ? !!p.rows.rl[i] : false,
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
    // geometry must exist before any frame runs (map image loads async);
    // fall back to 1024 dims until the bitmap is decodable
    const iw = (mapImg && mapImg.naturalWidth) || 1024;
    const ih = (mapImg && mapImg.naturalHeight) || 1024;
    const scale = Math.min(w / iw, h / ih);
    drawMapLayer.geom = { scale };
    // 3D mode: the radar texture is drawn by the control layer's perspective
    // camera on fx-layer — the flat 2D basemap here would cover it
    if (state.toggles.ctrl3d) return;
    if (!mapImg) return;
    // camera transform: screen = viewCenter + (mapPx - camCenter) * scale * zoom
    if (window.ViewerCam) ViewerCam.resolve(cam, iw, ih);
    const S = scale * cam.zoom;
    const sx0 = w / 2 + (0 - cam.cx) * S;
    const sy0 = h / 2 + (0 - cam.cy) * S;
    ctx.globalAlpha = 0.92;
    ctx.drawImage(mapImg, sx0, sy0, iw * S, ih * S);
    ctx.globalAlpha = 1;
  }

  function playerPosAt(sid, tick) {
    const p = players.find((x) => x.steamid === sid);
    if (!p) return null;
    const st = playerStateAt(p, tick);
    if (!st.x && !st.y) return null;
    return [st.x, st.y];
  }

  function drawFxLayer(tick) {
    const wrap = document.querySelector('.ob-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('fx-layer'), w, h);
    ctx.clearRect(0, 0, w, h);
    if (!D || !window.ViewerOverlays) return;
    // map-control layer first (territory wash under all event overlays)
    if (window.ViewerControl && (state.toggles.control || state.toggles.ctrl3d)) {
      drawControlLayer(ctx, tick, w, h);
    }
    // 2D event overlays are skipped in 3D mode (perspective makes them wrong)
    if (state.toggles.ctrl3d) return;
    // advanced overlays (ported effect templates) live in viewer_overlays.js
    ViewerOverlays.draw({
      ctx,
      tick,
      TICK: D.tick_rate,
      events: D.events || {},
      layers: layersData || {},
      toggles: state.toggles,
      toScreen,
      worldDist: (dWorld) => dWorld * pxPerWorldUnit() * camScale(),
      posAt: playerPosAt,
    });
  }

  // ---- map control (Phase F M6): EMA-smoothed territory tint / 3D orbit ----
  let controlLegendBuilt = false;
  function controlPlayersAt(tick) {
    const out = [];
    for (const p of players) {
      const st = playerStateAt(p, tick);
      if (!st.alive) continue;
      out.push({ x: st.x, y: st.y, sideCode: p.rows.side[st.i] });
    }
    return out;
  }
  function drawControlLayer(ctx, tick, w, h) {
    const t0 = performance.now();
    const field = ViewerControl.update(tick, D.tick_rate, controlPlayersAt, D.map);
    if (state.toggles.ctrl3d) {
      // 3D: ground texture + columns + player dots rendered by the control
      // module's own perspective camera
      const players3d = [];
      for (const p of players) {
        const st = playerStateAt(p, tick);
        if (!st.alive) continue;
        const dimmed = state.focusSid && p.steamid !== state.focusSid;
        players3d.push({
          x: st.x, y: st.y,
          color: dimmed ? hexA(p.color, 0.18) : p.color,
          focus: state.focusSid === p.steamid,
        });
      }
      ViewerControl.render3D(ctx, D.map, field, w, h, mapImg, players3d);
    } else {
      ViewerControl.renderFlat(ctx, D.map, field, toScreen);
    }
    buildControlLegend();
    // perf probe (budget: p95 < 4ms; degrade 3D -> flat if blown repeatedly)
    const ms = performance.now() - t0;
    const dbg = (window.__viewerDebug = window.__viewerDebug || { timings: {} });
    dbg.timings = dbg.timings || {};
    dbg.timings.controlMs = ms;
    if (ms > 12 && state.toggles.ctrl3d) {
      controlSlowFrames = (controlSlowFrames || 0) + 1;
      if (controlSlowFrames > 60) {
        console.warn('control 3D frame budget blown (%.1fms avg) — falling back to flat', ms);
        state.toggles.ctrl3d = false;
        syncToolbarChips();
      }
    } else {
      controlSlowFrames = 0;
    }
  }
  let controlSlowFrames = 0;
  function buildControlLegend() {
    if (controlLegendBuilt) return;
    controlLegendBuilt = true;
    const wrap = document.querySelector('.ob-map-wrap');
    const el = document.createElement('div');
    el.className = 'control-legend';
    el.innerHTML =
      '<span class="cl-t">T 控制</span>' +
      '<span class="cl-bar"></span>' +
      '<span class="cl-ct">CT 控制</span>';
    wrap.appendChild(el);
  }

  // glyph wrappers shared with the main layer (implementations in viewer_overlays.js)
  // Marker scale grows with zoom, capped: ms = min(0.36·√z, 1).
  //   fit (z=1): ms=0.36 → dot r≈4px — players ~120u apart stay separated;
  //   zoomed (z≥7.7): ms=1 → r=11px — fully readable, never grows beyond.
  // Number label clamps to ≥9px so identity stays readable at any zoom.
  function markerScale() {
    const z = cam.zoom || 1;
    return Math.min(0.36 * Math.sqrt(z), 1);
  }

  // Number font: shrinks with ms but never below ~9px — the label is the
  // identity anchor and must stay readable even when dots are tiny.
  function labelFont(ms) {
    return `800 ${Math.max(12 * ms, 9)}px Consolas, monospace`;
  }

  // Label collision resolution: when two markers are closer than ~2.2 dot
  // radii, offset their number labels apart (up-right / down-left) with a
  // leader line so every player's number stays readable. OB-software staple.
  function resolveLabelOffsets(projected, ms) {
    const minDist = 24 * ms;   // label needs ~2.2 dot radii of separation
    const items = projected.filter((pr) => !pr.corpse);
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const a = items[i], b = items[j];
        const dx = b.sx - a.sx, dy = b.sy - a.sy;
        const d = Math.hypot(dx, dy);
        if (d >= minDist || d === 0) continue;
        // push labels apart along the a→b axis, half each
        const push = (minDist - d) / 2 + 6 * ms;
        const ux = dx / d, uy = dy / d;
        a.lox = (a.lox || 0) - ux * push;
        a.loy = (a.loy || 0) - uy * push;
        b.lox = (b.lox || 0) + ux * push;
        b.loy = (b.loy || 0) + uy * push;
      }
    }
  }

  function star(ctx, x, y, r) {
    if (window.ViewerOverlays) ViewerOverlays.star(ctx, x, y, r);
  }

  function skull(ctx, x, y) {
    if (window.ViewerOverlays) ViewerOverlays.skull(ctx, x, y);
  }

  function drawMainLayer(tick) {
    const wrap = document.querySelector('.ob-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('main-layer'), w, h); // setupCanvas clears
    if (!D) return;
    if (state.toggles.ctrl3d) return; // players render inside the 3D layer
    const windowT = 1.2 * D.tick_rate;
    // zoom-aware marker scale: readable when magnified, unchanged at fit (z=1)
    const ms = markerScale();
    // pass 1: project everyone + collect screen positions for label collision
    const projected = [];
    for (const p of players) {
      const st = playerStateAt(p, tick);
      if (!st.alive) {
        if ((st.x || st.y)) {
          const [sx, sy] = toScreen(st.x, st.y);
          projected.push({ p, st, sx, sy, corpse: true });
        }
        continue;
      }
      const [sx, sy] = toScreen(st.x, st.y);
      projected.push({ p, st, sx, sy, corpse: false });
    }
    // label collision: players within (2.2·dotR) vertically stack their labels
    resolveLabelOffsets(projected, ms);
    for (const pr of projected) {
      const { p, st, sx, sy } = pr;
      const focusA = state.focusSid ? (p.steamid === state.focusSid ? 1 : 0.12) : 1;
      if (pr.corpse) {
        if (focusA > 0.5) {
          ctx.globalAlpha = focusA;
          skull(ctx, sx, sy);
          ctx.globalAlpha = 1;
        }
        continue;
      }
      // trail: walk back through snapshots within the window (toggle-gated)
      if (state.toggles.trails !== false) {
        const rows = p.rows;
        let i0 = st.i;
        while (i0 > 0 && rows.t[st.i] - rows.t[i0] < windowT) i0--;
        ctx.lineWidth = 2.2 * ms;
        let prev = null;
        for (let i = i0; i <= st.j && i < rows.t.length; i++) {
          if (!rows.alive[i]) break;
          const [sx2, sy2] = toScreen(rows.x[i], rows.y[i]);
          if (prev && Math.hypot(sx2 - prev.sx, sy2 - prev.sy) * (1 / drawMapLayer.geom.scale) < BREAK_DIST) {
            const f = (i - i0) / Math.max(st.i - i0, 1);
            ctx.strokeStyle = hexA(p.color, (0.15 + 0.85 * f) * focusA);
            ctx.beginPath(); ctx.moveTo(prev.sx, prev.sy); ctx.lineTo(sx2, sy2); ctx.stroke();
          }
          prev = { sx: sx2, sy: sy2 };
        }
      }
      // marker + yaw fan (sizes tuned for readability: dot r≈11px at floor)
      const yawRad = (st.yaw * Math.PI) / 180;
      // Source yaw: 0 = +X, CCW. Screen y grows south -> dir = (cos(yaw), -sin(yaw)).
      // (Verified: 12613 moving samples, yaw vs atan2(vy,vx) circ error -0.8 deg.)
      const dx = Math.cos(yawRad), dy = -Math.sin(yawRad);
      const half = (YAW_FAN_DEG * Math.PI) / 360;
      const R = 30 * ms;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.arc(sx, sy, R, Math.atan2(dy, dx) - half, Math.atan2(dy, dx) + half);
      ctx.closePath();
      ctx.fillStyle = hexA(p.color, 0.35 * focusA); ctx.fill();
      ctx.beginPath(); ctx.arc(sx, sy, 11 * ms, 0, Math.PI * 2);
      ctx.fillStyle = hexA(p.color, focusA); ctx.fill();
      ctx.lineWidth = 2 * ms; ctx.strokeStyle = '#000'; ctx.stroke();
      // number label (identity anchor): offset above-right of the dot with a
      // leader line when markers collide; white on black outline
      const lx = sx + (pr.lox || 0), ly = sy + (pr.loy || 0);
      if (pr.lox || pr.loy) {
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(lx, ly);
        ctx.strokeStyle = 'rgba(0,0,0,.6)'; ctx.lineWidth = 1.2 * ms; ctx.stroke();
      }
      ctx.font = labelFont(ms);
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.lineWidth = 3 * ms; ctx.strokeStyle = 'rgba(0,0,0,.95)';
      ctx.strokeText(p.num, lx, ly);
      ctx.fillStyle = '#ffffff';
      ctx.fillText(p.num, lx, ly);
      if (state.focusSid === p.steamid) {
        // highlight ring on the focused player
        ctx.beginPath(); ctx.arc(sx, sy, 18 * ms, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(255,255,255,.85)'; ctx.lineWidth = 2.4 * ms; ctx.stroke();
      }
      // reload indicator: rotating amber dashed arc around the dot
      if (st.reload) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(sx, sy, 22 * ms, 0, Math.PI * 2);
        ctx.setLineDash([6, 4]);
        ctx.lineDashOffset = -tick / 3; // rotate as the reload progresses
        ctx.strokeStyle = 'rgba(255,176,46,.9)';
        ctx.lineWidth = 3 * ms;
        ctx.stroke();
        ctx.restore();
      }
      // zoom-gated LOD detail (Phase F M5): HP ring, ammo, weapon badge
      if (cam.zoom >= ZOOM_LOD && focusA > 0.5) drawLodDetail(ctx, st, sx, sy, ms);
    }
  }


  // zoom threshold where per-player detail fades in
  const ZOOM_LOD = 2.5;
  // weapon badge images pre-rasterized through WeaponMeta.getIconImage
  const _badgeCache = new Map(); // weapon short name -> Image | null(failed)
  function drawLodDetail(ctx, st, sx, sy, ms) {
    // HP ring: track arc around the dot (ok/warn/err by hp)
    const hpFrac = Math.max(0, Math.min(st.hp / 100, 1));
    ctx.beginPath(); ctx.arc(sx, sy, 17 * ms, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(255,255,255,.12)'; ctx.lineWidth = 4 * ms; ctx.stroke();
    if (hpFrac > 0) {
      ctx.beginPath();
      ctx.arc(sx, sy, 17 * ms, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * hpFrac);
      ctx.strokeStyle = st.hp > 50 ? C.ok : st.hp > 25 ? C.warn : C.err;
      ctx.lineWidth = 4 * ms; ctx.stroke();
    }
    // ammo readout at the dot's upper right (v3 payloads only)
    if (st.ammo != null) {
      ctx.font = `700 ${14 * ms}px Consolas, monospace`;
      ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
      ctx.lineWidth = 4 * ms; ctx.strokeStyle = '#000';
      ctx.strokeText(String(st.ammo), sx + 15 * ms, sy - 12 * ms);
      ctx.fillStyle = st.ammo === 0 ? C.err : '#e8edf4';
      ctx.fillText(String(st.ammo), sx + 15 * ms, sy - 12 * ms);
    }
    // weapon icon badge above the dot (zoom >= 3): light plate — the vendored
    // SVGs have no fill attr (default BLACK), so they need a light background
    if (cam.zoom >= 3 && window.WeaponMeta && st.w) {
      const img = _badgeCache.get(st.w);
      if (img && img.naturalWidth) {
        const bw = 36 * ms, bh = 20 * ms;
        const bx = sx - bw / 2, by = sy - 42 * ms;
        ctx.fillStyle = 'rgba(232, 237, 244, .92)';
        roundRect(ctx, bx, by, bw, bh, 4 * ms);
        ctx.fill();
        ctx.lineWidth = 1 * ms; ctx.strokeStyle = 'rgba(0,0,0,.5)'; ctx.stroke();
        const pad = 4 * ms;
        ctx.drawImage(img, bx + pad, by + (bh - (bh - pad * 2)) / 2, bw - pad * 2, bh - pad * 2);
      } else if (img === undefined) {
        // async load; draw nothing this frame, cache resolves later
        _badgeCache.set(st.w, null);
        WeaponMeta.getIconImage(st.w)
          .then((loaded) => _badgeCache.set(st.w, loaded))
          .catch((e) => console.warn('weapon badge load failed:', st.w, String(e)));
      }
    }
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
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
    // kill dots colored by the killer's side (slight jitter avoids overlap)
    const sideCol = { T: C.t, CT: C.ct };
    for (const k of D.events.kills || []) {
      const px = xOf(k.tick);
      const killer = players.find((p) => p.steamid === k.att);
      ctx.fillStyle = sideCol[killer && killer.sideFirst] || C.err;
      ctx.beginPath(); ctx.arc(px, 7 + ((k.tick >> 3) % 3) * 3, 2.2, 0, Math.PI * 2); ctx.fill();
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
      syncDeepLink();
      schedulePanelFlush(ts);
    } catch (err) {
      console.error('viewer frame error:', err);
    }
  }

  /** Keep ?round=N&t=S and the round selector in step with playback. */
  function syncDeepLink() {
    const seg = segOfTick(state.tick);
    if (!seg || seg.round === state.lastLinkedRound) return;
    state.lastLinkedRound = seg.round;
    const sel = $('sel-round');
    if (sel && sel.value !== String(seg.round)) sel.value = String(seg.round);
    const t = Math.max(0, Math.round((state.tick - seg.start_tick) / D.tick_rate));
    try {
      history.replaceState(null, '', `/demo/${HASH}/viewer?round=${seg.round}&t=${t}`);
    } catch (e) { /* sandboxed contexts */ }
  }

  function updateHudTexts() {
    const seg = segOfTick(state.tick);
    const rl = $('round-label'), timer = $('round-timer'), cur = $('cur-tick');
    cur.textContent = 'tick ' + Math.round(state.tick);
    if (!seg) { rl.textContent = '回合 -'; timer.textContent = '-'; setScores(null); setBombTimer(null); return; }
    rl.textContent = '回合 ' + seg.round;
    const remain = Math.max(D.round_clock_seconds - (state.tick - seg.start_tick) / D.tick_rate, 0);
    const mm = Math.floor(remain / 60), ss = Math.floor(remain % 60);
    timer.textContent = mm + ':' + String(ss).padStart(2, '0');
    setScores(seg);
    setBombTimer(seg);
  }

  /** Bomb countdown beside the round clock once the bomb is down (40s fuse). */
  function setBombTimer(seg) {
    const el = document.getElementById('bomb-timer');
    if (!el) return;
    let planted = null;
    if (seg) {
      for (const b of (D.events.bombs || [])) {
        if (b.type === 'plant' && b.tick >= seg.start_tick && b.tick <= state.tick) planted = b;
        if (planted && (b.type === 'defuse' || b.type === 'explode') &&
            b.tick > planted.tick && b.tick <= state.tick) { planted = null; break; }
      }
    }
    if (!planted) { el.hidden = true; return; }
    const left = Math.max(0, 40 - (state.tick - planted.tick) / D.tick_rate);
    el.hidden = false;
    el.textContent = '💣 ' + Math.floor(left / 60) + ':' + String(Math.ceil(left % 60)).padStart(2, '0');
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
      // number chip (1-0) — same label as the map marker
      const nameEl = li.querySelector('.ob-name');
      const num = document.createElement('span');
      num.className = 'ob-num';
      num.style.borderColor = p.color;
      num.style.color = p.color;
      num.textContent = p.num;
      num.title = `编号 ${p.num} · ${p.name}`;
      const txt = document.createElement('span');
      txt.className = 'ob-name-text';
      txt.textContent = p.name;
      nameEl.replaceChildren(num, txt);
      // click to focus/highlight this player (works in live + overlap modes)
      li.title = '点击高亮该选手，再点取消';
      li.classList.add('ob-row--clickable');
      li.addEventListener('click', () => {
        state.focusSid = state.focusSid === p.steamid ? null : p.steamid;
        syncPanelFocus();
      });
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

  function syncPanelFocus() {
    for (const [sid, li] of Object.entries(panelRows)) {
      li.classList.toggle('is-focus', state.focusSid === sid);
    }
  }

  function schedulePanelFlush(ts) {
    if (ts - lastFlush < 100) return;
    lastFlush = ts;
    flushPanels();
    updateKillFeed();
  }

  // ---- kill feed widget (rolling 12s window, newest first, capped at 5) ----
  let lastFeedSig = '';
  function updateKillFeed() {
    const ul = document.getElementById('kill-feed');
    if (!ul || !D) return;
    const windowT = 12 * D.tick_rate;
    const recent = (D.events.kills || []).filter((k) => k.tick <= state.tick && k.tick > state.tick - windowT);
    const shown = recent.slice(-5).reverse();
    const sig = shown.map((k) => k.tick + ':' + k.att + '>' + k.vic).join('|');
    if (sig === lastFeedSig) return;
    lastFeedSig = sig;
    ul.innerHTML = '';
    for (const k of shown) {
      const li = document.createElement('li');
      const ak = players.find((p) => p.steamid === k.att);
      const vk = players.find((p) => p.steamid === k.vic);
      const sideCls = (p) => (p ? (p.sideFirst === 'T' ? ' t-text' : p.sideFirst === 'CT' ? ' ct-text' : '') : '');
      li.innerHTML =
        '<span class="kf-a' + sideCls(ak) + '"></span>' +
        '<img class="kf-w wpn-ico" alt="" draggable="false"><span class="kf-x">✖</span>' +
        '<span class="kf-v' + sideCls(vk) + '"></span>';
      li.querySelector('.kf-a').textContent = k.an || '?';
      const wName = (D.weapon_table || [])[k.wi] || '';
      const wEl = li.querySelector('.kf-w');
      if (window.WeaponMeta && wName) {
        wEl.src = WeaponMeta.iconUrl(wName);
        wEl.title = WeaponMeta.label(wName);
      } else {
        wEl.remove();
        li.querySelector('.kf-x').insertAdjacentHTML('beforebegin',
          '<span class="kf-w"></span>');
        // fall back to text when icons are unavailable
        li.querySelectorAll('.kf-w').forEach((el) => { el.textContent = wName; });
      }
      li.querySelector('.kf-v').textContent = k.vn || '?';
      if (k.hs) { const b = document.createElement('span'); b.className = 'kf-hs'; b.textContent = 'HS'; li.appendChild(b); }
      ul.appendChild(li);
    }
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
        const sig = [st.hp, st.w, st.alive, st.armor, st.ammo, st.reload].join('|');
        if (lastVals[key] === sig) return;
        lastVals[key] = sig;
        const wEl = li.querySelector('.ob-wpn');
        const wName = st.w || '';
        if (window.WeaponMeta && wName) {
          // icon + tooltip + ammo readout (dense OB layout)
          const sigW = wName + ':' + (st.ammo != null ? st.ammo : '');
          if (wEl.dataset.w !== sigW) {
            wEl.dataset.w = sigW;
            wEl.innerHTML = '';
            const img = document.createElement('img');
            img.className = 'wpn-ico'; img.alt = ''; img.draggable = false;
            img.src = WeaponMeta.iconUrl(wName);
            img.title = WeaponMeta.label(wName);
            wEl.appendChild(img);
            if (st.ammo != null) {
              const n = document.createElement('span');
              n.className = 'ob-ammo' + (st.ammo === 0 ? ' empty' : '');
              n.textContent = st.ammo;
              wEl.appendChild(n);
            }
            if (st.reload) {
              const r = document.createElement('span');
              r.className = 'ob-reloading';
              r.textContent = '换弹';
              wEl.appendChild(r);
            }
          }
        } else {
          wEl.textContent = wName;
        }
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
    // panel header names follow the LIVE side occupying each panel (teams swap
    // at halftime; the header must not keep showing a stale side)
    const tName = buckets.T.length ? (D.teams && teamNameForSide('T', state.tick)) || 'T' : 'T';
    const ctName = buckets.CT.length ? (D.teams && teamNameForSide('CT', state.tick)) || 'CT' : 'CT';
    const tEl = document.querySelector('.ob-team--t .ob-side-name');
    const ctEl = document.querySelector('.ob-team--ct .ob-side-name');
    if (tEl) tEl.textContent = tName;
    if (ctEl) ctEl.textContent = ctName;
  }

  /** Real team name currently playing `side` at `tick` (halftime-swap aware). */
  function teamNameForSide(side, tick) {
    // segments carry winner_side; find which real team won as `side` most
    // recently at/before tick — cheap heuristic: last segment ≤ tick
    let seg = null;
    for (const s of D.segments) {
      if (s.start_tick <= tick) seg = s; else break;
    }
    if (!seg) return side;
    // teams.t/ct are the STARTING sides (begin_new_match); after a side swap
    // the names flip. Winner side tells us the mapping at this segment.
    const starts = { T: D.teams?.t || 'T', CT: D.teams?.ct || 'CT' };
    // if the segment's round is in the second half (side swap), flip
    const swapped = seg.round > Math.ceil(D.segments.length / 2);
    return swapped ? (side === 'T' ? starts.CT : starts.T) : starts[side];
  }

  // ---- data load ----
  async function load() {
    try {
      const res = await fetch('/api/demo/' + HASH + '/viewer-data?v=' + Date.now());
      if (!res.ok) throw new Error('HTTP ' + res.status);
      D = await res.json();
      totalTicks = D.segments[D.segments.length - 1].end_tick;
      state.tick = D.segments[0].start_tick; // start at the first round, not tick 0

      // per-player identity: number label (1-0) + stable color from STARTING
      // side (warm palette = starting T, cool = starting CT — identity, not
      // live side; the live side drives the panel columns)
      const sideCount = { T: 0, CT: 0 };
      players = D.players.map((rows, i) => {
        const firstCode = rows.side.find((s) => s !== 2);
        const firstSide = SIDE_NAME[firstCode] || 'CT';
        const pal = firstSide === 'T' ? T_PALETTE : CT_PALETTE;
        const idx = sideCount[firstSide]++;
        return {
          steamid: rows.steamid,
          name: (D.roster.find(r => r.steamid === rows.steamid) || {}).name || rows.steamid,
          sideFirst: firstSide,
          num: String((i + 1) % 10),  // 1..9, 0 — unique per player
          rows, color: pal[idx % pal.length],
        };
      });

      killTicks = (D.events.kills || []).map((k) => k.tick).sort((a, b) => a - b);
      killMarks = (D.events.kills || [])
        .filter((k) => Number.isFinite(k.ax) && Number.isFinite(k.vx))
        .sort((a, b) => a.tick - b.tick);

      // real team names from the demo header (starting sides; panel headers
      // re-derive the live mapping per tick in flushPanels)
      if (D.teams) {
        if (D.teams.t || D.teams.ct) {
          const tEl = document.querySelector('.ob-team--t .ob-side-name');
          const ctEl = document.querySelector('.ob-team--ct .ob-side-name');
          if (tEl && D.teams.t) tEl.textContent = D.teams.t;
          if (ctEl && D.teams.ct) ctEl.textContent = D.teams.ct;
        }
      }

      // deep link ?round=N&t=S (seconds into the round)
      const q = new URLSearchParams(location.search);
      const qRound = Number(q.get('round'));
      if (qRound) {
        const seg = D.segments.find((s) => s.round === qRound);
        if (seg) {
          state.tick = Math.min(seg.start_tick + Math.max(0, Number(q.get('t')) || 0) * D.tick_rate,
                                seg.end_tick);
        }
      }

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
      if (qRound) sel.value = String(qRound); // deep link keeps the selector in sync

      // heavy overlay layers (shots/economy): fetch shortly after first paint
      setTimeout(() => {
        fetch('/api/demo/' + HASH + '/viewer-layers?with=shots,economy')
          .then((r) => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
          .then((j) => { layersData = j; })
          .catch(() => { /* toggle stays inert; base overlays unaffected */ });
      }, 1500);

      wireControls();
      buildToolbar();
      drawMapLayer(); // lay out map geometry before any frame reads it
      window.__viewerDebug = { state, players, D, playerStateAt, cam }; // dev probe
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

    // ---- camera: wheel zoom-to-cursor + drag pan + reset (R / dblclick) ----
    const wrap = document.querySelector('.ob-map-wrap');
    const camView = () => ({ w: wrap.clientWidth, h: wrap.clientHeight });
    const redrawMap = () => drawMapLayer();
    wrap.addEventListener('wheel', (e) => {
      e.preventDefault();
      if (state.toggles.ctrl3d && window.ViewerControl) {
        ViewerControl.dolly(Math.exp(e.deltaY * 0.0012)); // wheel = dolly in 3D
        return;
      }
      if (!drawMapLayer.geom) return;
      const rect = wrap.getBoundingClientRect();
      const cursor = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      ViewerCam.zoomAt(cam, cursor, Math.exp(-e.deltaY * 0.0015), camView(),
        drawMapLayer.geom.scale, D.map.width, D.map.height, 1, 8);
      redrawMap();
    }, { passive: false });
    // pointer capture is deferred until the drag threshold is crossed so plain
    // clicks (toolbar chips inside the wrap!) still receive their native click
    const pan = { on: false, id: -1, x: 0, y: 0, moved: false };
    wrap.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      // toolbar chips are interactive DOM inside the wrap — they own their gestures
      if (e.target.closest && e.target.closest('.ob-toolbar')) return;
      pan.on = true; pan.id = e.pointerId; pan.moved = false;
      pan.x = e.clientX; pan.y = e.clientY;
    });
    wrap.addEventListener('pointermove', (e) => {
      if (!pan.on || e.pointerId !== pan.id) return;
      const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
      if (!pan.moved) {
        if (Math.hypot(dx, dy) < 4) return; // click vs drag threshold
        pan.moved = true;
        try { wrap.setPointerCapture(pan.id); } catch (err) { /* pointer gone */ }
      }
      pan.x = e.clientX; pan.y = e.clientY;
      // 3D mode: drag orbits the perspective camera (ground texture redraws
      // every frame in drawFxLayer — no explicit redraw needed)
      if (state.toggles.ctrl3d && window.ViewerControl) {
        ViewerControl.orbit(dx * 0.005, dy * 0.004);
        return;
      }
      if (!drawMapLayer.geom) return;
      ViewerCam.panBy(cam, dx, dy, camView(), drawMapLayer.geom.scale,
        D.map.width, D.map.height);
      redrawMap();
    });
    wrap.addEventListener('pointerup', (e) => {
      if (e.pointerId !== pan.id) return;
      pan.on = false;
      try { if (wrap.hasPointerCapture && wrap.hasPointerCapture(pan.id)) wrap.releasePointerCapture(pan.id); } catch (err) { /* noop */ }
    });
    const resetCam = (e) => {
      // dblclick on toolbar chips must not reset the camera
      if (e && e.target && e.target.closest && e.target.closest('.ob-toolbar')) return;
      if (state.toggles.ctrl3d && window.ViewerControl) {
        ViewerControl.reset3d(D.map); // 3D has its own camera
        return;
      }
      ViewerCam.reset(cam); redrawMap();
    };
    wrap.addEventListener('dblclick', resetCam);
    document.getElementById('btn-cam-reset')?.addEventListener('click', resetCam);

    // ---- timeline scrub + hover tooltip ----
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
      else if (e.code === 'KeyR') resetCam();
      else if (e.code === 'Escape' && state.focusSid) {
        state.focusSid = null;
        syncPanelFocus();
      }
      else if (/^[1-9]$/.test(e.key)) {
        const v = Number(e.key);
        // only accept speeds the select actually offers (keeps UI in sync)
        if ([...$('sel-speed').options].some((o) => o.value === e.key)) {
          state.speed = v; $('sel-speed').value = e.key;
        }
      }
    });
    window.addEventListener('resize', () => { drawMapLayer(); });
  }

  // ---- overlay toolbar: chip toggles bound to state.toggles + localStorage ----
  let toolbarChips = {}; // key -> chip element
  function buildToolbar() {
    const bar = document.getElementById('ob-toolbar');
    if (!bar) return;
    const labels = [
      ['trails', '轨迹'], ['kills', '击杀线'], ['nades', '道具'],
      ['shots', '枪线'], ['blinds', '闪光'], ['bombs', '炸弹'],
      ['control', '控图'], ['ctrl3d', '3D'],
    ];
    bar.innerHTML = '';
    toolbarChips = {};
    for (const [key, label] of labels) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip' + (state.toggles[key] ? ' on' : '');
      chip.textContent = label;
      chip.addEventListener('click', () => {
        state.toggles[key] = !state.toggles[key];
        // 3D and flat tint are mutually exclusive modes of one layer
        if (key === 'control' && state.toggles.control) state.toggles.ctrl3d = false;
        if (key === 'ctrl3d' && state.toggles.ctrl3d) { state.toggles.control = true; ViewerControl.reset(); }
        if (key === 'control' && !state.toggles.control) state.toggles.ctrl3d = false;
        if (!state.toggles.control) {
          const legend = document.querySelector('.control-legend');
          if (legend) { legend.remove(); controlLegendBuilt = false; }
        }
        // 2D basemap <-> 3D ground texture swap lives on the map-layer canvas;
        // it only repaints on explicit redraws, so force one on mode change
        if (key === 'ctrl3d' || key === 'control') drawMapLayer();
        syncToolbarChips();
        try { localStorage.setItem('csa-viewer-toggles', JSON.stringify(state.toggles)); } catch (e) {}
      });
      toolbarChips[key] = chip;
      bar.appendChild(chip);
    }
  }

  function syncToolbarChips() {
    for (const [key, chip] of Object.entries(toolbarChips)) {
      chip.classList.toggle('on', !!state.toggles[key]);
      // 3D chip only meaningful when the control layer is on
      if (key === 'ctrl3d') chip.disabled = !state.toggles.control;
    }
  }

  load();
})();
