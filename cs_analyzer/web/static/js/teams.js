// Phase L4: 队伍视图 — lineup fingerprint grouping (车队局 vs 单排局).
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function pct(v) { return v == null ? '—' : (v * 100).toFixed(1) + '%'; }

  function groupCard(g, title) {
    return '<div class="sub" style="margin-bottom:6px">' + title + '</div>' +
      '<div class="stat-row" style="grid-template-columns:1fr 1fr 1fr">' +
      '<div class="stat-card"><div class="stat-label">场次</div><div class="stat-value">' + g.matches + '</div></div>' +
      '<div class="stat-card"><div class="stat-label">己方回合胜率</div><div class="stat-value ' +
      (g.avg_our_win_rate != null && g.avg_our_win_rate >= 0.5 ? 'pos' : 'neg') + '">' + pct(g.avg_our_win_rate) + '</div></div>' +
      '<div class="stat-card"><div class="stat-label">地图池</div><div class="stat-value" style="font-size:13px;line-height:1.5">' +
      (g.maps || []).map(esc).join('<br>') + '</div></div></div>';
  }

  function lineupTable(lineups, demoHash) {
    var sides = ['CT', 'T'];
    var html = '<div class="grid" style="grid-template-columns:1fr 1fr;gap:8px">';
    sides.forEach(function (side) {
      html += '<div><div class="sub" style="margin-bottom:4px;color:' +
        (side === 'T' ? 'var(--t)' : 'var(--ct)') + '">' + side + ' 首发</div>';
      (lineups[side] || []).forEach(function (pl) {
        var r = pl.rating;
        html += '<div style="display:flex;justify-content:space-between;font-size:12px;padding:2px 0">' +
          '<a href="/player/' + esc(pl.steamid) + '">' + esc(pl.name) + '</a>' +
          '<span class="' + (r != null && r >= 1 ? 'pos' : 'neg') + '">' +
          (r != null ? r.toFixed(2) : '—') + '</span></div>';
      });
      html += '</div>';
    });
    html += '</div>';
    return html;
  }

  function init() {
    fetch('/api/lineups.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        document.getElementById('tm-regulars').innerHTML = (d.regulars || []).map(function (r) {
          return '<button class="chip chip-sm" type="button">' + esc(r.name) + ' · ' + r.appearances + '场</button>';
        }).join('') || '<span class="sub">无</span>';
        document.getElementById('tm-stack-group').innerHTML = groupCard(d.groups.stack, '与固定队友开黑的场次');
        document.getElementById('tm-solo-group').innerHTML = groupCard(d.groups.solo, '独自匹配的场次');

        var wrap = document.getElementById('tm-matches');
        wrap.innerHTML = (d.matches || []).map(function (m) {
          return '<div class="card" style="margin-bottom:12px">' +
            '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">' +
            '<div><b>' + esc(m.map) + '</b> · <span class="sub">' + esc(m.filename) + '</span></div>' +
            '<div><span class="badge ' + (m.is_stack ? 't0' : '') + '">' + (m.is_stack ? '车队 ' + m.stack_size + ' 人' : '单排') + '</span> ' +
            '<span class="sub">己方胜率 ' + pct(m.our_win_rate) + '（' + (m.our_rounds || 0) + ' 回合）</span> ' +
            '<a href="/match/' + esc(m.demo_hash) + '">查看 →</a></div></div>' +
            '<div class="sub" style="margin-bottom:6px">常客: ' + esc((m.regulars || []).join('、')) + '</div>' +
            lineupTable(m.lineups, m.demo_hash) + '</div>';
        }).join('') || '<div class="empty-state"><div class="empty-title">暂无场次</div></div>';
      })
      .catch(function () { /* leave skeleton */ });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
