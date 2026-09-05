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

  window.CSACommon = { esc: esc, fetchJson: fetchJson };
})();
