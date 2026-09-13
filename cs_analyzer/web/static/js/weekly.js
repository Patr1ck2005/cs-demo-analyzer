// M4 复盘教练线: mark-read button — the current library becomes the next
// report's BEFORE cohort. Reload re-renders the SSR page from the state.
(function () {
  'use strict';
  var btn = document.getElementById('weekly-baseline');
  if (!btn) return;
  btn.addEventListener('click', function () {
    btn.disabled = true;
    fetch('/api/weekly/baseline', { method: 'POST' })
      .then(function (r) {
        if (!r.ok) throw new Error(String(r.status));
        location.reload();
      })
      .catch(function () { btn.disabled = false; });
  });
})();
