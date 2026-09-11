// Real-time 2D map replay viewer (Phase C M3): layered canvases, rAF loop,
// tick-domain timeline. Data: /api/demo/{hash}/viewer-data (8 Hz snapshots).
(function () {
  // tolerate all four route shapes: /demo|match/{h}/viewer (replay) and
  // /demo|match/{h}/overlap (legacy bookmark → replay in overlap sub-mode)
  const m = location.pathname.match(/\/(?:demo|match)\/([^/]+)\/(?:viewer|overlap)/);
  if (!m) return;
  const HASH = m[1];

  // ---- palette (matches style.css Phase G violet tokens) ----
  const C = {
    t: '#ffb02e', ct: '#3d9bff', text: '#eceaf6', muted: '#9aa0b8',
    err: '#ff4d5e', ok: '#3ddc97', warn: '#ffb02e', accent: '#a78bfa',
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
  const TOGGLE_DEFAULTS = { trails: true, kills: true, nades: true, shots: false, blinds: true, bombs: true, control: false, ctrl3d: false, buys: true, ovpatterns: false };
  const state = {
    playing: false,
    tick: 0,
    speed: 1,
    lastTs: 0,
    holdUntil: 0,          // wall-clock ms pause at round end
    toggles: Object.assign({}, TOGGLE_DEFAULTS),  // overlay switches (persisted)
    lastLinkedRound: null, // last round written to the deep-link URL
    focusSid: null,        // clicked player (highlight; others dimmed)
    overlap: false,        // Phase J: overlap sub-mode (rounds superimposed)
    ovPhase: 0.15,         // round-relative phase 0..1 in overlap mode
    ovHalf: 1,             // 1 = first half, 2 = second half
    ovRounds: new Set(),   // K2a: explicitly included rounds; EMPTY = all shown
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
    // Phase J: tail-gap ticks (a few ticks past a round's end, before the
    // next freeze-end) fall back to the PREVIOUS segment — playback never
    // flashes "回合 -" while crossing the seam, and bomb state stays put.
    let last = null;
    for (const s of D.segments) {
      if (tick >= s.start_tick && tick <= s.end_tick) return s;
      if (tick >= s.end_tick) last = s;
    }
    return last;
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
    ctx.fillStyle = '#07070d';
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
    // map-control layer first (territory wash under all event overlays) —
    // meaningless against a cross-round synthetic stream, so overlap skips it
    if (window.ViewerControl && (state.toggles.control || state.toggles.ctrl3d)
        && !state.overlap) {
      drawControlLayer(ctx, tick, w, h);
    }
    // 2D event overlays are skipped in 3D mode (perspective makes them wrong)
    if (state.toggles.ctrl3d) return;
    // overlap sub-mode: events from every round of the half, shifted to the
    // shared phase timeline (same semantics as the standalone overlap page)
    let events = D.events || {};
    let fxTick = tick;
    let seg = segOfTick(tick);
    if (state.overlap) {
      const segs = effectiveOvSegs();   // K2a: honor the round-grid filter
      const span = ovSpanOf(segs);
      fxTick = state.ovPhase * span;
      seg = null; // cross-round synthetic stream — bomb clamping not applicable
      const rel = (arr) => {
        const out = [];
        for (const s of segs) {
          for (const e of (arr || [])) {
            if (e.tick < s.start_tick || e.tick > s.end_tick) continue;
            out.push({ ...e, tick: e.tick - s.start_tick });
          }
        }
        out.sort((a, b) => a.tick - b.tick);
        return out;
      };
      events = {
        utilities: rel(events.utilities),
        kills: rel(events.kills),
        bombs: rel(events.bombs),
        blinds: rel(events.blinds),
      };
    }
    // advanced overlays (ported effect templates) live in viewer_overlays.js
    ViewerOverlays.draw({
      ctx,
      tick: fxTick,
      TICK: D.tick_rate,
      seg,
      events,
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
  // U3 v2: fresh kill sites for engagement decay (≤ fight_ttl seconds old)
  ViewerControl.setFightProvider((tick) => {
    if (!ViewerPrefs || ViewerPrefs.get('control.v2') < 0.5) return null;
    const ttl = (ViewerPrefs.get('control.fight_ttl') || 6) * D.tick_rate;
    const out = [];
    for (const k of D.events.kills || []) {
      if (tick - k.tick < 0 || tick - k.tick > ttl) continue;
      // kill site = midpoint of attacker/victim when both known
      const x = (k.ax != null && k.vx != null) ? (k.ax + k.vx) / 2 : (k.ax != null ? k.ax : k.vx);
      const y = (k.ay != null && k.vy != null) ? (k.ay + k.vy) / 2 : (k.ay != null ? k.ay : k.vy);
      if (x == null || y == null) continue;
      out.push({ x, y, tick: k.tick });
    }
    return out;
  });
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
  // Marker scale grows superlinearly with zoom, capped:
  //   ms = min(fit · z^exp, cap) — all three tunable in the ⚙ panel
  //   (ViewerPrefs; defaults 0.54 / 0.6 / 2 → fit r≈6px, z=8 r≈21px).
  // Number label clamps to a floor so identity stays readable at any zoom.
  function markerScale() {
    const z = cam.zoom || 1;
    const P = window.ViewerPrefs;
    const fit = P ? P.get('marker.fit') : 0.54;
    const exp = P ? P.get('marker.exp') : 0.6;
    const cap = P ? P.get('marker.cap') : 2;
    return Math.min(fit * Math.pow(z, exp), cap);
  }

  // Number font: shrinks with ms but never below the floor — the label is the
  // identity anchor and must stay readable even when dots are tiny.
  function labelFont(ms) {
    const P = window.ViewerPrefs;
    const scale = P ? P.get('label.scale') : 12;
    const min = P ? P.get('label.min') : 9;
    return `800 ${Math.max(scale * ms, min)}px Consolas, monospace`;
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

  // ---- overlap sub-mode (Phase J): all rounds of one half superimposed at
  // the same round-relative phase. Semantics ported from viewer_overlap.js —
  // live-side coloring, ghost dimming, focus tracking. ----
  const OV_T_PALETTE = ['#ffd54f', '#ffb02e', '#ff8f00', '#ff7043', '#f4511e'];
  const OV_CT_PALETTE = ['#81d4fa', '#3d9bff', '#00bcd4', '#0288d1', '#1565c0'];
  // Halves are NOT half-of-count (the naive ceil(n/2) split put MR12 rounds
  // 9-12 into "half 2" — user-caught). The real split is the side swap:
  // classify each segment by where the STARTING-T roster actually plays that
  // round — majority on T = first half, majority on CT = second half.
  // (Overtime alternates per pair of rounds after 24; this library has none.)
  let ovHalfGroups = null;  // [[firstHalfSegs], [secondHalfSegs]]
  function ovHalfGroupsOf() {
    if (ovHalfGroups) return ovHalfGroups;
    const starters = players.filter((p) => p.sideFirst === 'T');
    const groups = [[], []];
    for (const s of D.segments) {
      const mid = s.start_tick + (s.end_tick - s.start_tick) / 2;
      let onT = 0, onCT = 0;
      for (const p of starters) {
        const st = playerStateAt(p, mid);
        if ((SIDE_NAME[p.rows.side[st.i]] || '') === 'CT') onCT++;
        else onT++;
      }
      groups[onCT > onT ? 1 : 0].push(s);
    }
    ovHalfGroups = groups;
    return groups;
  }
  function ovHalfRounds(half) {
    return ovHalfGroupsOf()[half === 2 ? 1 : 0];
  }
  /** K2a: rounds of the current half AFTER the round-grid filter.
   *  Empty selection = every round (legacy overlap-page semantics). */
  function effectiveOvSegs() {
    const segs = ovHalfRounds(state.ovHalf);
    if (!state.ovRounds.size) return segs;
    return segs.filter((s) => state.ovRounds.has(s.round));
  }
  function ovSpanOf(segs) {
    return segs.length ? Math.max(segs[0].end_tick - segs[0].start_tick - 2, 1) : 1;
  }
  // K2c: opening-route pattern clusters (pure-JS k-means, deterministic)
  const CLUSTER_COLORS = ['#a78bfa', '#f472b6', '#2dd4bf'];
  let ovClusterCache = { key: null, assign: new Map() };
  function computeOvClusters() {
    // Feature: the ATTACKING (T-side) team-centroid path — 6 samples over the
    // opening phase 0..0.3 of each round (live side, so halftime swaps work).
    const segs = ovHalfRounds(state.ovHalf);
    const feats = segs.map((seg) => {
      const pts = [];
      for (let k = 0; k < 6; k++) {
        const tick = seg.start_tick + (0.3 * k) / 5 * (seg.end_tick - seg.start_tick);
        let sx = 0, sy = 0, n = 0;
        for (const p of players) {
          const st = playerStateAt(p, tick);
          if (!st.alive) continue;
          if ((SIDE_NAME[p.rows.side[st.i]] || '') !== 'T') continue;
          sx += st.x; sy += st.y; n++;
        }
        pts.push(n ? [sx / n, sy / n] : [0, 0]);
      }
      return pts.flat();
    });
    const assign = new Map();
    if (!feats.length) { ovClusterCache = { key: state.ovHalf, assign }; return assign; }
    const dist2 = (a, b) => a.reduce((s, v, i) => s + (v - b[i]) * (v - b[i]), 0);
    const kMeans = (k) => {
      // deterministic farthest-first init (fixed seed semantics — no RNG)
      const cent = [feats[0].slice()];
      while (cent.length < k) {
        let best = 0, bestD = -1;
        for (let i = 0; i < feats.length; i++) {
          const d = Math.min(...cent.map((c) => dist2(feats[i], c)));
          if (d > bestD) { bestD = d; best = i; }
        }
        cent.push(feats[best].slice());
      }
      const lab = new Array(feats.length).fill(0);
      for (let it = 0; it < 12; it++) {
        let moved = false;
        for (let i = 0; i < feats.length; i++) {
          let bi = 0, bd = Infinity;
          for (let c = 0; c < cent.length; c++) {
            const d = dist2(feats[i], cent[c]);
            if (d < bd) { bd = d; bi = c; }
          }
          if (lab[i] !== bi) { lab[i] = bi; moved = true; }
        }
        for (let c = 0; c < cent.length; c++) {
          const members = feats.filter((_, i) => lab[i] === c);
          if (!members.length) continue;
          cent[c] = members[0].map((_, dim) => members.reduce((s, f) => s + f[dim], 0) / members.length);
        }
        if (!moved && it > 0) break;
      }
      const inertia = feats.reduce((s, f, i) => s + dist2(f, cent[lab[i]]), 0);
      return { lab, inertia };
    };
    const k2 = kMeans(2), k3 = kMeans(3);
    // elbow: k=3 only pays for itself when inertia drops substantially
    const useK3 = k2.inertia > 0 && k3.inertia / k2.inertia < 0.55 && feats.length >= 6;
    const pick = useK3 ? k3 : k2;
    segs.forEach((s, i) => assign.set(s.round, pick.lab[i] % CLUSTER_COLORS.length));
    ovClusterCache = { key: state.ovHalf, assign };
    return assign;
  }
  function clusterOfRound(round) {
    if (ovClusterCache.key !== state.ovHalf) computeOvClusters();
    const c = ovClusterCache.assign.get(round);
    return (c == null) ? 0 : c;
  }
  function drawOverlapLayer() {
    const wrap = document.querySelector('.ob-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('main-layer'), w, h); // setupCanvas clears
    if (!D) return;
    const ms = markerScale();
    const windowT = 6 * D.tick_rate;
    const segs = effectiveOvSegs();          // K2a: round-grid filter
    const span = ovSpanOf(segs);
    const phaseTick = state.ovPhase * span;
    const SIDE_NAME = ['T', 'CT', ''];
    const ghostA = window.ViewerPrefs ? ViewerPrefs.get('overlap.ghost_alpha') : 0.14;
    const breakDist = window.ViewerPrefs ? ViewerPrefs.get('overlap.break_dist') : 300;
    const usePatterns = !!state.toggles.ovpatterns && segs.length > 1;

    // K2d: focused player vs own-side centroid deviation lines (violet, faint)
    let devSum = 0, devN = 0;
    if (state.focusSid) {
      const fp = players.find((q) => q.steamid === state.focusSid);
      if (fp) {
        ctx.save();
        ctx.setLineDash([4 * ms, 4 * ms]);
        ctx.strokeStyle = 'rgba(167,139,250,.55)';
        ctx.lineWidth = 1.6 * ms;
        for (const seg of segs) {
          const tick = seg.start_tick + phaseTick;
          const fst = playerStateAt(fp, tick);
          if (!fst.alive) continue;
          const side = SIDE_NAME[fp.rows.side[fst.i]] || 'CT';
          let cx = 0, cy = 0, n = 0;
          for (const p of players) {
            const st = playerStateAt(p, tick);
            if (!st.alive) continue;
            if ((SIDE_NAME[p.rows.side[st.i]] || '') !== side) continue;
            cx += st.x; cy += st.y; n++;
          }
          if (!n) continue;
          cx /= n; cy /= n;
          const [ax, ay] = toScreen(fst.x, fst.y);
          const [bx, by] = toScreen(cx, cy);
          ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
          devSum += Math.hypot(fst.x - cx, fst.y - cy); devN++;
        }
        ctx.restore();
      }
    }
    const devEl = document.getElementById('ov-focus-dev');
    if (devEl) {
      if (state.focusSid && devN) {
        const meanU = devSum / devN;
        devEl.textContent = '偏差 ' + Math.round(meanU) + 'u · ' + (meanU * 0.019).toFixed(1) + 'm';
        devEl.hidden = false;
      } else devEl.hidden = true;
    }

    for (const seg of segs) {
      // K2c: pattern coloring recolors the trail strokes per round cluster
      const cluColor = usePatterns ? CLUSTER_COLORS[clusterOfRound(seg.round)] : null;
      for (const p of players) {
        const isFocus = state.focusSid === p.steamid;
        // ghost dimming: focused player full, everyone else at ghost alpha
        const alpha = state.focusSid ? (isFocus ? 1 : ghostA) : 0.9;
        const tick = seg.start_tick + phaseTick;
        const st = playerStateAt(p, tick);
        if (!st.alive) continue;
        const liveSide = SIDE_NAME[p.rows.side[st.i]] || 'CT';
        const color = liveSide === 'T'
          ? OV_T_PALETTE[parseInt(p.num, 10) % OV_T_PALETTE.length]
          : OV_CT_PALETTE[parseInt(p.num, 10) % OV_CT_PALETTE.length];
        if (alpha < 0.03) continue;
        // trail (round-relative window) — 轨迹 chip gates it like in replay
        const rows = p.rows;
        if (state.toggles.trails !== false) {
          const winSec = isFocus
            ? (window.ViewerPrefs ? ViewerPrefs.get('trail.focus_window_s') : 10)
            : (window.ViewerPrefs ? ViewerPrefs.get('trail.window_s') : 6);
          const win = winSec * D.tick_rate;
          ctx.lineWidth = (window.ViewerPrefs ? ViewerPrefs.get('trail.width') : 2)
            * (isFocus ? 1.6 : 1) * ms;
          let i0 = st.i;
          while (i0 > 0 && rows.t[st.i] - rows.t[i0] < win) i0--;
          let prev = null;
          // stride 3 (~2.7Hz effective): 8 rounds × 10 players × 6s windows
          // would otherwise push ~30k line segments per redraw
          for (let i = i0; i <= st.i && i < rows.t.length; i += 3) {
            if (!rows.alive[i]) break;
            const [sx, sy] = toScreen(rows.x[i], rows.y[i]);
            if (prev && Math.hypot(sx - prev.sx, sy - prev.sy) * (1 / drawMapLayer.geom.scale) < breakDist) {
              const f = (i - i0) / Math.max(st.i - i0, 1);
              const base = cluColor || color;
              ctx.strokeStyle = hexA(base, alpha * (0.12 + 0.85 * f));
              ctx.beginPath(); ctx.moveTo(prev.sx, prev.sy); ctx.lineTo(sx, sy); ctx.stroke();
            }
            prev = { sx, sy };
          }
        }
        const [sx, sy] = toScreen(st.x, st.y);
        ctx.beginPath(); ctx.arc(sx, sy, 11 * ms, 0, Math.PI * 2);
        ctx.fillStyle = hexA(color, alpha); ctx.fill();
        ctx.lineWidth = 2 * ms; ctx.strokeStyle = '#000'; ctx.stroke();
        ctx.font = labelFont(ms);
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.lineWidth = 3 * ms; ctx.strokeStyle = 'rgba(0,0,0,.95)';
        ctx.strokeText(p.num, sx, sy);
        ctx.fillStyle = alpha > 0.5 ? '#ffffff' : '#08080f';
        ctx.fillText(p.num, sx, sy);
        if (isFocus) {
          ctx.beginPath(); ctx.arc(sx, sy, 18 * ms, 0, Math.PI * 2);
          ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 2.4 * ms; ctx.stroke();
        }
      }
    }
  }
  function setOverlapMode(on) {
    state.overlap = on && D && D.segments.length > 0;
    state.playing = false;
    $('btn-play').textContent = '播放';
    const tl = document.getElementById('tl-wrap');
    const controls = document.getElementById('ov-controls');
    const metricsWrap = document.getElementById('ov-metrics-wrap');
    if (tl) tl.hidden = state.overlap;
    if (controls) controls.hidden = !state.overlap;
    if (metricsWrap) metricsWrap.hidden = !state.overlap;
    // replay-only HUD bits hide in overlap mode
    for (const id of ['bomb-timer', 'buy-strip', 'round-timer']) {
      const el = document.getElementById(id);
      if (el) el.hidden = state.overlap;
    }
    if (state.overlap) {
      buildOvRoundStrip();   // K2a: per-half round grid
      ovMetricsCache = null; // K2b: recompute for this half
      ovClusterCache = { key: null, assign: new Map() };
      lastOverlapSig = '';   // force a fresh overlay render
      syncOvPhaseUI();
      const ovPlay = document.getElementById('ov-play');
      if (ovPlay) { ovPlay.textContent = '▶ 播放'; ovPlay.classList.remove('on'); }
    }
    syncToolbarChips();
    // deep link: ?mode=overlap is the truth
    try {
      const url = new URL(location.href);
      if (state.overlap) url.searchParams.set('mode', 'overlap');
      else url.searchParams.delete('mode');
      history.replaceState(null, '', url);
    } catch (e) { /* sandboxed */ }
    drawMapLayer();
  }
  /** Reflect state.ovPhase onto the slider + phase clock readout. */
  function syncOvPhaseUI() {
    const slider = document.getElementById('ov-phase');
    if (slider) slider.value = String(Math.round(state.ovPhase * 1150));
    const val = document.getElementById('ov-phase-val');
    if (val && D) {
      const span = ovSpanOf(effectiveOvSegs());
      const sec = Math.max(0, Math.round(state.ovPhase * span / D.tick_rate));
      val.textContent = Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
    }
    drawOvMetrics();   // K2b: phase cursor follows the slider (and playback)
  }

  // ---- K2a: round grid (horizontal chip strip, legacy overlap semantics) --
  function buildOvRoundStrip() {
    const holder = document.getElementById('ov-rounds');
    if (!holder) return;
    holder.innerHTML = '';
    for (const s of ovHalfRounds(state.ovHalf)) {
      const chip = document.createElement('button');
      chip.type = 'button';
      const winCls = s.winner_side === 'T' ? 'rs-t' : s.winner_side === 'CT' ? 'rs-ct' : '';
      chip.className = 'chip chip-sm rs-chip ' + winCls;
      chip.textContent = 'R' + s.round;
      chip.dataset.round = String(s.round);
      chip.title = 'R' + s.round + ' · 胜方 ' + (s.winner_side || '-');
      chip.addEventListener('click', () => {
        if (state.ovRounds.has(s.round)) state.ovRounds.delete(s.round);
        else state.ovRounds.add(s.round);
        syncOvRoundStrip();
      });
      holder.appendChild(chip);
    }
    syncOvRoundStrip();
  }
  function syncOvRoundStrip() {
    const holder = document.getElementById('ov-rounds');
    if (!holder) return;
    const total = ovHalfRounds(state.ovHalf).length;
    for (const chip of holder.querySelectorAll('.rs-chip')) {
      const round = Number(chip.dataset.round);
      // empty explicit selection = everything shown → all chips read "on"
      const shown = !state.ovRounds.size || state.ovRounds.has(round);
      chip.classList.toggle('off', !shown);
      // K2c: pattern-cluster border replaces the winner corner when enabled
      chip.classList.remove('clu-0', 'clu-1', 'clu-2');
      if (state.toggles.ovpatterns && total > 1) {
        chip.classList.add('clu-' + clusterOfRound(round));
      }
    }
    const count = document.getElementById('ov-rounds-count');
    if (count) {
      count.textContent = state.ovRounds.size
        ? '已选 ' + state.ovRounds.size + '/' + total
        : '全部 ' + total;
    }
    ovMetricsCache = null;  // selection changed → metrics recompute
    drawOvMetrics();
  }

  // ---- K2b: formation metrics across the shared phase ---------------------
  const OV_METRIC_PHASES = 96;
  let ovMetricsCache = null;  // { key, phases[], spread[], gap[] } in units
  function ovMetricsKey() {
    const sel = [...state.ovRounds].sort((a, b) => a - b).join(',');
    return state.ovHalf + '|' + (state.ovRounds.size ? sel : 'all');
  }
  function computeOvMetrics() {
    const segs = effectiveOvSegs();
    const N = OV_METRIC_PHASES;
    const spread = new Array(N).fill(0), gap = new Array(N).fill(0), cnt = new Array(N).fill(0);
    for (const seg of segs) {
      const span = ovSpanOf([seg]);
      for (let k = 0; k < N; k++) {
        const tick = seg.start_tick + (k / (N - 1)) * span;
        const alive = [];
        for (const p of players) {
          const st = playerStateAt(p, tick);
          if (st.alive) alive.push([st.x, st.y, SIDE_NAME[p.rows.side[st.i]] || '']);
        }
        if (alive.length < 2) continue;
        let sum = 0, pairs = 0;
        for (let a = 0; a < alive.length; a++) {
          for (let b = a + 1; b < alive.length; b++) {
            sum += Math.hypot(alive[a][0] - alive[b][0], alive[a][1] - alive[b][1]);
            pairs++;
          }
        }
        let tx = 0, ty = 0, tn = 0, cx = 0, cy = 0, cn = 0;
        for (const [x, y, s] of alive) {
          if (s === 'T') { tx += x; ty += y; tn++; }
          else if (s === 'CT') { cx += x; cy += y; cn++; }
        }
        spread[k] += sum / pairs;
        gap[k] += (tn && cn) ? Math.hypot(tx / tn - cx / cn, ty / tn - cy / cn) : 0;
        cnt[k]++;
      }
    }
    const phases = [], sp = [], gp = [];
    for (let k = 0; k < N; k++) {
      phases.push(k / (N - 1));
      sp.push(cnt[k] ? spread[k] / cnt[k] : 0);
      gp.push(cnt[k] ? gap[k] / cnt[k] : 0);
    }
    ovMetricsCache = { key: ovMetricsKey(), phases, spread: sp, gap: gp };
    return ovMetricsCache;
  }
  function ovMetrics() {
    const key = ovMetricsKey();
    if (!ovMetricsCache || ovMetricsCache.key !== key) computeOvMetrics();
    return ovMetricsCache;
  }
  function drawOvMetrics() {
    const wrap = document.getElementById('ov-metrics-wrap');
    const canvas = document.getElementById('ov-metrics');
    if (!wrap || !canvas || wrap.hidden || !D || !players.length) return;
    const m = ovMetrics();
    const dpr = DPR;
    const w = wrap.clientWidth, h = 110;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const padL = 44, padR = 10, padT = 8, padB = 16;
    const iw = w - padL - padR, ih = h - padT - padB;
    const maxV = Math.max(1, ...m.spread, ...m.gap) * 1.12;
    const xOf = (ph) => padL + ph * iw;
    const yOf = (v) => padT + ih - (v / maxV) * ih;
    // horizontal grid + unit labels
    ctx.strokeStyle = 'rgba(255,255,255,.07)';
    ctx.fillStyle = '#9aa0b8';
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (let g = 0; g <= 3; g++) {
      const v = (maxV * g) / 3;
      const y = yOf(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
      ctx.fillText(Math.round(v) + 'u', padL - 6, y);
    }
    // x time ticks (round clock is D.round_clock_seconds)
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (const frac of [0, 0.25, 0.5, 0.75, 1]) {
      const sec = Math.round(frac * (D.round_clock_seconds || 115));
      const lbl = Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
      ctx.fillText(lbl, xOf(frac), h - padB + 4);
    }
    const line = (vals, color, width) => {
      ctx.strokeStyle = color; ctx.lineWidth = width;
      ctx.beginPath();
      vals.forEach((v, i) => {
        const x = xOf(m.phases[i]), y = yOf(v);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    };
    line(m.spread, '#a78bfa', 1.8);
    line(m.gap, '#3ddc97', 1.6);
    // phase cursor (slider + playback linked)
    const px = xOf(state.ovPhase);
    ctx.strokeStyle = 'rgba(236,234,246,.85)'; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.moveTo(px, padT - 2); ctx.lineTo(px, h - padB); ctx.stroke();
    for (const [vals, color] of [[m.spread, '#c4b5fd'], [m.gap, '#7ee2bb']]) {
      const idx = Math.round(state.ovPhase * (vals.length - 1));
      const v = vals[Math.max(0, Math.min(idx, vals.length - 1))];
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(px, yOf(v), 3, 0, Math.PI * 2); ctx.fill();
    }
  }

  function drawMainLayer(tick) {
    const wrap = document.querySelector('.ob-map-wrap');
    const w = wrap.clientWidth, h = wrap.clientHeight;
    const ctx = setupCanvas($('main-layer'), w, h); // setupCanvas clears
    if (!D) return;
    if (state.overlap) { drawOverlapLayer(); return; }  // overlap sub-mode
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
        const P = window.ViewerPrefs;
        const arcR = (P ? P.get('fx.reload_arc_r') : 13) + 9; // dot ring + gap
        ctx.save();
        ctx.beginPath();
        ctx.arc(sx, sy, arcR * ms, 0, Math.PI * 2);
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
      ctx.fillStyle = st.ammo === 0 ? C.err : C.text;
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
  // Overlap layers are expensive (rounds × players × trails) — skip the
  // redraw entirely when nothing visible changed (paused + static camera).
  let lastOverlapSig = '';
  function ovRenderSig() {
    const sel = state.ovRounds.size
      ? [...state.ovRounds].sort((a, b) => a - b).join(',') : 'all';
    return [state.ovPhase.toFixed(4), state.focusSid || '', state.ovHalf, sel,
            !!state.toggles.trails, !!state.toggles.ovpatterns,
            (cam.cx ?? 0).toFixed(2), (cam.cy ?? 0).toFixed(2),
            (cam.zoom ?? 1).toFixed(4)].join('|');
  }
  function frame(ts) {
    requestAnimationFrame(frame);
    if (!D) return;
    try {
      const dt = Math.min((ts - state.lastTs) / 1000, 0.1);
      state.lastTs = ts;
      if (state.overlap) {
        // overlap sub-mode: 播放 sweeps the shared phase (20s full sweep)
        if (state.playing) {
          state.ovPhase += dt / 20;
          if (state.ovPhase >= 1) {
            state.ovPhase = 1;
            state.playing = false;
            $('btn-play').textContent = '播放';
            const ovPlay = document.getElementById('ov-play');
            if (ovPlay) { ovPlay.textContent = '▶ 播放'; ovPlay.classList.remove('on'); }
          }
          syncOvPhaseUI();
        }
      } else if (state.playing && ts >= state.holdUntil) {
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
      // K1b: camera moves BEFORE the draws — the basemap used to lag the
      // markers by a frame (updateCamFollow ran after everything, and the
      // map layer only repainted on wheel/pan/resize)
      const camMoved = updateCamFollow();
      if (camMoved) drawMapLayer();
      if (state.overlap) {
        const sig = ovRenderSig();
        if (sig !== lastOverlapSig) {
          lastOverlapSig = sig;
          drawMainLayer(state.tick);
          drawFxLayer(state.tick);
        }
      } else {
        drawMainLayer(state.tick);
        drawFxLayer(state.tick);
      }
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
    if (state.overlap) return;  // setOverlapMode owns the URL (mode=overlap)
    const seg = segOfTick(state.tick);
    if (!seg || seg.round === state.lastLinkedRound) return;
    state.lastLinkedRound = seg.round;
    const sel = $('sel-round');
    if (sel && sel.value !== String(seg.round)) sel.value = String(seg.round);
    const t = Math.max(0, Math.round((state.tick - seg.start_tick) / D.tick_rate));
    try {
      history.replaceState(null, '', `/match/${HASH}/viewer?round=${seg.round}&t=${t}`);
    } catch (e) { /* sandboxed contexts */ }
  }

  function updateHudTexts() {
    // overlap sub-mode: replay HUD is meaningless — show the mode banner
    // instead and keep bomb/buy strips hidden
    if (state.overlap) {
      $('round-label').textContent = state.ovHalf === 1 ? '上半场 · 重叠' : '下半场 · 重叠';
      $('round-timer').hidden = true;
      $('bomb-timer').hidden = true;
      const bs = document.getElementById('buy-strip');
      if (bs) bs.hidden = true;
      const kf = document.getElementById('kill-feed');
      if (kf) kf.hidden = true;
      return;
    }
    const kf2 = document.getElementById('kill-feed');
    if (kf2) kf2.hidden = false;
    const seg = segOfTick(state.tick);
    updateBuyStrip(seg);
    const rl = $('round-label'), timer = $('round-timer'), cur = $('cur-tick');
    cur.textContent = 'tick ' + Math.round(state.tick);
    if (!seg) { rl.textContent = '回合 -'; timer.textContent = '-'; setScores(null); setBombTimer(null); return; }
    rl.textContent = '回合 ' + seg.round;
    const remain = Math.max(D.round_clock_seconds - (state.tick - seg.start_tick) / D.tick_rate, 0);
    const mm = Math.floor(remain / 60), ss = Math.floor(remain % 60);
    timer.textContent = mm + ':' + String(ss).padStart(2, '0');
    // final 20s: red pulse (Phase G .ob-timer.low-time)
    timer.classList.toggle('low-time', remain <= 20);
    setScores(seg);
    setBombTimer(seg);
  }

  /** Bomb countdown beside the round clock once the bomb is down (40s fuse).
   * Phase J: plant AND its clearing end-event must both live inside the
   * current segment — tail-gap plants (a few ticks past round_end) used to
   * light the PREVIOUS round's timer, and cross-round end events from later
   * rounds never cleared the fuse. */
  function setBombTimer(seg) {
    const el = document.getElementById('bomb-timer');
    if (!el) return;
    let planted = null;
    if (seg) {
      for (const b of (D.events.bombs || [])) {
        if (b.tick > Math.min(state.tick, seg.end_tick)) break;  // sorted: nothing later can matter
        if (b.type === 'plant' && b.tick >= seg.start_tick && b.tick <= state.tick) planted = b;
        else if (planted && (b.type === 'defuse' || b.type === 'explode') &&
            b.tick > planted.tick && b.tick <= state.tick && b.tick <= seg.end_tick) {
          planted = null;  // cleared within the same round
        }
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

  // ---- P6: per-round buy strip from the (previously unread) economy layer ----
  let lastBuyKey = '';
  function updateBuyStrip(seg) {
    const el = document.getElementById('buy-strip');
    if (!el) return;
    if (!state.toggles.buys || !layersData || !layersData.economy || !seg) {
      el.hidden = true; return;
    }
    // show only during the first 20 game-seconds of the round
    const tInRound = state.tick - seg.start_tick;
    if (tInRound > 20 * D.tick_rate) { el.hidden = true; return; }
    const key = seg.round;
    if (key !== lastBuyKey) {
      lastBuyKey = key;
      renderBuyStrip(el, seg.round);
    }
    el.hidden = false;
  }
  function renderBuyStrip(el, round) {
    const econ = layersData && layersData.economy && layersData.economy.rounds;
    const table = layersData && layersData.weapon_table;
    const roundData = econ && econ[String(round)];
    if (!roundData || !table) { el.innerHTML = ''; return; }
    const sideOf = {};
    for (const p of players) sideOf[p.steamid] = p.sideFirst;
    for (const p of players) {
      if (p.sideFirst === 'T') sideOf[p.steamid] = 'T';
      else if (p.sideFirst === 'CT') sideOf[p.steamid] = 'CT';
    }
    const mkSide = (sideName) => {
      const items = [];
      for (const [sid, load] of Object.entries(roundData)) {
        if (sideOf[sid] !== sideName) continue;
        const icons = (load.weapons || []).slice(0, 4).map((idx) => {
          const name = table[idx];
          const url = window.WeaponMeta ? WeaponMeta.iconUrl(name) : '';
          return url ? `<img class="bs-ico" src="${url}" title="${name}" draggable="false">` : '';
        }).join('');
        items.push(`<span class="bs-item" title="${sid}">${icons}` +
          `<i class="bs-spend">$${load.spend}</i></span>`);
      }
      return `<div class="bs-side bs-${sideName.toLowerCase()}"><b>${sideName}</b>${items.join('')}</div>`;
    };
    el.innerHTML = mkSide('T') + mkSide('CT');
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
      // Phase J: focusing also glides the camera onto the player (2.5×) —
      // "聚焦" should move the view, not just recolor markers.
      // Bound on POINTERDOWN, not click: flushPanels' dead-last reordering
      // re-parents rows between mousedown and mouseup, and a repressed
      // target swallows the browser's click event (real-user bug report).
      li.title = '点击聚焦该选手（镜头跟随），再点取消';
      li.classList.add('ob-row--clickable');
      li.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
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
    // camera follow: glide onto the focused player at 2.5×; unfocus returns
    // to the fit view. Manual pan/zoom cancels the glide, not the focus.
    // Phase K1a: works in overlap mode too (target = phase-mean position,
    // computed per-frame inside updateCamFollow).
    if (state.focusSid) {
      camFollow.zoom = 2.5;
      camFollow.active = true;  // target computed per-frame in updateCamFollow
    } else {
      camFollow.active = false;
      ViewerCam.reset(cam);
      drawMapLayer();
    }
  }
  // per-frame camera glide state (lerp toward the focused player)
  const camFollow = { active: false, target: null, zoom: 1 };
  function worldToMapPx(wx, wy) {
    const b = D.map.bounds;
    return {
      x: ((wx - b.min_x) / (b.max_x - b.min_x)) * D.map.width,
      y: (1 - (wy - b.min_y) / (b.max_y - b.min_y)) * D.map.height,
    };
  }
  function updateCamFollow() {
    if (!camFollow.active || !D) return;
    const p = players.find((q) => q.steamid === state.focusSid);
    if (!p) { camFollow.active = false; return; }
    if (state.overlap) {
      // K1a: overlap target = the player's mean map-px across the half's
      // rounds at the shared phase — the centroid of their identity traces.
      // K2a: honors the round-grid filter (only selected rounds pull).
      const segs = effectiveOvSegs();
      const span = ovSpanOf(segs);
      let sx = 0, sy = 0, n = 0;
      for (const s of segs) {
        const st = playerStateAt(p, s.start_tick + state.ovPhase * span);
        if (!st.alive || !Number.isFinite(st.x)) continue;
        const mp = worldToMapPx(st.x, st.y);
        sx += mp.x; sy += mp.y; n++;
      }
      if (!n) return;
      camFollow.target = { x: sx / n, y: sy / n };
    } else {
      const st = playerStateAt(p, state.tick);
      camFollow.target = worldToMapPx(st.x, st.y);  // track while they move
    }
    ViewerCam.resolve(cam, D.map.width, D.map.height);
    const k = 0.12;  // glide factor per frame
    const pcx = cam.cx, pcy = cam.cy, pz = cam.zoom;
    cam.cx += (camFollow.target.x - cam.cx) * k;
    cam.cy += (camFollow.target.y - cam.cy) * k;
    cam.zoom += (camFollow.zoom - cam.zoom) * k;
    return Math.abs(cam.cx - pcx) + Math.abs(cam.cy - pcy) > 0.25
        || Math.abs(cam.zoom - pz) > 0.002;
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
      // deep link / legacy: ?mode=overlap or the standalone /overlap page
      // path both land in overlap sub-mode (overlap is a child of replay)
      if (q.get('mode') === 'overlap' || /\/overlap\/?$/.test(location.pathname)) {
        setOverlapMode(true);
        const qh = Number(q.get('half'));
        if (qh === 1 || qh === 2) state.ovHalf = qh;
        const qp = Number(q.get('phase'));
        if (qp > 0 && qp <= 1) {
          state.ovPhase = qp;
          const slider = document.getElementById('ov-phase');
          if (slider) slider.value = String(Math.round(qp * 1150));
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
    // K2 fix: one play state, two buttons (bottom bar + overlap phase bar)
    const syncPlayLabels = () => {
      btnPlay.textContent = state.playing ? '暂停' : '播放';
      const ovPlay = document.getElementById('ov-play');
      if (ovPlay) {
        ovPlay.textContent = state.playing ? '⏸ 暂停' : '▶ 播放';
        ovPlay.classList.toggle('on', state.playing);
      }
    };
    btnPlay.addEventListener('click', () => {
      state.playing = !state.playing;
      syncPlayLabels();
    });
    document.getElementById('ov-play')?.addEventListener('click', () => btnPlay.click());
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
      camFollow.active = false;  // manual zoom takes over
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
      // toolbar chips + overlap controls are interactive DOM inside the wrap —
      // they own their gestures. Missing .ov-controls here made dragging the
      // phase slider pan the map at the same time (user-reported jank).
      if (e.target.closest && e.target.closest('.ob-toolbar, .ov-controls')) return;
      pan.on = true; pan.id = e.pointerId; pan.moved = false;
      pan.x = e.clientX; pan.y = e.clientY;
    });
    wrap.addEventListener('pointermove', (e) => {
      if (!pan.on || e.pointerId !== pan.id) return;
      const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
      if (!pan.moved) {
        if (Math.hypot(dx, dy) < 4) return; // click vs drag threshold
        pan.moved = true;
        camFollow.active = false;  // manual pan takes over
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
      // dblclick on toolbar chips / overlap controls must not reset the camera
      if (e && e.target && e.target.closest
          && e.target.closest('.ob-toolbar, .ov-controls')) return;
      if (state.toggles.ctrl3d && window.ViewerControl) {
        ViewerControl.reset3d(D.map); // 3D has its own camera
        return;
      }
      ViewerCam.reset(cam); redrawMap();
    };
    wrap.addEventListener('dblclick', resetCam);
    document.getElementById('btn-cam-reset')?.addEventListener('click', resetCam);

    // ---- overlap sub-mode: phase slider + half toggles (Phase J) ----
    const ovPhase = document.getElementById('ov-phase');
    if (ovPhase) {
      ovPhase.addEventListener('input', (e) => {
        state.ovPhase = Number(e.target.value) / 1150;
        syncOvPhaseUI();
      });
    }
    for (const [id, half] of [['ov-half-1', 1], ['ov-half-2', 2]]) {
      const el = document.getElementById(id);
      if (el) el.addEventListener('click', () => {
        state.ovHalf = half;
        document.getElementById('ov-half-1')?.classList.toggle('on', half === 1);
        document.getElementById('ov-half-2')?.classList.toggle('on', half === 2);
        // K2a/K2b/K2c: round numbers differ per half — reset the selection
        // and rebuild every dependent view
        state.ovRounds.clear();
        buildOvRoundStrip();
        ovClusterCache = { key: null, assign: new Map() };
        ovMetricsCache = null;
        syncOvPhaseUI();
      });
    }
    // K2a quick filters (legacy semantics: empty selection = all rounds)
    const q = (id) => document.getElementById(id);
    q('ovr-all')?.addEventListener('click', () => { state.ovRounds.clear(); syncOvRoundStrip(); });
    q('ovr-clear')?.addEventListener('click', () => { state.ovRounds.clear(); syncOvRoundStrip(); });
    q('ovr-first4')?.addEventListener('click', () => {
      state.ovRounds = new Set(ovHalfRounds(state.ovHalf).slice(0, 4).map((s) => s.round));
      syncOvRoundStrip();
    });
    // K2b: drag on the metrics chart sets the shared phase
    const mCanvas = document.getElementById('ov-metrics');
    if (mCanvas) {
      const mWrap = document.getElementById('ov-metrics-wrap');
      const seekPhase = (e) => {
        const r = mCanvas.getBoundingClientRect();
        state.ovPhase = Math.max(0, Math.min((e.clientX - r.left) / r.width, 1));
        syncOvPhaseUI();
      };
      const drag = { on: false };
      mCanvas.addEventListener('mousedown', (e) => { drag.on = true; seekPhase(e); });
      window.addEventListener('mousemove', (e) => { if (drag.on) seekPhase(e); });
      window.addEventListener('mouseup', () => { drag.on = false; });
      void mWrap;
    }

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
    window.addEventListener('resize', () => { drawMapLayer(); drawOvMetrics(); });
    // prefs panel tweaks marker/trail visuals live — force overlap redraw
    document.addEventListener('prefs-changed', () => { lastOverlapSig = ''; });
  }

  // ---- overlay toolbar: chip toggles bound to state.toggles + localStorage ----
  let toolbarChips = {}; // key -> chip element
  let modeSwitchBtns = null; // K2e: { replay, overlap } segmented control
  function buildToolbar() {
    const bar = document.getElementById('ob-toolbar');
    if (!bar) return;
    const labels = [
      ['trails', '轨迹'], ['kills', '击杀线'], ['nades', '道具'],
      ['shots', '枪线'], ['blinds', '闪光'], ['bombs', '炸弹'],
      ['control', '控图'], ['ctrl3d', '3D'], ['buys', '买装'],
      ['ovpatterns', '模式着色'],
    ];
    // keep the static ⚙ prefs button (lives in the same bar) and the B3
    // ⏺ recorder chip — buildToolbar rebuilds bar.innerHTML on mode switches
    const prefsBtn = document.getElementById('prefs-btn');
    const recBtn = document.getElementById('btn-rec');
    bar.innerHTML = '';
    if (prefsBtn) bar.appendChild(prefsBtn);
    if (recBtn) bar.appendChild(recBtn);
    toolbarChips = {};
    // K2e: prominent segmented mode switcher FIRST — replay vs overlap is a
    // mode, not an overlay toggle, so it gets its own control shape.
    const modeSwitch = document.createElement('div');
    modeSwitch.className = 'ob-mode-switch';
    modeSwitch.innerHTML =
      '<button type="button" data-mode="replay">实时回放</button>' +
      '<button type="button" data-mode="overlap">回合重叠</button>';
    modeSwitchBtns = {
      replay: modeSwitch.querySelector('[data-mode="replay"]'),
      overlap: modeSwitch.querySelector('[data-mode="overlap"]'),
    };
    modeSwitchBtns.replay.addEventListener('click', () => setOverlapMode(false));
    modeSwitchBtns.overlap.addEventListener('click', () => setOverlapMode(true));
    bar.appendChild(modeSwitch);
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
        // K2c: pattern coloring recolors round chips + trail strokes in place
        if (key === 'ovpatterns') syncOvRoundStrip();
        syncToolbarChips();
        try { localStorage.setItem('csa-viewer-toggles', JSON.stringify(state.toggles)); } catch (e) {}
      });
      toolbarChips[key] = chip;
      bar.appendChild(chip);
    }
    // initial chip states must reflect mode/toggles set before this ran
    // (deep-link overlap entry calls setOverlapMode pre-buildToolbar)
    syncToolbarChips();
  }

  function syncToolbarChips() {
    // K2e: the segmented mode switch mirrors state.overlap; 模式着色 only
    // means something in overlap mode (disabled otherwise)
    if (modeSwitchBtns) {
      modeSwitchBtns.replay.classList.toggle('on', !state.overlap);
      modeSwitchBtns.overlap.classList.toggle('on', !!state.overlap);
    }
    for (const [key, chip] of Object.entries(toolbarChips)) {
      chip.classList.toggle('on', !!state.toggles[key]);
      if (key === 'ovpatterns') chip.disabled = !state.overlap;
      if (key === 'ctrl3d') chip.disabled = !state.toggles.control;
    }
  }

  load();
})();
