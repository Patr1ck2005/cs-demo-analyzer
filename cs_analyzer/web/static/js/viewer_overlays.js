// Advanced 2D analysis overlays (Phase E M4): video-era effect templates
// ported onto the canvas replay per docs/video_pipeline_archive.md §3.
//
// Drawn on #fx-layer (below #main-layer trails): utility zones/arcs, shot
// sparks, blind rings, bomb markers, kill connections. All windows are
// game-time seconds; zone radii are WORLD units converted through the camera.
(function () {
  'use strict';

  // ---- palette (archive spec §3.3) ----
  const COLORS = {
    smokeFill: 'rgba(200,205,215,',       // canvas-family smoke (Phase C)
    flash: 'rgba(255,255,255,',
    fire: 'rgba(255,110,40,',
    projectile: { smoke: '#9E9E9E', flash: '#FFFFFF', he: '#FF8800', fire: '#FF6600' },
    kill: '#ffd166',
    shot: '#FFD700',
    blind: 'rgba(255,255,255,',
    bombPlant: '#ff4d5e', bombDefuse: '#3ddc97', bombBoom: '#ff8800',
  };
  const C_ERR = '#ff4d5e';

  // ---- geometry constants (archive spec §3.1/§3.2/§3.4) ----
  const SMOKE_RADII = [1.0, 0.85, 0.7, 0.95, 0.75];
  const SMOKE_ALPHAS = [0.30, 0.26, 0.22, 0.24, 0.18];
  const N_SMOKE_LAYERS = 5;
  const N_FIRE_FLAMES = 8;
  const SMOKE_GROW_S = 1.0;
  const SMOKE_FADE_TAIL_S = 2.5;
  const SMOKE_SCALE = 1.2;  // Phase J: drawn cloud ×1.2 (user-tuned)
  const KILL_DUR_S = 1.2;
  const SHOT_DUR_S = 0.12;
  // combat feedback (Phase F M5): muzzle flash / tracer windows & lengths —
  // live values come from ViewerPrefs (⚙ panel); consts are the fallbacks
  const MUZZLE_DUR_S = 0.06;         // 60ms flash at the muzzle
  const TRACER_DUR_S = 0.18;         // tracer fade window
  const TRACER_WORLD = 900;          // tracer length in world units
  const RELOAD_ARC_R = 13;           // reload arc radius (screen px, zoom-scaled)
  const pref = (k, fb) => (window.ViewerPrefs ? window.ViewerPrefs.get(k) : fb);
  const LANDING_PULSE_S = 0.35;
  const DEFAULT_ZONE_S = { smoke: 18, flash: 2, he: 1, fire: 7 };

  // deterministic RNG so clouds/flames render identically every run
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // per-event offsets/phases computed once and cached by event index
  const _offsetCache = new Map();
  function smokeOffsets(i) {
    if (!_offsetCache.has(i)) {
      const rnd = mulberry32(7 + i * 1013);
      const pts = [];
      for (let l = 0; l < N_SMOKE_LAYERS; l++) {
        pts.push(l === 0 ? [0, 0] : [(rnd() - 0.5) * 0.9, (rnd() - 0.5) * 0.9]);
      }
      _offsetCache.set(i, pts);
    }
    return _offsetCache.get(i);
  }

  function firePhases(i) {
    if (!_offsetCache.has('f' + i)) {
      const rnd = mulberry32(11 + i * 977);
      const pts = [];
      for (let f = 0; f < N_FIRE_FLAMES; f++) {
        pts.push([(rnd() - 0.5) * 1.3, (rnd() - 0.5) * 1.3, rnd() * Math.PI * 2]);
      }
      _offsetCache.set('f' + i, pts);
    }
    return _offsetCache.get('f' + i);
  }

  /** First index with arr[i] >= lo (binary search over a sorted tick array). */
  function lowerBound(ticks, lo) {
    let a = 0, b = ticks.length;
    while (a < b) { const m = (a + b) >> 1; (ticks[m] < lo ? a = m + 1 : b = m); }
    return a;
  }

  /** Cached sorted tick array for windowed scans. */
  function tickIndex(arr, key) {
    if (!arr.__ticks) arr.__ticks = arr.map((e) => e[key]);
    return arr.__ticks;
  }

  /**
   * Draw all event-driven overlays for env.tick.
   * env: {ctx, tick, TICK, events, layers, toggles, toScreen, worldDist,
   *       posAt} — built by viewer_canvas.js each frame.
   */
  function draw(env) {
    const { ctx } = env;
    if (env.toggles.nades !== false) drawUtilities(env);
    if (env.toggles.kills !== false) drawKills(env);
    if (env.toggles.shots && env.layers && env.layers.shots) drawShots(env);
    if (env.toggles.blinds !== false) drawBlinds(env);
    if (env.toggles.bombs !== false) drawBombs(env);
    return ctx;
  }

  // ---- grenades: flight arc + landing pulse + living zone ----
  function drawUtilities(env) {
    const { ctx, tick, TICK, toScreen, events } = env;
    const utils = events.utilities || [];
    const maxLookback = 25 * TICK; // longest-lived zone kind is smoke (~18-22s)
    const ticks = tickIndex(utils, 'tick');
    for (let i = lowerBound(ticks, tick - maxLookback); i < utils.length; i++) {
      const u = utils[i];
      if (u.tick > tick + (u.tt != null ? Math.max(u.tick - u.tt, 0) : 0)) break;
      // flight phase: reconstructed throw -> landing (end-exclusive window)
      if (u.tt != null && u.tt <= tick && tick < u.tick) {
        const f = (tick - u.tt) / Math.max(u.tick - u.tt, 1);
        const [tx, ty] = toScreen(u.tx, u.ty);
        const [lx, ly] = toScreen(u.x, u.y);
        const col = COLORS.projectile[u.kind] || '#fff';
        ctx.save();
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = col;
        ctx.globalAlpha = 0.8;
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(lx, ly); ctx.stroke();
        ctx.setLineDash([]);
        const px = tx + (lx - tx) * f, py = ty + (ly - ty) * f;
        ctx.beginPath(); ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fillStyle = col; ctx.fill();
        ctx.lineWidth = 1; ctx.strokeStyle = '#000'; ctx.stroke();
        ctx.restore();
        continue;
      }
      const age = tick - u.tick;
      if (age < 0) continue;
      const durS = u.dur_s > 0 ? u.dur_s : DEFAULT_ZONE_S[u.kind] || 7;
      const durT = durS * TICK;
      if (age > durT) continue;
      // landing ring pulse (brief, overlaps the zone's first instants)
      if (age < LANDING_PULSE_S * TICK) {
        const p = age / (LANDING_PULSE_S * TICK);
        const [sx, sy] = toScreen(u.x, u.y);
        ctx.beginPath();
        ctx.arc(sx, sy, env.worldDist(30) * (0.5 + p), 0, Math.PI * 2);
        ctx.strokeStyle = hexA(COLORS.projectile[u.kind] || '#fff', 0.8 * (1 - p));
        ctx.lineWidth = 2; ctx.stroke();
      }
      drawZone(env, i, u, age / durT, durT);
    }
  }

  function drawZone(env, idx, u, prog, durT) {
    const { ctx, tick, TICK, toScreen } = env;
    const [sx, sy] = toScreen(u.x, u.y);
    const ageT = prog * durT;
    if (u.kind === 'smoke') {
      // multi-circle irregular volume; grow 1s, fade the last 2.5s
      // Phase J: base radius 120 -> 144 (×1.2, user-tuned — the drawn cloud
      // read smaller than the in-game smoke)
      const grow = Math.min(ageT / (SMOKE_GROW_S * TICK), 1);
      const R = env.worldDist(120 * SMOKE_SCALE) * grow;
      const fadeTail = SMOKE_FADE_TAIL_S * TICK;
      const remain = durT - prog * durT;
      const fade = remain < fadeTail ? remain / fadeTail : 1;
      const offs = smokeOffsets(idx % 64);
      for (let l = 0; l < N_SMOKE_LAYERS; l++) {
        const rr = R * SMOKE_RADII[l];
        const ox = sx + offs[l][0] * R, oy = sy + offs[l][1] * R;
        ctx.beginPath(); ctx.arc(ox, oy, rr, 0, Math.PI * 2);
        ctx.fillStyle = COLORS.smokeFill + (SMOKE_ALPHAS[l] * 1.15 * fade).toFixed(3) + ')';
        ctx.fill();
      }
    } else if (u.kind === 'flash') {
      const R = env.worldDist(130) * (0.7 + 0.3 * prog);
      ctx.beginPath(); ctx.arc(sx, sy, R, 0, Math.PI * 2);
      ctx.fillStyle = COLORS.flash + (0.55 * (1 - prog)).toFixed(3) + ')'; ctx.fill();
    } else if (u.kind === 'he') {
      const R = env.worldDist(85) * (0.5 + 0.5 * prog);
      ctx.beginPath(); ctx.arc(sx, sy, R, 0, Math.PI * 2);
      ctx.strokeStyle = hexA('#FF8800', 0.75 * (1 - prog)); ctx.lineWidth = 2.5; ctx.stroke();
    } else { // fire: base zone + flickering flame points
      const ramp = Math.min(ageT / (0.5 * TICK), 1);
      const R = env.worldDist(50) * (0.8 + 0.2 * ramp);
      const fade = prog > 0.8 ? (1 - prog) / 0.2 : 1;
      ctx.beginPath(); ctx.arc(sx, sy, R, 0, Math.PI * 2);
      ctx.fillStyle = COLORS.fire + (0.45 * 0.45 * fade).toFixed(3) + ')'; ctx.fill();
      const phases = firePhases(idx % 64);
      for (let f = 0; f < N_FIRE_FLAMES; f++) {
        const [oxf, oyf, ph] = phases[f];
        const flick = 0.55 + 0.45 * Math.abs(Math.sin(tick / 5 + ph));
        const fr = env.worldDist(6) * (0.7 + flick);
        ctx.beginPath();
        ctx.arc(sx + oxf * R, sy + oyf * R, fr, 0, Math.PI * 2);
        ctx.fillStyle = COLORS.fire + (0.65 * flick * fade).toFixed(3) + ')'; ctx.fill();
      }
    }
  }

  // ---- kills: gold connection line + star/skull + headshot accent ----
  function drawKills(env) {
    const { ctx, tick, TICK, events } = env;
    const durT = KILL_DUR_S * TICK;
    const kills = events.kills || [];
    const ticks = tickIndex(kills, 'tick');
    for (let i = lowerBound(ticks, tick - durT); i < kills.length; i++) {
      const k = kills[i];
      const age = tick - k.tick;
      if (age > durT) break;
      if (age < 0) continue; // future kills (array is ascending; keep scanning)
      if (!Number.isFinite(k.ax) || !Number.isFinite(k.vx)) continue;
      const a = 0.9 * (1 - age / durT);
      const [ax, ay] = env.toScreen(k.ax, k.ay);
      const [vx, vy] = env.toScreen(k.vx, k.vy);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(vx, vy);
      ctx.strokeStyle = COLORS.kill; ctx.globalAlpha = a; ctx.lineWidth = 1.4; ctx.stroke();
      star(ctx, ax, ay, 5);
      if (k.hs) {
        ctx.beginPath(); ctx.arc(ax, ay, 8.5, 0, Math.PI * 2);
        ctx.strokeStyle = COLORS.kill; ctx.globalAlpha = a * 0.7; ctx.lineWidth = 1; ctx.stroke();
        ctx.globalAlpha = a;
      }
      skull(ctx, vx, vy, 3.2, C_ERR);
      ctx.globalAlpha = 1;
    }
  }

  // ---- shots: muzzle flash + gold tracer along shooter yaw (lazy layer) ----
  function drawShots(env) {
    const { ctx, tick, TICK } = env;
    const durT = SHOT_DUR_S * TICK;
    const shots = env.layers.shots || [];
    const ticks = tickIndex(shots, 'tick');
    const tracerDur = pref('fx.tracer_dur', TRACER_DUR_S);
    const muzzleDur = pref('fx.muzzle_dur', MUZZLE_DUR_S);
    const maxT = Math.max(durT, tracerDur * TICK, muzzleDur * TICK);
    const wm = window.WeaponMeta;
    for (let i = lowerBound(ticks, tick - maxT); i < shots.length; i++) {
      const s = shots[i];
      const age = tick - s.tick;
      if (age > maxT) break;
      if (age < 0) continue; // future shots
      const [sx, sy] = env.toScreen(s.x, s.y);
      const wName = (env.layers.weapon_table || [])[s.wi] || '';
      const isGun = !wm || wm.isGun(wName); // grenades/knife/c4 get no tracer
      // tracer: gold gradient line along the shot's yaw (needs layer v2 "ya")
      if (isGun && s.ya != null && age <= tracerDur * TICK) {
        const rad = (s.ya * Math.PI) / 180;
        // Source yaw: 0 = +X CCW; screen y grows south -> (cos, -sin)
        const dx = Math.cos(rad), dy = -Math.sin(rad);
        const len = env.worldDist(pref('fx.tracer_world', TRACER_WORLD));
        const a = 0.55 * (1 - age / (tracerDur * TICK));
        const grad = ctx.createLinearGradient(sx, sy, sx + dx * len, sy + dy * len);
        grad.addColorStop(0, hexA(COLORS.shot, a));
        grad.addColorStop(1, hexA(COLORS.shot, 0));
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(sx + dx * len, sy + dy * len);
        ctx.strokeStyle = grad; ctx.lineWidth = 1.6; ctx.stroke();
      }
      // muzzle flash: additive radial burst at the origin (guns only)
      if (isGun && age <= muzzleDur * TICK) {
        const p = 1 - age / (muzzleDur * TICK);
        const r = pref('fx.muzzle_r', 9) * (0.5 + 0.5 * p);
        const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, r);
        g.addColorStop(0, `rgba(255,235,150,${0.9 * p})`);
        g.addColorStop(0.5, `rgba(255,210,80,${0.55 * p})`);
        g.addColorStop(1, 'rgba(255,210,80,0)');
        ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.fillStyle = g; ctx.fill();
      }
      // legacy spark for non-gun "shots" (grenade detonations etc.)
      if (!isGun) {
        ctx.beginPath(); ctx.arc(sx, sy, 3, 0, Math.PI * 2);
        ctx.fillStyle = hexA(COLORS.shot, 0.85 * (1 - age / durT)); ctx.fill();
      }
    }
  }

  // ---- blinds: white ring at the victim, intensity by blinded duration ----
  function drawBlinds(env) {
    const { ctx, tick, TICK } = env;
    const blinds = env.events.blinds || [];
    for (const b of blinds) {
      if (b.tick > tick || tick - b.tick > 1.5 * TICK) continue;
      if (b.dur < 0.5) continue; // sub-half-second flickers are noise
      const pos = env.posAt(b.vic, Math.min(b.tick, tick));
      if (!pos) continue;
      const [sx, sy] = env.toScreen(pos[0], pos[1]);
      const p = (tick - b.tick) / (1.5 * TICK);
      const inten = Math.min(b.dur, 3) / 3;
      ctx.beginPath(); ctx.arc(sx, sy, 10 + 14 * p, 0, Math.PI * 2);
      ctx.strokeStyle = COLORS.blind + (0.75 * inten * (1 - p)).toFixed(3) + ')';
      ctx.lineWidth = 2.5; ctx.stroke();
    }
  }

  // ---- bombs: pulsing plant diamond while live; defuse/explode flashes ----
  // Phase J: the clearing end-event must belong to the SAME segment as the
  // plant — the old "any later end" match paired a plant with a defuse from
  // rounds later, keeping the diamond alive across half the map.
  function drawBombs(env) {
    const { ctx, tick, TICK, events } = env;
    const bombs = events.bombs || [];
    const seg = env.seg;  // current segment (viewer_canvas supplies it)
    const inSeg = (t) => (!seg || (t >= seg.start_tick && t <= seg.end_tick));
    for (const b of bombs) {
      if (b.type === 'plant') {
        if (b.tick > tick) continue;
        if (!inSeg(b.tick)) continue;          // not this round -> invisible
        if (!(Number.isFinite(b.x) && Number.isFinite(b.y))) continue;
        const end = bombs.find((o) => o !== b && o.tick >= b.tick &&
          (o.type === 'defuse' || o.type === 'explode') && inSeg(o.tick));
        if (end && tick >= end.tick) continue;
        const [sx, sy] = env.toScreen(b.x, b.y);
        const pulse = 0.75 + 0.25 * Math.sin(tick / 8);
        diamond(ctx, sx, sy, 7 * pulse, COLORS.bombPlant);
      } else if (b.type === 'defuse' || b.type === 'explode') {
        const age = tick - b.tick;
        if (age < 0 || age > 1.2 * TICK) continue;
        if (!(Number.isFinite(b.x) && Number.isFinite(b.y))) continue;
        const a = 1 - age / (1.2 * TICK);
        const [sx, sy] = env.toScreen(b.x, b.y);
        const color = b.type === 'defuse' ? COLORS.bombDefuse : COLORS.bombBoom;
        ctx.beginPath(); ctx.arc(sx, sy, 10 + 8 * (1 - a), 0, Math.PI * 2);
        ctx.strokeStyle = hexA(color, a); ctx.lineWidth = 2.5; ctx.stroke();
      }
    }
  }

  // ---- shared glyph painters (reused by the main player layer) ----
  function star(ctx, x, y, r) {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const rr = i % 2 ? r * 0.45 : r;
      const a = (Math.PI / 5) * i - Math.PI / 2;
      const px = x + rr * Math.cos(a), py = y + rr * Math.sin(a);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle = COLORS.kill; ctx.fill();
  }

  function skull(ctx, x, y, r, color) {
    ctx.beginPath(); ctx.arc(x, y, r == null ? 3.2 : r, 0, Math.PI * 2);
    ctx.fillStyle = color || C_ERR; ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.fillRect(x - r * 0.62, y - r * 0.38, r * 0.38, r * 0.38);
    ctx.fillRect(x + r * 0.24, y - r * 0.38, r * 0.38, r * 0.38);
  }

  function diamond(ctx, x, y, r, fill) {
    ctx.beginPath();
    ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y);
    ctx.closePath();
    ctx.fillStyle = fill; ctx.fill();
    ctx.lineWidth = 1; ctx.strokeStyle = '#000'; ctx.stroke();
  }

  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  window.ViewerOverlays = {
    draw, star, skull, diamond, hexA,
    COLORS, DEFAULT_ZONE_S, KILL_DUR_S, RELOAD_ARC_R,
  };
})();
