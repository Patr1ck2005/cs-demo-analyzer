// 复盘提升包 A1: global quick search (Ctrl+K command palette).
// Data: /api/search.json over the T1 aggregate memo (request-safe);
// rendering escapes all server-derived strings via CSACommon.esc.
(function () {
  const overlay = document.getElementById('cmdk');
  if (!overlay) return;
  const input = document.getElementById('cmdk-input');
  const list = document.getElementById('cmdk-list');
  let rows = [];
  let sel = 0;
  let timer = null;

  const HINT = '<div class="cmdk-hint">输入 昵称 / SteamID / 地图 / 文件名…</div>';

  function open() {
    overlay.hidden = false;
    input.value = '';
    list.innerHTML = HINT;
    rows = [];
    input.focus();
  }

  function close() { overlay.hidden = true; }

  function render() {
    if (!rows.length) { list.innerHTML = '<div class="cmdk-hint">无匹配结果</div>'; return; }
    list.innerHTML = rows.map((x, i) =>
      `<a class="cmdk-row${i === sel ? ' sel' : ''}" href="${x.href}">` +
      `<span class="cmdk-tag">${CSACommon.esc(x.tag)}</span>` +
      `<span class="cmdk-main">${CSACommon.esc(x.main)}</span>` +
      `<span class="cmdk-sub">${CSACommon.esc(x.sub)}</span></a>`).join('');
    const cur = list.children[sel];
    if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
  }

  async function run(q) {
    if (!q.trim()) { list.innerHTML = HINT; rows = []; return; }
    try {
      const r = await fetch('/api/search.json?q=' + encodeURIComponent(q));
      if (r.status === 503) {  // R3-F3: aggregate memo still rebuilding
        list.innerHTML = '<div class="cmdk-hint">预热中（聚合重算进行中）…</div>';
        return;
      }
      if (!r.ok) return;
      const d = await r.json();
      rows = [];
      for (const p of d.players) rows.push({ href: '/player/' + p.steamid, tag: '选手', main: p.name, sub: p.sub });
      for (const m of d.matches) rows.push({ href: '/match/' + m.hash, tag: '对局', main: m.name, sub: m.sub });
      sel = 0;
      render();
    } catch (e) { /* transient — next keystroke retries */ }
  }

  document.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && (ev.key === 'k' || ev.key === 'K')) {
      ev.preventDefault();
      overlay.hidden ? open() : close();
    } else if (ev.key === 'Escape' && !overlay.hidden) {
      close();
    }
  });

  overlay.addEventListener('click', (ev) => {
    if (ev.target === overlay || ev.target.classList.contains('cmdk-backdrop')) close();
    const a = ev.target.closest('.cmdk-row');
    if (a) close();  // navigate via href
  });

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => run(input.value), 150);
  });

  input.addEventListener('keydown', (ev) => {
    if (!rows.length) return;
    if (ev.key === 'ArrowDown') { ev.preventDefault(); sel = (sel + 1) % rows.length; render(); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); sel = (sel - 1 + rows.length) % rows.length; render(); }
    else if (ev.key === 'Enter') {
      ev.preventDefault();
      if (rows[sel]) { close(); location.href = rows[sel].href; }
    }
  });
})();
