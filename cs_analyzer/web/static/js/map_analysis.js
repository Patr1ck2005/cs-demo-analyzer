// Phase L3: 地图分析 — per-map aggregation with routes over the radar PNG.
(function () {
  'use strict';

  var PALETTE = ['#ffb02e', '#3d9bff', '#3ddc97', '#ff4d5e', '#a78bfa'];
  var DATA = null;
  var ACTIVE = null;
  var SIDE = 'T';
  var chart = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function routesOption(routes) {
    return {
      grid: { left: 6, right: 6, top: 6, bottom: 6 },
      xAxis: { type: 'value', min: 0, max: 1, show: false },
      yAxis: { type: 'value', min: 0, max: 1, show: false, inverse: true },
      tooltip: { trigger: 'item' },
      series: routes.map(function (r, i) {
        return {
          name: '路线 ' + (i + 1), type: 'line', data: r.route,
          smooth: true, symbol: 'none', lineWidth: 2,
          lineStyle: { color: PALETTE[i % PALETTE.length], width: 3, opacity: 0.9 },
          itemStyle: { color: PALETTE[i % PALETTE.length] },
        };
      }),
    };
  }

  function draw() {
    var m = DATA.maps.find(function (x) { return x.map_name === ACTIVE; });
    if (!m) return;
    var pct = function (v) { return (v * 100).toFixed(1) + '%'; };
    // S2-A2: T 胜率区间徽章（R1 t_win_conf，n=该图回合数）
    var twc = m.t_win_conf || {};
    var twConf = twc.lo != null
      ? ' <span class="csa-conf' + (twc.gated ? ' csa-conf-gated' : '') +
        '" title="n=' + twc.n + ' 回合，95% 区间">[' + (twc.lo * 100).toFixed(0) + '%–' +
        (twc.hi * 100).toFixed(0) + '%]</span>'
      : '';
    document.getElementById('ma-tiles').innerHTML =
      '<div class="stat-card"><div class="stat-label">对局</div><div class="stat-value">' + m.demos + '</div></div>' +
      '<div class="stat-card"><div class="stat-label">回合</div><div class="stat-value">' + m.rounds + '</div></div>' +
      '<div class="stat-card"><div class="stat-label">T 胜率</div><div class="stat-value v-t">' + pct(m.t_win_rate) + twConf + '</div></div>' +
      '<div class="stat-card"><div class="stat-label">CT 胜率</div><div class="stat-value v-ct">' + pct(m.ct_win_rate) + '</div></div>';

    var dom = document.getElementById('ma-routes');
    dom.style.backgroundImage = 'url("/maps/' + encodeURIComponent(m.map_name) + '.png")';
    // per-demo clusters merge into many fragments — show the strongest 3
    var routes = ((m.routes && m.routes[SIDE]) || [])
      .slice().sort(function (a, b) { return b.share - a.share; }).slice(0, 3);
    if (chart) chart.dispose();
    chart = echarts.init(dom);
    chart.setOption(routesOption(routes));
    var leg = document.getElementById('ma-routes-legend');
    if (routes.length) {
      leg.style.display = 'flex';
      leg.innerHTML = routes.map(function (r, i) {
        return '<span><i style="background:' + PALETTE[i % PALETTE.length] + '"></i>路线 ' + (i + 1) +
          ' · ' + (r.share * 100).toFixed(0) + '%</span>';
      }).join('');
    } else {
      leg.style.display = 'none';
    }

    var sites = m.sites || {};
    var keys = Object.keys(sites);
    var total = keys.reduce(function (a, k) { return a + sites[k]; }, 0);
    document.getElementById('ma-sites').innerHTML = keys.length
      ? keys.map(function (k) {
          var w = total ? sites[k] / total : 0;
          return '<div style="margin-bottom:8px"><div class="sub" style="display:flex;justify-content:space-between">' +
            '<span>包点 ' + esc(k) + '</span><span>' + sites[k] + ' 次 · ' + (w * 100).toFixed(0) + '%</span></div>' +
            '<div style="height:8px;background:var(--panel3);border-radius:4px;overflow:hidden">' +
            '<div style="height:100%;width:' + (w * 100).toFixed(1) + '%;background:var(--grad-accent)"></div></div></div>';
        }).join('')
      : '<span class="sub">该图无下包记录</span>';

    var tb = document.querySelector('#ma-best tbody');
    tb.innerHTML = (m.best_players || []).map(function (bp) {
      // S2-A2: rating_shrunk (EB, n=rounds) + conf badge from the R1 payload
      var conf = bp.conf || {};
      var confHtml = conf.lo != null
        ? ' <span class="csa-conf' + (conf.gated ? ' csa-conf-gated' : '') +
          '" title="n=' + conf.n + ' 回合，95% 区间">[' + bp.rating.toFixed(2) + '–' +
          (+conf.hi).toFixed(2) + ']</span>'
        : '';
      var shrunkHtml = (typeof bp.rating_shrunk === 'number' &&
                        Math.abs(bp.rating_shrunk - bp.rating) > 0.005)
        ? ' <span class="sub" title="经验贝叶斯收缩值（向全库池均值收缩，小样本回拉）">收缩 ' +
          bp.rating_shrunk.toFixed(2) + '</span>'
        : '';
      return '<tr><td><a href="/player/' + esc(bp.steamid) + '">' + esc(bp.name) + '</a></td>' +
        '<td class="num">' + bp.rounds + '</td>' +
        '<td class="num ' + (bp.rating >= 1 ? 'pos' : 'neg') + '">' + bp.rating.toFixed(2) +
        confHtml + shrunkHtml + '</td>' +
        '<td class="num">' + bp.demos + '</td></tr>';
    }).join('') || '<tr><td colspan="4" class="sub">样本不足</td></tr>';
  }

  function init() {
    fetch('/api/map-analysis.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        DATA = d;
        var chips = document.getElementById('ma-map-chips');
        if (!d.maps || !d.maps.length) return;
        ACTIVE = d.maps[0].map_name;
        chips.innerHTML = d.maps.map(function (m) {
          return '<button class="chip' + (m.map_name === ACTIVE ? ' on' : '') + '" data-map="' +
            esc(m.map_name) + '" type="button">' + esc(m.map_name) + ' · ' + m.demos + '场</button>';
        }).join('');
        chips.querySelectorAll('[data-map]').forEach(function (b) {
          b.addEventListener('click', function () {
            chips.querySelectorAll('[data-map]').forEach(function (x) { x.classList.remove('on'); });
            b.classList.add('on');
            ACTIVE = b.getAttribute('data-map');
            draw();
            // Phase X: 道具落点热力跟随上方选中地图联动（utilitylab.js 监听）
            document.dispatchEvent(new CustomEvent('csa:map-changed', { detail: { map: ACTIVE } }));
          });
        });
        document.getElementById('ma-side-t').addEventListener('click', function () {
          SIDE = 'T';
          document.getElementById('ma-side-t').classList.add('on');
          document.getElementById('ma-side-ct').classList.remove('on');
          document.getElementById('ma-side-label').textContent = 'T';
          draw();
        });
        document.getElementById('ma-side-ct').addEventListener('click', function () {
          SIDE = 'CT';
          document.getElementById('ma-side-ct').classList.add('on');
          document.getElementById('ma-side-t').classList.remove('on');
          document.getElementById('ma-side-label').textContent = 'CT';
          draw();
        });
        draw();
      })
      .catch(function () { /* leave skeleton */ });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
