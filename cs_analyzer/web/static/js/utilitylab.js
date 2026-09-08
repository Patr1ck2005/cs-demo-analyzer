// Phase L2: 道具专题 (utility lab) — cross-library utility picture.
(function () {
  'use strict';

  var COLORS = { smoke: '#9aa0b8', kill: '#ff4d5e' };

  function tile(label, value) {
    return '<div class="stat-card"><div class="stat-label">' + label +
      '</div><div class="stat-value">' + value + '</div></div>';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function num(v, digits) {
    return typeof v === 'number' ? v.toFixed(digits == null ? 1 : digits) : '0';
  }

  function spotsOption(spots) {
    var byKind = { smoke: [], kill: [] };
    spots.forEach(function (s) { (byKind[s.kind] || (byKind[s.kind] = [])).push([s.u, s.v]); });
    return {
      grid: { left: 6, right: 6, top: 6, bottom: 6 },
      xAxis: { type: 'value', min: 0, max: 1, show: false },
      yAxis: { type: 'value', min: 0, max: 1, show: false, inverse: true },
      tooltip: { trigger: 'item' },
      series: [
        { name: '烟雾落点', type: 'scatter', data: byKind.smoke, symbolSize: 7,
          itemStyle: { color: COLORS.smoke, opacity: 0.45, borderColor: 'rgba(0,0,0,.5)', borderWidth: 1 } },
        { name: '烟中击杀', type: 'effectScatter', data: byKind.kill, symbolSize: 9,
          rippleEffect: { scale: 2.6 }, itemStyle: { color: COLORS.kill, opacity: 0.95 } },
      ],
    };
  }

  function init() {
    var chartDom = document.getElementById('ul-spots');
    fetch('/api/utilitylab.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var t = d.totals || {};
        document.getElementById('ul-tiles').innerHTML =
          tile('扫描对局', t.demos_scanned || 0) +
          tile('闪光投掷', t.total_throws || 0) +
          tile('敌人致盲(秒)', num(t.total_enemy_blind_s, 0)) +
          tile('闪光助攻', t.total_flash_assists || 0) +
          tile('烟中击杀', t.total_smoke_kills || 0);

        var fb = document.querySelector('#ul-flash-table tbody');
        fb.innerHTML = (d.flashers || []).slice(0, 15).map(function (f) {
          // v5 口径审计：投掷 <3 次的行标"少"——单投高光样本不代表稳定水平
          var low = f.throws < 3 ? ' <span class="badge no" title="样本不足 3 次投掷">少</span>' : '';
          return '<tr><td>' + esc(f.name) + low + '</td><td class="num">' + f.demos +
            '</td><td class="num">' + f.throws + '</td><td class="num">' + num(f.enemy_blind_s) +
            '</td><td class="num pos">' + num(f.value) + '</td><td class="num">' + num(f.value_per_throw, 2) +
            '</td><td class="num">' + (f.flash_assists || 0) + '</td></tr>';
        }).join('') || '<tr><td colspan="7" class="sub">暂无闪光数据</td></tr>';

        var sb = document.querySelector('#ul-smoke-table tbody');
        sb.innerHTML = (d.smoke || []).filter(function (s) { return s.smoke_kills || s.smoke_deaths; })
          .slice(0, 10).map(function (s) {
            return '<tr><td>' + esc(s.name) + '</td><td class="num">' + s.demos +
              '</td><td class="num pos">' + s.smoke_kills + '</td><td class="num neg">' + s.smoke_deaths +
              '</td><td class="num">' + (s.net_per_demo != null ? s.net_per_demo.toFixed(2) : '—') + '</td></tr>';
          }).join('') || '<tr><td colspan="5" class="sub">暂无烟中击杀数据</td></tr>';

        // R4 道具执行科学：支援闪光/迟投/燃烧弹（首次尝试渲染，容器缺失则跳过）
        var execBox = document.getElementById('ul-exec-table');
        if (execBox) {
          var body = execBox.querySelector('tbody');
          var pc = function (v) { return v == null ? '—' : (v * 100).toFixed(0) + '%'; };
          var conf = function (c) { return c ? ' <span class="csa-conf' + (c.gated ? ' csa-conf-gated' : '') + '">[' +
            pc(c.lo) + '–' + pc(c.hi) + ']</span>' : ''; };
          body.innerHTML = (d.exec_players || []).slice(0, 12).map(function (e) {
            return '<tr><td>' + esc(e.name) + '</td><td class="num">' + e.demos +
              '</td><td class="num">' + e.enemy_blind_throws + '</td>' +
              '<td class="num pos">' + e.support_kills + conf(e.support_conf) + '</td>' +
              '<td class="num">' + pc(e.support_flash_rate) + '</td>' +
              '<td class="num">' + pc(e.late_rate) + '</td>' +
              '<td class="num">' + (e.molly_dmg_per_throw != null ? e.molly_dmg_per_throw : '—') + '</td></tr>';
          }).join('') || '<tr><td colspan="7" class="sub">暂无执行数据</td></tr>';
        }
        var bucketBox = document.getElementById('ul-smoke-buckets');
        if (bucketBox) {
          var pc2 = function (v) { return v == null ? '—' : (v * 100).toFixed(0) + '%'; };
          var sel = null;
          var onPage = document.querySelector('#ma-map-chips .chip.on');
          if (onPage) sel = onPage.getAttribute('data-map');
          var rows = (d.smoke_buckets || []).filter(function (b) { return !sel || b.map_name === sel; });
          bucketBox.innerHTML = rows.map(function (b) {
            return '<tr><td>' + esc(b.map_name) + '</td><td>' + (b.side === 'T' ? 'T' : 'CT') + '</td>' +
              '<td class="num">' + (b.smokes === 2 ? '2+' : b.smokes) + '</td>' +
              '<td class="num">' + b.rounds + '</td>' +
              '<td class="num">' + pc2(b.win_rate) +
              ' <span class="csa-conf' + (b.conf.gated ? ' csa-conf-gated' : '') + '">[' + pc2(b.conf.lo) + '–' + pc2(b.conf.hi) + ']</span></td></tr>';
          }).join('') || '<tr><td colspan="5" class="sub">当前图暂无烟阻桶数据</td></tr>';
          document.addEventListener('csa:map-changed', function (ev) {
            var m = ev.detail && ev.detail.map;
            bucketBox.innerHTML = (d.smoke_buckets || []).filter(function (b) { return b.map_name === m; })
              .map(function (b) {
                return '<tr><td>' + esc(b.map_name) + '</td><td>' + (b.side === 'T' ? 'T' : 'CT') + '</td>' +
                  '<td class="num">' + (b.smokes === 2 ? '2+' : b.smokes) + '</td>' +
                  '<td class="num">' + b.rounds + '</td>' +
                  '<td class="num">' + pc2(b.win_rate) +
                  ' <span class="csa-conf' + (b.conf.gated ? ' csa-conf-gated' : '') + '">[' + pc2(b.conf.lo) + '–' + pc2(b.conf.hi) + ']</span></td></tr>';
              }).join('') || '<tr><td colspan="5" class="sub">当前图暂无烟阻桶数据</td></tr>';
          });
        }

        // map chips + spots chart
        var chips = document.getElementById('ul-map-chips');
        var maps = d.maps || [];
        if (!maps.length || !chartDom) return;
        // Phase X: the section merged into /map-analysis — the page-level
        // map selector (map_analysis.js) is the single source of truth; hide
        // the redundant chips row and follow its csa:map-changed events.
        var chipRow = chips.parentElement;
        if (chipRow) chipRow.style.display = 'none';
        var chart = null;
        function draw(mapName) {
          chartDom.style.backgroundImage = 'url("/maps/' + encodeURIComponent(mapName) + '.png")';
          var opt = spotsOption(d.spots_by_map[mapName] || []);
          if (chart) chart.dispose();
          chart = echarts.init(chartDom);
          chart.setOption(opt);
          var leg = document.getElementById('ul-spots-legend');
          leg.style.display = 'flex';
          leg.innerHTML = '<span><i style="background:' + COLORS.smoke + '"></i>烟雾落点</span>' +
            '<span><i style="background:' + COLORS.kill + '"></i>烟中击杀</span>';
        }
        function drawMap(mapName) {
          if (maps.indexOf(mapName) < 0) return;
          draw(mapName);
        }
        document.addEventListener('csa:map-changed', function (ev) {
          drawMap(ev.detail && ev.detail.map);
        });
        // initial frame: follow the page selector's current map if it exists
        var pageMap = null;
        var onPage = document.querySelector('#ma-map-chips .chip.on');
        if (onPage) pageMap = onPage.getAttribute('data-map');
        draw((pageMap && maps.indexOf(pageMap) >= 0) ? pageMap : maps[0]);
      })
      .catch(function () {
        // S2-V4: failure must settle the placeholders, not leave "加载中…"
        var fb = document.querySelector('#ul-flash-table tbody');
        if (fb) fb.innerHTML = '<tr><td colspan="7" class="sub">数据不可用（服务端错误）</td></tr>';
        var sb2 = document.querySelector('#ul-smoke-table tbody');
        if (sb2) sb2.innerHTML = '<tr><td colspan="5" class="sub">数据不可用（服务端错误）</td></tr>';
        var eb2 = document.querySelector('#ul-exec-table tbody');
        if (eb2) eb2.innerHTML = '<tr><td colspan="7" class="sub">数据不可用（服务端错误）</td></tr>';
        var bk = document.getElementById('ul-smoke-buckets');
        if (bk) bk.innerHTML = '<tr><td colspan="5" class="sub">数据不可用（服务端错误）</td></tr>';
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
