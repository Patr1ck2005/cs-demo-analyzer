// Phase L0: dashboard skeleton fill-in while the startup prewarm runs.
// The server rendered "…" placeholders; once /api/warmup.json reports ready,
// fill the player count and swap the highlight skeleton for the real feed.
(function () {
  'use strict';

  var waited = 0;
  var POLL_MS = 1500;
  var MAX_WAIT_MS = 180000; // give up silently after 3 min (memos stay lazy)

  function stop() { waited = -1; }

  function fill() {
    fetch('/api/warmup.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (s) {
      // ready = prewarm finished; phase=error = prewarm failed but the
      // hydration endpoint still lazily computes (slow path) and fills.
      if (s && (s.ready || s.phase === 'error')) {
        stop();
        fetch('/api/warmup/dashboard.json', { cache: 'no-store' })
          .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
          .then(function (d) {
            sessionStorage.removeItem('csa.warmupFails');
            apply(d);
          })
          .catch(function () {
            // F6: a persistently failing hydration endpoint (e.g. the
            // aggregate scan errors out) must not loop reload forever —
            // retry once, then stop and surface the failure.
            var fails = (parseInt(sessionStorage.getItem('csa.warmupFails') || '0', 10) || 0) + 1;
            sessionStorage.setItem('csa.warmupFails', String(fails));
            if (fails < 2) { location.reload(); return; }
            var sk = document.getElementById('dash-highlights-skeleton');
            if (sk) sk.innerHTML =
              '<div class="empty-title">数据加载失败</div>' +
              '<div>预热/聚合持续出错 — 请到 /system 查看服务端日志后手动刷新。</div>';
          });
      }
    }).catch(stop);
  }

  function apply(d) {
    var pc = document.querySelector('[data-warmup="player_count"]');
    if (pc && typeof d.player_count === 'number') pc.textContent = String(d.player_count);
    var sk = document.getElementById('dash-highlights-skeleton');
    if (sk && d.highlights_html) {
      var wrap = document.createElement('div');
      wrap.innerHTML = d.highlights_html;
      var grid = wrap.firstElementChild;
      if (grid) sk.replaceWith(grid);
      else sk.remove();
    } else if (sk) {
      sk.remove();
    }
  }

  var timer = setInterval(function () {
    if (waited < 0) { clearInterval(timer); return; }
    waited += POLL_MS;
    if (waited > MAX_WAIT_MS) { clearInterval(timer); return; }
    fill();
  }, POLL_MS);
  fill();
})();
