// 复盘教练线 M3: focus buttons on career suggestion items + progress-card
// clear. Steamid comes from the /player/{sid} path; actions reload so the
// SSR progress card re-renders from the store.
(function () {
  'use strict';

  function sid() {
    var m = location.pathname.match(/\/player\/([^/]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  document.querySelectorAll('.focus-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      btn.disabled = true;
      fetch('/api/focus', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ steamid: sid(), dim: btn.dataset.dim }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error(String(r.status));
          location.reload();
        })
        .catch(function () { btn.disabled = false; });
    });
  });

  var clear = document.querySelector('.focus-clear');
  if (clear) {
    clear.addEventListener('click', function () {
      clear.disabled = true;
      fetch('/api/focus?steamid=' + encodeURIComponent(sid()),
        { method: 'DELETE' })
        .then(function (r) {
          if (!r.ok) throw new Error(String(r.status));
          location.reload();
        })
        .catch(function () { clear.disabled = false; });
    });
  }
})();
