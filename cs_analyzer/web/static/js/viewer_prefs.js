// ViewerPrefs (Phase H+): user-tunable visual parameters for the replay /
// overlap canvases. Every previously hard-coded visual constant is exposed as
// a slider in the ⚙ panel; values persist to localStorage AND the server
// (output/web/ui_prefs.json) so the developer can read the file and bake the
// tuned values back in as the new defaults.
//
// Usage: ViewerPrefs.get('marker.fit') anywhere in render code; sliders call
// set() which applies instantly (canvas redraws every frame anyway).
(function () {
  'use strict';

  const LS_KEY = 'csa.prefs.v1';
  const API = '/api/ui-prefs';

  // ---- defaults = the shipped values (bake user-tuned ones back here) ----
  const DEFAULTS = {
    'marker.fit': 0.54,     // marker scale at fit view (dot r = 11·ms px)
    'marker.exp': 0.6,      // zoom growth exponent (0 = constant size)
    'marker.cap': 2,        // max marker scale at full zoom
    'label.scale': 12,      // number label font base (px at ms=1)
    'label.min': 9,         // number label font floor (px)
    'fx.tracer_world': 900, // tracer length (world units)
    'fx.tracer_dur': 0.18,  // tracer fade window (s)
    'fx.muzzle_dur': 0.06,  // muzzle flash window (s)
    'fx.muzzle_r': 9,       // muzzle flash radius (px)
    'fx.reload_arc_r': 13,  // reload arc radius (px, zoom-scaled)
    'trail.window_s': 6,    // trail lookback window, normal (s)
    'trail.focus_window_s': 10, // trail lookback, focused player (s)
    'trail.width': 2,       // trail line width (px at ms=1)
    'overlap.ghost_alpha': 0.14, // non-focused player alpha in single mode
    'overlap.break_dist': 300,   // trail break threshold (world units)
    'control.sigma': 170,   // influence kernel width (world units)
    'control.tau': 2.0,     // EMA time constant (game seconds)
    'control.alpha': 0.34,  // territory tint max alpha
    'control.h3d': 0.06,    // 3D column height (× camera distance)
    'control.v2': 1,        // U3: v2 = density dampening + engagement decay
    'control.fight_r': 400, // fight zone radius (world units)
    'control.fight_decay': 0.45, // control multiplier inside a fight zone
    'control.fight_ttl': 6.0,    // fight zone lifetime (game seconds)
    'control.density_pow': 0.72, // team-mate density dampening exponent
  };

  // ---- panel schema: drives the drawer UI ----
  const SCHEMA = [
    { group: '标记大小', hint: 'fit=全局视角基础大小 · 指数=随缩放增长速度 · 封顶=最大倍数', items: [
      { key: 'marker.fit', label: '基础大小', min: 0.2, max: 1.5, step: 0.01 },
      { key: 'marker.exp', label: '增长指数', min: 0, max: 1.2, step: 0.01 },
      { key: 'marker.cap', label: '放大封顶', min: 0.5, max: 4, step: 0.05 },
    ]},
    { group: '编号字体', items: [
      { key: 'label.scale', label: '字号系数', min: 6, max: 24, step: 0.5 },
      { key: 'label.min', label: '最小字号', min: 6, max: 16, step: 0.5 },
    ]},
    { group: '射击特效', hint: '曳光长度/寿命 · 枪口焰大小/寿命 · 换弹弧半径', items: [
      { key: 'fx.tracer_world', label: '曳光长度', min: 0, max: 2500, step: 50 },
      { key: 'fx.tracer_dur', label: '曳光寿命 s', min: 0.05, max: 0.6, step: 0.01 },
      { key: 'fx.muzzle_dur', label: '枪口焰寿命 s', min: 0.02, max: 0.3, step: 0.01 },
      { key: 'fx.muzzle_r', label: '枪口焰半径', min: 4, max: 24, step: 0.5 },
      { key: 'fx.reload_arc_r', label: '换弹弧半径', min: 6, max: 30, step: 0.5 },
    ]},
    { group: '轨迹', items: [
      { key: 'trail.window_s', label: '回看窗口 s', min: 1, max: 20, step: 0.5 },
      { key: 'trail.focus_window_s', label: '聚焦回看 s', min: 2, max: 30, step: 0.5 },
      { key: 'trail.width', label: '线宽', min: 0.5, max: 6, step: 0.1 },
    ]},
    { group: '重叠页', items: [
      { key: 'overlap.ghost_alpha', label: '幽灵透明度', min: 0, max: 0.6, step: 0.01 },
      { key: 'overlap.break_dist', label: '轨迹断裂阈值', min: 50, max: 800, step: 10 },
    ]},
    { group: '控图', hint: '改动后自动重建累计场（回溯 4s）', items: [
      { key: 'control.sigma', label: '影响半径', min: 60, max: 400, step: 5 },
      { key: 'control.tau', label: '平滑 τ s', min: 0.2, max: 8, step: 0.1 },
      { key: 'control.alpha', label: '染色强度', min: 0.05, max: 1, step: 0.01 },
      { key: 'control.h3d', label: '3D 柱高系数', min: 0.01, max: 0.2, step: 0.005 },
    ]},
    { group: '控图 v2（U3）', hint: 'v2=密度去重+交战衰减：抱团不再线性叠加，交战区控制存疑', items: [
      { key: 'control.v2', label: 'v2 开关', min: 0, max: 1, step: 1 },
      { key: 'control.fight_r', label: '交战半径', min: 150, max: 800, step: 10 },
      { key: 'control.fight_decay', label: '交战衰减', min: 0, max: 0.9, step: 0.05 },
      { key: 'control.fight_ttl', label: '交战存续 s', min: 1, max: 15, step: 0.5 },
      { key: 'control.density_pow', label: '密度去重', min: 0.4, max: 1, step: 0.02 },
    ]},
  ];

  let values = { ...DEFAULTS };

  function get(key) {
    const v = values[key];
    return v === undefined ? DEFAULTS[key] : v;
  }

  function set(key, val, silent) {
    values[key] = val;
    localStorage.setItem(LS_KEY, JSON.stringify(values));
    if (!silent) {
      if (key.startsWith('control.') && window.ViewerControl) {
        try { window.ViewerControl.reset(); } catch (e) { /* not on this page */ }
      }
      document.dispatchEvent(new CustomEvent('prefs-changed', { detail: { key } }));
    }
    syncPanel();
  }

  function setMany(obj) {
    for (const [k, v] of Object.entries(obj)) {
      if (k in DEFAULTS) values[k] = v;
    }
    localStorage.setItem(LS_KEY, JSON.stringify(values));
    if (window.ViewerControl) { try { window.ViewerControl.reset(); } catch (e) { /* */ } }
    syncPanel();
  }

  function resetAll() {
    values = { ...DEFAULTS };
    localStorage.setItem(LS_KEY, JSON.stringify(values));
    if (window.ViewerControl) { try { window.ViewerControl.reset(); } catch (e) { /* */ } }
    syncPanel();
  }

  async function load() {
    // precedence: localStorage (this machine's latest tweaks) > server file
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) Object.assign(values, JSON.parse(raw));
    } catch (e) { /* corrupt ls — keep defaults */ }
    try {
      const r = await fetch(API);
      if (r.ok) {
        const remote = await r.json();
        for (const [k, v] of Object.entries(remote)) {
          if (k in DEFAULTS && !(k in values)) values[k] = v; // ls absent → server
        }
        // if localStorage had nothing at all, adopt the server wholesale
        if (!localStorage.getItem(LS_KEY)) values = { ...DEFAULTS, ...remote };
      }
    } catch (e) { /* offline / no file — defaults fine */ }
    syncPanel();
  }

  async function save() {
    localStorage.setItem(LS_KEY, JSON.stringify(values));
    try {
      const r = await fetch(API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(values),
      });
      return r.ok;
    } catch (e) {
      return false;
    }
  }

  // ---- drawer panel (auto-injected when the page has #prefs-btn) ----
  function buildPanel() {
    const btn = document.getElementById('prefs-btn');
    if (!btn || document.getElementById('prefs-drawer')) return;

    const drawer = document.createElement('aside');
    drawer.id = 'prefs-drawer';
    drawer.className = 'prefs-drawer';
    drawer.hidden = true;
    let html = '<div class="prefs-head"><span>视觉调节</span>' +
      '<button class="prefs-close" id="prefs-close" type="button">✕</button></div>' +
      '<div class="prefs-body">';
    for (const g of SCHEMA) {
      html += `<div class="prefs-group"><div class="prefs-group-title">${g.group}` +
        (g.hint ? `<span class="prefs-hint">${g.hint}</span>` : '') + '</div>';
      for (const it of g.items) {
        html += `<label class="prefs-row"><span class="prefs-label">${it.label}</span>` +
          `<input type="range" data-pref="${it.key}" min="${it.min}" max="${it.max}" step="${it.step}">` +
          `<output class="prefs-val" data-pref-out="${it.key}"></output></label>`;
      }
      html += '</div>';
    }
    html += '</div><div class="prefs-foot">' +
      '<button class="btn btn-ghost btn-sm" id="prefs-reset" type="button">恢复默认</button>' +
      '<button class="btn btn-primary btn-sm" id="prefs-save" type="button">保存</button>' +
      '<span class="prefs-saved" id="prefs-saved"></span></div>';
    drawer.innerHTML = html;
    document.body.appendChild(drawer);

    btn.addEventListener('click', () => { drawer.hidden = !drawer.hidden; });
    drawer.querySelector('#prefs-close').addEventListener('click', () => { drawer.hidden = true; });
    drawer.querySelector('#prefs-reset').addEventListener('click', () => { resetAll(); });
    drawer.querySelector('#prefs-save').addEventListener('click', async () => {
      const ok = await save();
      const tag = drawer.querySelector('#prefs-saved');
      tag.textContent = ok ? '已保存 ✓' : '保存失败';
      setTimeout(() => { tag.textContent = ''; }, 2000);
    });
    drawer.addEventListener('input', (e) => {
      const el = e.target.closest('input[data-pref]');
      if (el) set(el.dataset.pref, Number(el.value));
    });
    syncPanel();
  }

  function syncPanel() {
    const drawer = document.getElementById('prefs-drawer');
    if (!drawer) return;
    drawer.querySelectorAll('input[data-pref]').forEach((el) => {
      el.value = get(el.dataset.pref);
    });
    drawer.querySelectorAll('output[data-pref-out]').forEach((el) => {
      const v = get(el.dataset.prefOut);
      el.textContent = Number.isInteger(v) ? v : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
    });
  }

  document.addEventListener('DOMContentLoaded', () => { load().then(buildPanel); });

  window.ViewerPrefs = { get, set, setMany, resetAll, save, load, DEFAULTS };
})();
