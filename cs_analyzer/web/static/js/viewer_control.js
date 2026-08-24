// Map control (控图) layer (Phase F M6 + 真3D upgrade): football pitch-control
// style territory tinting + perspective 3D orbit view.
//
// 2D mode: computed client-side per frame — the replay shows one tick at a
// time, so a frame costs 10 players × ≤49 grid cells of kernel evals.
// Temporal smoothing is an EMA over game seconds, rebuilt on seeks.
//
// 3D mode: a real perspective camera (orbit via drag, dolly via wheel).
// The radar PNG is perspective-mapped onto the ground plane by grid
// subdivision (affine triangle mapping); control cells become extruded
// translucent columns, painter-sorted by camera depth.
//
// Exposed as window.ViewerControl.
(function () {
  'use strict';

  // ---- tuning constants ----
  const CELL_WORLD = 128;      // grid cell size, world units (~40×40 on mirage)
  const SIGMA = 170;           // player influence kernel width (world units)
  const CUTOFF = 480;          // kernel truncation radius (±4 cells)
  const TAU_S = 2.0;           // EMA time constant (game seconds)
  const SEEK_REBUILD_S = 4.0;  // trailing window re-integrated after a seek
  const SAT_PLAYERS = 2.5;     // |control| that reaches full opacity
  const MAX_ALPHA = 0.34;
  const MIN_CELL = 0.15;       // cells below this stay transparent
  // 3D
  const FOV = 50 * Math.PI / 180;
  const GROUND_DIVS = 16;      // ground texture subdivision (per axis)
  const MAX_3D_CELLS = 900;    // painter cap (perf guard)

  const T_COLOR = [255, 176, 46];   // --t amber
  const CT_COLOR = [61, 155, 255];  // --ct blue

  let grid = null; // { cols, rows, x0, y0, map_name } in world coords

  function ensureGrid(map) {
    if (grid && grid.map_name === map.map_name) return grid;
    const b = map.bounds;
    const cols = Math.max(1, Math.ceil((b.max_x - b.min_x) / CELL_WORLD));
    const rows = Math.max(1, Math.ceil((b.max_y - b.min_y) / CELL_WORLD));
    grid = { cols, rows, x0: b.min_x, y0: b.min_y, map_name: map.map_name };
    return grid;
  }

  /**
   * Instantaneous control field: Σ_T w − Σ_CT w per cell.
   * players: [{x, y, sideCode}] (alive only; 0=T 1=CT).
   * Returns Float32Array(cols*rows).
   */
  function computeInstant(map, players) {
    const g = ensureGrid(map);
    const field = new Float32Array(g.cols * g.rows);
    const reach = Math.ceil(CUTOFF / CELL_WORLD);
    const inv2s2 = 1 / (2 * SIGMA * SIGMA);
    for (const pl of players) {
      if (!Number.isFinite(pl.x) || !Number.isFinite(pl.y)) continue;
      const cx = Math.floor((pl.x - g.x0) / CELL_WORLD);
      const cy = Math.floor((pl.y - g.y0) / CELL_WORLD);
      const sign = pl.sideCode === 0 ? 1 : pl.sideCode === 1 ? -1 : 0;
      if (!sign) continue;
      for (let dy = -reach; dy <= reach; dy++) {
        const ry = cy + dy;
        if (ry < 0 || ry >= g.rows) continue;
        const wy = g.y0 + (ry + 0.5) * CELL_WORLD;
        const ddy = wy - pl.y;
        for (let dx = -reach; dx <= reach; dx++) {
          const rx = cx + dx;
          if (rx < 0 || rx >= g.cols) continue;
          const wx = g.x0 + (rx + 0.5) * CELL_WORLD;
          const d2 = (wx - pl.x) * (wx - pl.x) + ddy * ddy;
          if (d2 > CUTOFF * CUTOFF) continue;
          field[ry * g.cols + rx] += sign * Math.exp(-d2 * inv2s2);
        }
      }
    }
    return field;
  }

  /** EMA the accumulated field toward the instant field (dt in game seconds). */
  function smoothTo(acc, instant, dtS) {
    if (!acc) return Float32Array.from(instant);
    const a = 1 - Math.exp(-Math.max(dtS, 0) / TAU_S);
    for (let i = 0; i < acc.length; i++) {
      acc[i] += (instant[i] - acc[i]) * a;
    }
    return acc;
  }

  let acc = null;
  let lastTick = null;
  function reset() { acc = null; lastTick = null; }

  function update(tick, TICK, playersAt, map) {
    ensureGrid(map); // resolve the grid before any computeInstant call
    if (acc === null || lastTick === null || Math.abs(tick - lastTick) > TICK) {
      // seek or cold start: integrate the trailing window coarsely
      const steps = 8;
      const span = SEEK_REBUILD_S * TICK;
      acc = null;
      for (let k = steps; k >= 1; k--) {
        const t = tick - (span * k) / steps;
        acc = smoothTo(acc, computeInstant(grid, playersAt(t)), span / steps / TICK);
      }
      acc = smoothTo(acc, computeInstant(grid, playersAt(tick)), 0.05);
    } else {
      const dtS = (tick - lastTick) / TICK;
      acc = smoothTo(acc, computeInstant(grid, playersAt(tick)), dtS);
    }
    lastTick = tick;
    return acc;
  }

  /**
   * 2D fast path: paint cells into an offscreen cols×rows ImageData (one
   * pixel per cell), then one drawImage with smoothing = soft territory wash.
   */
  function renderFlat(ctx, map, field, toScreen) {
    const g = ensureGrid(map);
    const c = flatCanvas(g);
    const cctx = flatCtx(g);
    const img = cctx.createImageData(g.cols, g.rows);
    const data = img.data;
    for (let i = 0; i < field.length; i++) {
      const v = field[i];
      const o = i * 4;
      if (Math.abs(v) < MIN_CELL) { data[o + 3] = 0; continue; }
      const alpha = Math.min(Math.abs(v) / SAT_PLAYERS, 1) * MAX_ALPHA * 255;
      const col = v > 0 ? T_COLOR : CT_COLOR;
      data[o] = col[0]; data[o + 1] = col[1]; data[o + 2] = col[2];
      data[o + 3] = alpha;
    }
    cctx.putImageData(img, 0, 0);
    const [sx0, sy0] = toScreen(g.x0, g.y0);
    const [sx1, sy1] = toScreen(g.x0 + g.cols * CELL_WORLD, g.y0 + g.rows * CELL_WORLD);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(c, sx0, sy0, sx1 - sx0, sy1 - sy0);
  }

  const _flatCanvases = new Map();
  function flatCanvas(g) {
    let c = _flatCanvases.get(g.map_name);
    if (!c) {
      c = document.createElement('canvas');
      c.width = g.cols; c.height = g.rows;
      _flatCanvases.set(g.map_name, c);
    }
    return c;
  }
  function flatCtx(g) { return flatCanvas(g).getContext('2d'); }

  // ================= perspective 3D =================
  // Orbit camera around the map center. theta=0 → camera due south looking
  // north (screen-up = world +Y, matching the 2D view); phi = elevation.
  const cam3d = { theta: 0, phi: 55 * Math.PI / 180, dist: 0, ready: false };

  function reset3d(map) {
    const b = map.bounds;
    const diag = Math.hypot(b.max_x - b.min_x, b.max_y - b.min_y);
    cam3d.theta = 0;
    cam3d.phi = 55 * Math.PI / 180;
    cam3d.dist = diag * 0.85;
    cam3d.ready = true;
  }
  function orbit(dTheta, dPhi) {
    cam3d.theta += dTheta;
    cam3d.phi = Math.max(12 * Math.PI / 180, Math.min(87 * Math.PI / 180, cam3d.phi + dPhi));
  }
  function dolly(factor) {
    cam3d.dist = Math.max(cam3d.dist * factor, 200);
  }

  function makeCamera(map, w, h) {
    const b = map.bounds;
    const target = [(b.min_x + b.max_x) / 2, (b.min_y + b.max_y) / 2, 0];
    const { theta, phi, dist } = cam3d;
    const eye = [
      target[0] + dist * Math.sin(theta) * Math.cos(phi),
      target[1] - dist * Math.cos(theta) * Math.cos(phi),
      target[2] + dist * Math.sin(phi),
    ];
    // forward = normalize(target - eye); right = normalize(f × up); up = r × f
    let fx = target[0] - eye[0], fy = target[1] - eye[1], fz = target[2] - eye[2];
    const fl = Math.hypot(fx, fy, fz); fx /= fl; fy /= fl; fz /= fl;
    let rx = fy * 1 - fz * 0, ry = fz * 0 - fx * 1, rz = 0; // f × (0,0,1)
    const rl = Math.hypot(rx, ry, rz) || 1; rx /= rl; ry /= rl; rz /= rl;
    const ux = ry * fz - rz * fy, uy = rz * fx - rx * fz, uz = rx * fy - ry * fx;
    const focal = (h / 2) / Math.tan(FOV / 2);
    return {
      eye, target,
      project(px, py, pz) {
        const dx = px - eye[0], dy = py - eye[1], dz = pz - eye[2];
        const cz = dx * fx + dy * fy + dz * fz;
        if (!(cz > 1)) return null; // behind camera OR NaN (undefined z etc.)
        const cx = dx * rx + dy * ry + dz * rz;
        const cy = dx * ux + dy * uy + dz * uz;
        return [w / 2 + cx * focal / cz, h / 2 - cy * focal / cz, cz];
      },
    };
  }

  /** Affine-map one image triangle onto one screen triangle and draw it. */
  function drawTexTriangle(ctx, img, src, dst) {
    // src/dst: [[x,y] ×3]; solve affine src→dst, clip to dst, drawImage
    const [p0, p1, p2] = src, [q0, q1, q2] = dst;
    const den = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1]);
    if (Math.abs(den) < 1e-9) return;
    const a = ((q1[0] - q0[0]) * (p2[1] - p0[1]) - (q2[0] - q0[0]) * (p1[1] - p0[1])) / den;
    const b = ((q2[0] - q0[0]) * (p1[0] - p0[0]) - (q1[0] - q0[0]) * (p2[0] - p0[0])) / den;
    const c = ((q1[1] - q0[1]) * (p2[1] - p0[1]) - (q2[1] - q0[1]) * (p1[1] - p0[1])) / den;
    const d = ((q2[1] - q0[1]) * (p1[0] - p0[0]) - (q1[1] - q0[1]) * (p2[0] - p0[0])) / den;
    const e = q0[0] - a * p0[0] - b * p0[1];
    const f = q0[1] - c * p0[0] - d * p0[1];
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(q0[0], q0[1]); ctx.lineTo(q1[0], q1[1]); ctx.lineTo(q2[0], q2[1]);
    ctx.closePath();
    ctx.clip();
    ctx.transform(a, c, b, d, e, f);
    ctx.drawImage(img, 0, 0);
    ctx.restore();
  }

  /**
   * Perspective 3D: radar PNG perspective-mapped on the ground + control
   * columns + player dots. painter-sorted by camera depth.
   * players3d: [{x, y, color, focus}] (screen-projected at ground level).
   */
  function render3D(ctx, map, field, w, h, mapImg, players3d) {
    const g = ensureGrid(map);
    if (!cam3d.ready) reset3d(map);
    const cam = makeCamera(map, w, h);
    const b = map.bounds;

    // ---- ground: radar texture by grid subdivision (2 triangles per cell) --
    if (mapImg && mapImg.naturalWidth) {
      const iw = mapImg.naturalWidth, ih = mapImg.naturalHeight;
      const nx = GROUND_DIVS, ny = GROUND_DIVS;
      // image pixel (px,py) ↔ world: x = min_x + px/iw*span_x,
      // y = max_y - py/ih*span_y (image top = north)
      const spanX = b.max_x - b.min_x, spanY = b.max_y - b.min_y;
      // NOTE: z must be 0 (ground plane) — a 2-element array would make
      // project() read p[2] as undefined → NaN poisoning every triangle
      const worldOf = (px, py) => [
        b.min_x + (px / iw) * spanX,
        b.max_y - (py / ih) * spanY,
        0,
      ];
      for (let j = 0; j < ny; j++) {
        for (let i = 0; i < nx; i++) {
          const px0 = (i / nx) * iw, px1 = ((i + 1) / nx) * iw;
          const py0 = (j / ny) * ih, py1 = ((j + 1) / ny) * ih;
          const w00 = project(cam, worldOf(px0, py0));
          const w10 = project(cam, worldOf(px1, py0));
          const w01 = project(cam, worldOf(px0, py1));
          const w11 = project(cam, worldOf(px1, py1));
          if (!w00 || !w10 || !w01 || !w11) continue;
          drawTexTriangle(ctx, mapImg,
            [[px0, py0], [px1, py0], [px0, py1]], [w00, w10, w01]);
          drawTexTriangle(ctx, mapImg,
            [[px1, py0], [px1, py1], [px0, py1]], [w10, w11, w01]);
        }
      }
    } else {
      // no bitmap: flat dark ground quad
      const c00 = project(cam, [b.min_x, b.max_y, 0]);
      const c10 = project(cam, [b.max_x, b.max_y, 0]);
      const c11 = project(cam, [b.max_x, b.min_y, 0]);
      const c01 = project(cam, [b.min_x, b.min_y, 0]);
      if (c00 && c10 && c11 && c01) {
        ctx.beginPath();
        ctx.moveTo(c00[0], c00[1]); ctx.lineTo(c10[0], c10[1]);
        ctx.lineTo(c11[0], c11[1]); ctx.lineTo(c01[0], c01[1]);
        ctx.closePath();
        ctx.fillStyle = '#0d1420'; ctx.fill();
      }
    }

    // ---- control columns ----
    const cells = [];
    for (let r = 0; r < g.rows; r++) {
      for (let cI = 0; cI < g.cols; cI++) {
        const v = field[r * g.cols + cI];
        if (Math.abs(v) < MIN_CELL) continue;
        const x0 = g.x0 + cI * CELL_WORLD, y0 = g.y0 + r * CELL_WORLD;
        const x1 = x0 + CELL_WORLD, y1 = y0 + CELL_WORLD;
        // project base + lifted top (height by intensity)
        const hh = (Math.abs(v) / SAT_PLAYERS) * (cam3d.dist * 0.06);
        const b00 = project(cam, [x0, y1, 0]), b10 = project(cam, [x1, y1, 0]);
        const b11 = project(cam, [x1, y0, 0]), b01 = project(cam, [x0, y0, 0]);
        if (!b00 || !b10 || !b11 || !b01) continue;
        const t00 = project(cam, [x0, y1, hh]), t10 = project(cam, [x1, y1, hh]);
        const t11 = project(cam, [x1, y0, hh]), t01 = project(cam, [x0, y0, hh]);
        if (!t00 || !t10 || !t11 || !t01) continue;
        // depth = camera-space z of the column center (bigger = farther)
        const cxw = (x0 + x1) / 2 - cam.eye[0];
        const cyw = (y0 + y1) / 2 - cam.eye[1];
        const czw = -cam.eye[2];
        const depth = cxw * cxw + cyw * cyw + czw * czw; // ~distance² (monotone)
        cells.push({ v, b00, b10, b11, b01, t00, t10, t11, t01,
                     x0, y0, x1, y1, depth });
      }
    }
    if (cells.length > MAX_3D_CELLS) {
      cells.sort((p, q) => q.depth - p.depth); // far first
      cells.length = MAX_3D_CELLS;
    } else {
      cells.sort((p, q) => q.depth - p.depth);
    }
    for (const c of cells) {
      const col = c.v > 0 ? T_COLOR : CT_COLOR;
      const alpha = Math.min(Math.abs(c.v) / SAT_PLAYERS, 1) * 0.5 + 0.12;
      // visible side faces: camera outside the cell edge
      const sides = [];
      if (cam.eye[1] > c.y1) sides.push([c.b00, c.b10, c.t10, c.t00]); // north face
      if (cam.eye[1] < c.y0) sides.push([c.b01, c.b11, c.t11, c.t01]); // south face
      if (cam.eye[0] > c.x1) sides.push([c.b10, c.b11, c.t11, c.t10]); // east face
      if (cam.eye[0] < c.x0) sides.push([c.b01, c.b00, c.t00, c.t01]); // west face
      for (const q of sides) {
        ctx.beginPath();
        ctx.moveTo(q[0][0], q[0][1]); ctx.lineTo(q[1][0], q[1][1]);
        ctx.lineTo(q[2][0], q[2][1]); ctx.lineTo(q[3][0], q[3][1]);
        ctx.closePath();
        ctx.fillStyle = rgba(col, alpha * 0.45);
        ctx.fill();
      }
      // top face
      ctx.beginPath();
      ctx.moveTo(c.t00[0], c.t00[1]); ctx.lineTo(c.t10[0], c.t10[1]);
      ctx.lineTo(c.t11[0], c.t11[1]); ctx.lineTo(c.t01[0], c.t01[1]);
      ctx.closePath();
      ctx.fillStyle = rgba(col, alpha);
      ctx.fill();
      ctx.strokeStyle = 'rgba(0,0,0,.28)'; ctx.lineWidth = 0.6; ctx.stroke();
    }

    // ---- player dots (projected at a small hover height) ----
    if (players3d) {
      const hover = cam3d.dist * 0.012;
      for (const p of players3d) {
        const s = project(cam, [p.x, p.y, hover]);
        if (!s) continue;
        ctx.beginPath(); ctx.arc(s[0], s[1], 5, 0, Math.PI * 2);
        ctx.fillStyle = p.color; ctx.fill();
        ctx.lineWidth = 1.2; ctx.strokeStyle = '#000'; ctx.stroke();
        if (p.focus) {
          ctx.beginPath(); ctx.arc(s[0], s[1], 9.5, 0, Math.PI * 2);
          ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.lineWidth = 1.6; ctx.stroke();
        }
      }
    }
  }

  function project(cam, p) { return cam.project(p[0], p[1], p[2]); }

  function rgba(col, a) {
    return `rgba(${col[0]},${col[1]},${col[2]},${a.toFixed(3)})`;
  }

  window.ViewerControl = {
    computeInstant: (map, players) => computeInstant(map, players),
    smoothTo,
    update,
    renderFlat,
    render3D,
    reset,
    reset3d,
    orbit,
    dolly,
    is3dReady: () => cam3d.ready,
    CELL_WORLD,
    MIN_CELL,
  };
})();
