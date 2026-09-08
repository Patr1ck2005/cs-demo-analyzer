// Shared micro-helpers (Phase S): HTML escaping + JSON fetch, previously
// re-implemented inline in 5+ templates (drift-prone; several spots forgot
// the escaping half). Loaded from base.html before page scripts.
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /** fetch JSON with non-2xx -> rejected promise (so callers' catch runs). */
  function fetchJson(url, opts) {
    return fetch(url, opts).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url);
      return r.json();
    });
  }

  // ---- Phase R1: statistical rigor rendering -------------------------------
  // conf entry: {lo, hi, n, gated} (from web funlab_data / future boards).
  // Renders as a compact grey badge: "0.61 [0.55–0.67] · 87"; gated rows add
  // the class csa-conf-gated (grey-out styling lives in style.css). Rows keep
  // showing — gating never hides (V2 EV-table precedent).
  function fmtConf(conf, opts) {
    opts = opts || {};
    if (!conf || typeof conf !== 'object' || conf.lo == null) return '';
    var pct = opts.pct !== false;
    var f = function (x) { return pct ? (x * 100).toFixed(0) + '%' : (+x).toFixed(2); };
    var s = ' <span class="csa-conf' + (conf.gated ? ' csa-conf-gated' : '') + '" title="样本 n=' +
      conf.n + (conf.gated ? '（不足 ' + (opts.gate || 3) + '，仅示意）' : '，95% 置信区间') + '">' +
      '[' + f(conf.lo) + '–' + f(conf.hi) + '] · n=' + conf.n + '</span>';
    return s;
  }

  window.CSACommon = { esc: esc, fetchJson: fetchJson, fmtConf: fmtConf };
})();
