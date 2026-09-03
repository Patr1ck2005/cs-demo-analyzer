// Phase L1: favorites / tags / notes — shared client helpers.
// Star buttons mount on match cards (_match_card.html) and the player career
// header; the /favorites page renders lists from the same API.
(function () {
  'use strict';

  function post(body) {
    return fetch('/api/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) { return r.json(); });
  }

  function get() {
    return fetch('/api/favorites', { cache: 'no-store' }).then(function (r) { return r.json(); });
  }

  // ---- star button (delegated: works for cards rendered later) ----
  function ensureStyles() {
    if (document.getElementById('fav-star-style')) return;
    var st = document.createElement('style');
    st.id = 'fav-star-style';
    st.textContent =
      '.fav-star{background:none;border:none;cursor:pointer;font-size:18px;line-height:1;' +
      'padding:2px 4px;color:var(--muted);transition:transform .12s,color .12s;border-radius:6px}' +
      '.fav-star:hover{transform:scale(1.25)}' +
      '.fav-star.on{color:#fbbf24}' +
      '.fav-note-dot{display:inline-block;width:7px;height:7px;border-radius:50%;' +
      'background:var(--accent);margin-left:6px;vertical-align:middle}';
    document.head.appendChild(st);
  }

  function starHtml(scope, id, entry) {
    var on = !!(entry && entry.starred);
    var note = entry && entry.note;
    return '<button class="fav-star' + (on ? ' on' : '') + '" data-fav-scope="' + scope +
      '" data-fav-id="' + id + '" title="' + (on ? '取消收藏' : '收藏') + '">' +
      (on ? '★' : '☆') + (note ? '<span class="fav-note-dot"></span>' : '') + '</button>';
  }

  // cache the doc for delegated renders
  var _doc = null;
  function doc() {
    if (_doc === null) { _doc = {}; get().then(function (d) { _doc = d; mountAll(); }); }
    return _doc;
  }

  function entryFor(scope, id) {
    var d = doc();
    return d && d[scope === 'match' ? 'matches' : 'players'] &&
      d[scope === 'match' ? 'matches' : 'players'][id];
  }

  function mountAll() {
    ensureStyles();
    document.querySelectorAll('[data-match-card]:not([data-fav-mounted])').forEach(function (el) {
      el.setAttribute('data-fav-mounted', '1');
      var slot = el.querySelector('.mc-actions');
      if (!slot) return;
      var id = el.getAttribute('data-match-card');
      slot.insertAdjacentHTML('afterbegin', starHtml('match', id, entryFor('match', id)));
    });
    document.querySelectorAll('[data-player-star]:not([data-fav-mounted])').forEach(function (el) {
      el.setAttribute('data-fav-mounted', '1');
      var id = el.getAttribute('data-player-star');
      el.innerHTML = starHtml('player', id, entryFor('player', id));
    });
  }

  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('.fav-star');
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    var scope = btn.getAttribute('data-fav-scope');
    var id = btn.getAttribute('data-fav-id');
    var nowOn = !btn.classList.contains('on');
    btn.classList.toggle('on', nowOn);
    btn.innerHTML = (nowOn ? '★' : '☆');
    // denormalize display meta from the DOM so /favorites shows names
    var meta = null;
    if (scope === 'match') {
      var host = btn.closest('[data-match-card]');
      if (host) {
        var fn = host.querySelector('.mc-name');
        var mn = host.querySelector('.mc-map-name');
        meta = { filename: fn ? fn.textContent.trim() : '', map_name: mn ? mn.textContent.trim() : '' };
      }
    } else if (scope === 'player') {
      var ph = btn.closest('[data-player-star]');
      var nm = ph ? ph.getAttribute('data-player-name') : '';
      if (nm) meta = { name: nm };
    }
    var body = { scope: scope, id: id, patch: { starred: nowOn } };
    if (meta) body.meta = meta;
    post(body).then(function (res) {
      if (!res || !res.ok) { btn.classList.toggle('on', !nowOn); btn.innerHTML = nowOn ? '☆' : '★'; }
    });
  });

  // ---- /favorites page ----
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function renderFavoritesPage() {
    ensureStyles();
    var tagRow = document.getElementById('fav-tag-row');
    var mWrap = document.getElementById('fav-matches');
    var pWrap = document.getElementById('fav-players');
    var nWrap = document.getElementById('fav-notes');
    if (!mWrap || !pWrap) return;
    var activeTag = '';
    get().then(function (doc) {
      var matches = Object.entries(doc.matches || {}).filter(function (kv) { return kv[1].starred; });
      var players = Object.entries(doc.players || {}).filter(function (kv) { return kv[1].starred; });
      // tag chips
      var tags = new Set();
      matches.concat(players).forEach(function (kv) { (kv[1].tags || []).forEach(function (t) { tags.add(t); }); });
      if (tagRow) {
        tagRow.innerHTML = Array.from(tags).map(function (t) {
          return '<button class="chip chip-sm" data-tag="' + esc(t) + '">' + esc(t) + '</button>';
        }).join('') || '<span class="sub">暂无标签 — 在对局/选手页点星后可加标签</span>';
        tagRow.querySelectorAll('[data-tag]').forEach(function (b) {
          b.addEventListener('click', function () {
            activeTag = activeTag === b.getAttribute('data-tag') ? '' : b.getAttribute('data-tag');
            tagRow.querySelectorAll('[data-tag]').forEach(function (x) {
              x.classList.toggle('on', x.getAttribute('data-tag') === activeTag);
            });
            draw();
          });
        });
      }
      function tagOk(e) { return !activeTag || (e.tags || []).indexOf(activeTag) >= 0; }

      function draw() {
        // matches
        var ms = matches.filter(function (kv) { return tagOk(kv[1]); });
        mWrap.innerHTML = ms.length ? ms.map(function (kv) {
          var id = kv[0], e = kv[1], m = e.meta || {};
          return '<a class="match-card" href="/match/' + esc(id) + '">' +
            '<div class="mc-map mc-map--none"><span class="mc-map-name">' + esc(m.map_name || '对局') + '</span></div>' +
            '<div class="mc-body"><div class="mc-name">' + esc(m.filename || id.slice(0, 12)) + '</div>' +
            '<div class="mc-meta"><span class="badge t0">' + esc(m.map_name || '') + '</span>' +
            '<span class="mc-actions">查看分析 →</span></div></div></a>';
        }).join('') : '<div class="empty-state" style="grid-column:1/-1"><div class="empty-title">还没有收藏的对局</div><div>在对局卡片右上角点 ☆ 收藏。</div></div>';
        // players
        var ps = players.filter(function (kv) { return tagOk(kv[1]); });
        pWrap.innerHTML = ps.length ? ps.map(function (kv) {
          var id = kv[0], e = kv[1], m = e.meta || {};
          return '<a class="card" style="text-decoration:none" href="/player/' + esc(id) + '">' +
            '<div class="mc-name">' + esc(m.name || id.slice(-4)) + '</div>' +
            '<div class="sub">' + esc((e.tags || []).join(' · ')) + '</div></a>';
        }).join('') : '<div class="empty-state" style="grid-column:1/-1"><div class="empty-title">还没有收藏的选手</div><div>在选手生涯页点 ☆ 收藏。</div></div>';
        // notes
        var notes = matches.concat(players).filter(function (kv) { return (kv[1].note || '').trim() && tagOk(kv[1]); });
        nWrap.innerHTML = notes.length ? notes.map(function (kv) {
          var e = kv[1], m = e.meta || {};
          var href = kv[0] in (doc.matches || {}) ? '/match/' + esc(kv[0]) : '/player/' + esc(kv[0]);
          var label = m.filename || m.name || kv[0].slice(0, 12);
          return '<div style="margin-bottom:10px"><a href="' + href + '"><b>' + esc(label) + '</b></a>' +
            '<div class="sub" style="white-space:pre-wrap">' + esc(e.note) + '</div></div>';
        }).join('') : '<span class="sub">暂无备注 — 备注编辑在对局详情页（即将加入）。</span>';
      }
      draw();
    });
  }

  window.CSAFavorites = { post: post, get: get, mountAll: mountAll, starHtml: starHtml, entryFor: entryFor, renderFavoritesPage: renderFavoritesPage };
  window.renderFavoritesPage = renderFavoritesPage; // favorites.html inline caller
  document.addEventListener('DOMContentLoaded', mountAll);
})();
