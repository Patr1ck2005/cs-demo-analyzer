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

        // map chips + spots chart
        var chips = document.getElementById('ul-map-chips');
        var maps = d.maps || [];
        if (!maps.length || !chartDom) return;
        var active = maps[0];
        chips.innerHTML = maps.map(function (m) {
          var n = (d.spots_by_map[m] || []).length;
          return '<button class="chip' + (m === active ? ' on' : '') + '" data-map="' + esc(m) +
            '" type="button">' + esc(m) + ' · ' + n + '</button>';
        }).join('');
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
        chips.querySelectorAll('[data-map]').forEach(function (b) {
          b.addEventListener('click', function () {
            chips.querySelectorAll('[data-map]').forEach(function (x) { x.classList.remove('on'); });
            b.classList.add('on');
            draw(b.getAttribute('data-map'));
          });
        });
        draw(active);
      })
      .catch(function () { /* page stays with empty tables */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
