// Phase L4: 队伍视图 — lineup fingerprint grouping (车队局 vs 单排局).
// Phase X: 五排协同 moved here from /compare (the section's natural home —
// same 常客/车队 concepts, one page instead of two cross-linking ones).
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

  // ---- Phase X: five-stack teamplay (network + contrast + portraits) ----
  // Ported from the old /compare inline script verbatim, modulo esc() and
  // the canonical API path.
  function loadTeamplay() {
    fetch('/api/teams/teamplay.json', { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(renderTeamplay)
      .catch(function () {
        var meta = document.getElementById('tp-meta');
        if (meta) meta.textContent = '五排协同数据加载失败';
      });
  }

  function renderTeamplay(tp) {
    var meta = document.getElementById('tp-meta');
    var sv = tp.stack_vs_mixed;
    if (!tp.regulars.length) {
      if (meta) meta.textContent =
        '5E 样本不足（需 ' + tp.library.min_regular_demos + ' 场以上常客）';
      return;
    }
    if (meta) meta.textContent =
      '5E ' + tp.library.five_e_demos + ' 场 · 常客 ' + tp.regulars.length + ' 人 · ' +
      '五排局 ' + sv.stack_matches + ' / 混野 ' + sv.mixed_matches;

    // heatmap: symmetric link weights between regulars
    var hm = echarts.init(document.getElementById('tp-heatmap'), 'csa');
    var players = tp.matrix.players;
    var data = [];
    players.forEach(function (a, i) {
      players.forEach(function (b, j) {
        if (i !== j) data.push([j, i, tp.matrix.values[i][j]]);
      });
    });
    var maxW = Math.max(1, Math.max.apply(null, data.map(function (d) { return d[2]; })));
    hm.setOption({
      tooltip: { formatter: function (p) { return players[p.value[1]] + ' ↔ ' + players[p.value[0]] + ': ' + p.value[2]; } },
      grid: { left: 110, right: 20, top: 10, bottom: 60 },
      xAxis: { type: 'category', data: players, axisLabel: { color: '#9aa0b8', fontSize: 10, rotate: 40 },
               axisLine: { lineStyle: { color: '#262942' } } },
      yAxis: { type: 'category', data: players, axisLabel: { color: '#9aa0b8', fontSize: 10 },
               axisLine: { lineStyle: { color: '#262942' } } },
      visualMap: { min: 0, max: maxW, calculable: false, orient: 'horizontal',
                   left: 'center', bottom: 0, itemHeight: 80, itemWidth: 12,
                   inRange: { color: ['#26294a', '#8b5cf6'] }, textStyle: { color: '#9aa0b8', fontSize: 10 } },
      series: [{ type: 'heatmap', data: data,
                 label: { show: true, color: '#eceaf6', fontSize: 9 },
                 itemStyle: { borderColor: '#10111d', borderWidth: 1 } }],
    });

    // top links table
    var links = tp.links.slice(0, 10).map(function (l) {
      return '<tr><td>' + esc(l.a_name) + ' → ' + esc(l.b_name) + '</td>' +
        '<td class="num">' + l.assists + '</td><td class="num">' + l.trades + '</td>' +
        '<td class="num">' + l.flash_assists + '</td><td class="num"><b>' + l.weight + '</b></td></tr>';
    }).join('');
    document.getElementById('tp-links').innerHTML =
      '<table><thead><tr><th>连线（助攻方 → 被助方 / 复仇者 → 被复仇者）</th>' +
      '<th class="num">助攻</th><th class="num">补枪</th><th class="num">闪助</th><th class="num">权重</th>' +
      '</tr></thead><tbody>' + links + '</tbody></table>';

    // portraits
    document.getElementById('tp-portraits').innerHTML = tp.portraits.map(function (p) {
      var labels = p.labels.map(function (x) {
        return '<span class="badge kb-headshot" title="' + esc(x.detail) + '">' + esc(x.label) +
          (x.low_sample ? ' <span class="badge no" title="样本少于 3 次">少</span>' : '') + '</span>';
      }).join(' ');
      var partner = p.best_partner
        ? ' · 最佳搭档 <b>' + esc(p.best_partner.name) + '</b>(' + (p.best_partner.per_demo ?? '—') + '/场 · 共' + p.best_partner.weight + ')' : '';
      return '<div>' + esc(p.name) + ' <span class="sub">' + p.appearances + ' 场' + partner + '</span> ' + labels + '</div>';
    }).join('');

    // stack vs mixed contrast tiles
    var tile = function (name, s, m) {
      var f = function (v, suf) { suf = suf || ''; return v == null ? '-' : (v * 100).toFixed(1) + suf; };
      return '<div class="stat-card" style="min-width:200px"><div class="stat-label">' + name + ' 回合胜率</div>' +
        '<div class="stat-value">' + f(s.round_win_rate, '%') + '</div>' +
        '<div class="sub">混野 ' + f(m.round_win_rate, '%') + ' · 胜率差 ' +
        (s.round_win_rate != null && m.round_win_rate != null ? ((s.round_win_rate - m.round_win_rate) * 100).toFixed(1) + 'pp' : '-') + '</div></div>' +
        '<div class="stat-card" style="min-width:200px"><div class="stat-label">' + name + ' 场均 Rating</div>' +
        '<div class="stat-value">' + (s.avg_rating ?? '-') + '</div>' +
        '<div class="sub">混野 ' + (m.avg_rating ?? '-') + '</div></div>' +
        '<div class="stat-card" style="min-width:200px"><div class="stat-label">' + name + ' 首杀成功率</div>' +
        '<div class="stat-value">' + f(s.fk_success, '%') + '</div>' +
        '<div class="sub">混野 ' + f(m.fk_success, '%') + ' · ' + s.fk_duels + ' 次对枪</div></div>';
    };
    document.getElementById('tp-contrast').innerHTML =
      '<div style="display:flex;gap:12px;flex-wrap:wrap">' +
      tile('车队局（≥' + tp.library.stack_threshold + ' 常客同场）', sv.stack, sv.mixed) + '</div>' +
      '<div class="sub" style="margin-top:6px">车队局 ' + sv.stack_matches + ' 场；混野为其余 ' +
      sv.mixed_matches + ' 场 5E（常客不足同场）。Rating 为该组常客样本均值。</div>';
  }

  function init() {
    initLineups();
    loadTeamplay();
  }

  function initLineups() {
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
