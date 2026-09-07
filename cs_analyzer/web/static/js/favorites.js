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
      'background:var(--accent);margin-left:6px;vertical-align:middle}' +
      '.fav-edit{background:none;border:1px solid var(--line,#2a2d47);cursor:pointer;font-size:13px;' +
      'line-height:1;padding:4px 7px;margin-left:4px;color:var(--muted);border-radius:6px}' +
      '.fav-edit:hover{color:var(--accent);border-color:var(--accent)}' +
      '.fav-editor{position:fixed;inset:0;z-index:200;background:rgba(6,7,15,.6);' +
      'display:flex;align-items:center;justify-content:center}' +
      '.fav-editor-box{background:#151728;border:1px solid #2a2d47;border-radius:12px;' +
      'padding:18px;width:min(480px,92vw);box-shadow:0 18px 50px rgba(0,0,0,.5)}' +
      '.fav-editor-title{font-weight:600;margin-bottom:12px;display:flex;justify-content:space-between}' +
      '.fav-editor-x{background:none;border:none;color:var(--muted);cursor:pointer;font-size:15px}' +
      '.fav-editor label{display:block;font-size:12px;color:var(--muted);margin:10px 0 4px}' +
      '.fav-editor textarea,.fav-editor input{width:100%;box-sizing:border-box;background:#0e101d;' +
      'color:var(--text,#eceaf6);border:1px solid #2a2d47;border-radius:8px;padding:8px;font:inherit}' +
      '.fav-editor textarea{resize:vertical}' +
      '.fav-editor-actions{margin-top:14px;display:flex;align-items:center;gap:10px}' +
      '.fav-editor-save{background:var(--accent,#a78bfa);color:#17142a;border:none;border-radius:8px;' +
      'padding:7px 18px;font-weight:600;cursor:pointer}';
    document.head.appendChild(st);
  }

  function starHtml(scope, id, entry) {
    var on = !!(entry && entry.starred);
    var note = entry && entry.note;
    return '<button class="fav-star' + (on ? ' on' : '') + '" data-fav-scope="' + scope +
      '" data-fav-id="' + id + '" title="' + (on ? '取消收藏' : '收藏') + '">' +
      (on ? '★' : '☆') + (note ? '<span class="fav-note-dot"></span>' : '') + '</button>';
  }

  function editBtnHtml(scope, id) {
    return '<button class="fav-edit" data-fav-scope="' + scope + '" data-fav-id="' + id +
      '" title="编辑备注/标签" type="button">✎</button>';
  }

  // cache the doc for delegated renders
  var _doc = null;
  function doc() {
    if (_doc === null) {
      _doc = {};
      // F1: when the doc arrives AFTER first paint, mounted nodes were
      // rendered from the empty placeholder — refresh their star states
      // instead of leaving them stuck on ☆.
      get().then(function (d) { _doc = d; mountAll(); applyStars(); });
    }
    return _doc;
  }

  function entryFor(scope, id) {
    var d = doc();
    return d && d[scope === 'match' ? 'matches' : 'players'] &&
      d[scope === 'match' ? 'matches' : 'players'][id];
  }

  function setStar(btn, on, note) {
    btn.classList.toggle('on', on);
    btn.setAttribute('title', on ? '取消收藏' : '收藏');
    btn.innerHTML = (on ? '★' : '☆') + (note ? '<span class="fav-note-dot"></span>' : '');
  }

  // F1: re-apply persisted star state to every ALREADY-mounted node
  // (idempotent — updates class/innerHTML, never inserts a second star).
  function applyStars() {
    document.querySelectorAll('[data-fav-mounted]').forEach(function (el) {
      var scope = el.hasAttribute('data-player-star') ? 'player' : 'match';
      var id = el.getAttribute(scope === 'player' ? 'data-player-star' : 'data-match-card');
      if (!id) return;
      var e = entryFor(scope, id) || {};
      if (el.hasAttribute('data-fav-standalone')) {
        el.innerHTML = starHtml(scope, id, e) + editBtnHtml(scope, id);
        return;
      }
      var btn = el.querySelector('.fav-star');
      if (btn) setStar(btn, !!e.starred, !!e.note);
    });
  }

  // F1: keep the local doc in sync after a successful POST, so a refresh
  // before the next get() (and applyStars re-runs) shows the new state.
  function applyLocal(scope, id, patch, meta) {
    if (_doc === null) return;
    var bookKey = scope === 'match' ? 'matches' : 'players';
    var book = _doc[bookKey] || (_doc[bookKey] = {});
    var e = book[id] || (book[id] = { starred: false, tags: [], note: '', saved_at: '', meta: {} });
    if ('starred' in patch) e.starred = !!patch.starred;
    if ('note' in patch) e.note = String(patch.note || '');
    if ('tags' in patch) {
      e.tags = String(patch.tags || '').split(',').map(function (t) { return t.trim(); })
        .filter(Boolean).slice(0, 20);
    }
    if (meta) {
      var clean = {};
      for (var k in meta) if (meta[k]) clean[k] = String(meta[k]).slice(0, 200);
      e.meta = Object.assign(e.meta || {}, clean);
    }
    return e;
  }

  function mountAll() {
    ensureStyles();
    document.querySelectorAll('[data-match-card]:not([data-fav-mounted])').forEach(function (el) {
      el.setAttribute('data-fav-mounted', '1');
      var id = el.getAttribute('data-match-card');
      // standalone mount point (match detail header): star + edit inline
      if (el.hasAttribute('data-fav-standalone')) {
        var e = entryFor('match', id) || {};
        el.innerHTML = starHtml('match', id, e) + editBtnHtml('match', id);
        return;
      }
      var slot = el.querySelector('.mc-actions');
      if (!slot) return;
      slot.insertAdjacentHTML('afterbegin', starHtml('match', id, entryFor('match', id)));
    });
    document.querySelectorAll('[data-player-star]:not([data-fav-mounted])').forEach(function (el) {
      el.setAttribute('data-fav-mounted', '1');
      var id = el.getAttribute('data-player-star');
      el.innerHTML = starHtml('player', id, entryFor('player', id)) + editBtnHtml('player', id);
    });
  }

  // ---- note/tags editor overlay (Phase S: closes the L1 gap — the API
  // always supported note/tags patches but no UI ever called them) ----
  function openEditor(scope, id) {
    var entry = entryFor(scope, id) || {};
    var existing = get().then(function (d) {
      _doc = d;
      return (d[scope === 'match' ? 'matches' : 'players'] || {})[id] || {};
    });
    existing.then(function (e) {
      var ov = document.createElement('div');
      ov.className = 'fav-editor';
      ov.innerHTML =
        '<div class="fav-editor-box fav-editor">' +
        '<div class="fav-editor-title"><span>' + (scope === 'match' ? '对局' : '选手') + '备注与标签</span>' +
        '<button class="fav-editor-x" type="button" title="关闭">✕</button></div>' +
        '<label for="fav-editor-note">备注</label>' +
        '<textarea id="fav-editor-note" rows="5" maxlength="2000" ' +
        'placeholder="比如：这把翻盘局 / 枪法状态好 / 队友 id 备注…"></textarea>' +
        '<label for="fav-editor-tags">标签（逗号分隔）</label>' +
        '<input id="fav-editor-tags" maxlength="600" placeholder="比如：五排, 翻盘, nuke">' +
        '<div class="fav-editor-actions">' +
        '<button class="fav-editor-save" type="button">保存</button>' +
        '<span class="sub fav-editor-msg"></span></div></div>';
      document.body.appendChild(ov);
      var ta = ov.querySelector('#fav-editor-note');
      var tagsIn = ov.querySelector('#fav-editor-tags');
      ta.value = e.note || '';
      tagsIn.value = (e.tags || []).join(', ');
      ta.focus();
      function close() { ov.remove(); }
      ov.querySelector('.fav-editor-x').addEventListener('click', close);
      ov.addEventListener('click', function (ev) { if (ev.target === ov) close(); });
      ov.querySelector('.fav-editor-save').addEventListener('click', function () {
        var msg = ov.querySelector('.fav-editor-msg');
        var patch = { note: ta.value, tags: tagsIn.value };
        post({
          scope: scope, id: id,
          patch: patch,
          meta: collectMeta(scope, id),
        }).then(function (res) {
          if (res && res.ok) {
            applyLocal(scope, id, patch, collectMeta(scope, id));
            close();
            // refresh dot markers on any star button for this item
            document.querySelectorAll('.fav-star[data-fav-scope="' + scope + '"][data-fav-id="' + id + '"]')
              .forEach(function (btn) {
                setStar(btn, btn.classList.contains('on'), !!ta.value.trim());
              });
          } else {
            msg.textContent = '保存失败，请重试';
          }
        }).catch(function () { msg.textContent = '保存失败，请重试'; });
      });
    });
  }

  function collectMeta(scope, id) {
    // reuse the same denormalization the star path uses
    if (scope === 'match') {
      var host = document.querySelector('[data-match-card="' + id + '"]');
      if (!host) return null;
      var fn = host.getAttribute('data-fav-meta-filename') ||
        (host.querySelector('.mc-name') && host.querySelector('.mc-name').textContent.trim()) || '';
      var mn = host.getAttribute('data-fav-meta-map') ||
        (host.querySelector('.mc-map-name') && host.querySelector('.mc-map-name').textContent.trim()) || '';
      return { filename: fn, map_name: mn };
    }
    var ph = document.querySelector('[data-player-star="' + id + '"]');
    var nm = ph ? ph.getAttribute('data-player-name') : '';
    return nm ? { name: nm } : null;
  }

  document.addEventListener('click', function (ev) {
    var edit = ev.target.closest('.fav-edit');
    if (edit) {
      ev.preventDefault();
      ev.stopPropagation();
      openEditor(edit.getAttribute('data-fav-scope'), edit.getAttribute('data-fav-id'));
      return;
    }
    var btn = ev.target.closest('.fav-star');
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    var scope = btn.getAttribute('data-fav-scope');
    var id = btn.getAttribute('data-fav-id');
    var nowOn = !btn.classList.contains('on');
    setStar(btn, nowOn, false);
    // denormalize display meta from the DOM so /favorites shows names
    var meta = collectMeta(scope, id);
    var body = { scope: scope, id: id, patch: { starred: nowOn } };
    if (meta) body.meta = meta;
    function rollback() {
      var e = entryFor(scope, id) || {};
      setStar(btn, !nowOn, !!e.note);
    }
    post(body).then(function (res) {
      if (!res || !res.ok) { rollback(); return; }
      applyLocal(scope, id, body.patch, meta);
      var e = entryFor(scope, id) || {};
      setStar(btn, nowOn, !!e.note);
    }).catch(rollback);
  });  // ---- /favorites page ----
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
        var notes = matches.concat(players).filter(function (kv) { return tagOk(kv[1]); });
        nWrap.innerHTML = notes.length ? notes.map(function (kv) {
          var id = kv[0], e = kv[1], m = e.meta || {};
          var scope = id in (doc.matches || {}) ? 'match' : 'player';
          var href = scope === 'match' ? '/match/' + esc(id) : '/player/' + esc(id);
          var label = m.filename || m.name || id.slice(0, 12);
          return '<div style="margin-bottom:10px" data-fav-note-row="' + esc(id) + '">' +
            '<a href="' + href + '"><b>' + esc(label) + '</b></a>' + editBtnHtml(scope, id) +
            '<div class="sub" style="white-space:pre-wrap">' + esc(e.note) + '</div>' +
            ((e.tags || []).length ? '<div>' + e.tags.map(function (t) {
              return '<span class="badge kb-info" style="margin-right:4px">' + esc(t) + '</span>';
            }).join('') + '</div>' : '') + '</div>';
        }).join('') : '<span class="sub">暂无备注 — 在对局/选手页点 ✎ 即可编辑。</span>';
      }
      draw();
    });
  }

  window.CSAFavorites = { post: post, get: get, mountAll: mountAll, starHtml: starHtml, entryFor: entryFor, renderFavoritesPage: renderFavoritesPage };
  window.renderFavoritesPage = renderFavoritesPage; // favorites.html inline caller
  document.addEventListener('DOMContentLoaded', mountAll);
})();
