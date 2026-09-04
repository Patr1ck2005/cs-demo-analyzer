// Phase M: 趣味数据实验室 — quadrant scatter over cross-library fun metrics.
// 口径全部按 docs/funlab-metrics.md v2（用户已裁决）。
(function () {
  'use strict';

  var METRICS = {
    // 经济
    drop_generosity: { label: '发枪慷慨率', pct: true },
    vulture_rate:    { label: '吸血率（被供枪）', pct: true },
    drop_poor_share: { label: '雪中送炭占比', pct: true },
    drop_profit_rate:{ label: '发枪成材率', pct: true },
    drop_waste_rate: { label: '浪费发枪率', pct: true },
    showoff_rate:    { label: '装逼率（eco局沙鹰/鸟狙）', pct: true },
    pure_eco_rate:   { label: '纯eco率（eco局裸吊）', pct: true },
    rebel_rate:      { label: '叛逆起枪率（eco局长枪）', pct: true },
    rebel_win_rate:  { label: '赌狗胜率（叛逆局）', pct: true },
    free_pickup_rate:{ label: '白嫖率（捡阵亡队友枪）', pct: true },
    // 击杀
    eco_frag_rate:   { label: 'eco特率', pct: true },
    eco_hard_rate:   { label: '神仙率（每eco局）', pct: true },
    whiff_rate:      { label: '白给率', pct: true },
    snipe_rate:      { label: '抢人头率', pct: true },
    stolen_rate:     { label: '被抢人头率', pct: true },
    clutch_freq:     { label: '残局频率', pct: true },
    multi_rate:      { label: '多杀率', pct: true },
    avg_dist_m:      { label: '平均交战距离(m)', pct: false },
    awp_rate:        { label: '狙击依赖', pct: true },
    // 花活
    wallbang_rate:   { label: '穿墙杀率', pct: true },
    thrusmoke_rate:  { label: '烟中杀率', pct: true },
    noscope_rate:    { label: '盲狙率', pct: true },
    blind_rate:      { label: '致盲杀率', pct: true },
    air_rate:        { label: '空中杀率', pct: true },
    knife_rate:      { label: '刀杀率', pct: true },
    flags_rate:      { label: '花活合计率', pct: true },
    // 团队
    team_dmg_rpr:    { label: '队伤/回合', pct: false },
    avenged_rate:    { label: '被复仇率', pct: true },
    revenge_rate:    { label: '复仇率', pct: true },
    jame_index:      { label: '保枪率(Jame)', pct: true },
  };

  // 按意义组合的配方（docs/funlab-metrics.md 预设视图表）
  var PRESETS = [
    { name: '谁在养队', x: 'drop_generosity', y: 'vulture_rate',
      hint: '右上=又发又吸的双面人，左下=自给自足' },
    { name: '穷时的意志', x: 'drop_poor_share', y: 'drop_generosity',
      hint: '自己没钱还发枪=真情赞助商' },
    { name: '数据毒瘤', x: 'eco_frag_rate', y: 'whiff_rate',
      hint: '右上=刷经济局人头+零贡献暴毙' },
    { name: '人头账', x: 'snipe_rate', y: 'stolen_rate',
      hint: '抢王 vs 被抢王，中间=互不亏欠' },
    { name: '残局画像', x: 'clutch_freq', y: 'avg_dist_m',
      hint: '孤胆狙位 vs 贴脸疯狗' },
    { name: '花活大师', x: 'flags_rate', y: 'multi_rate',
      hint: '花活且有产出=节目效果担当' },
    { name: '保险大师', x: 'jame_index', y: 'multi_rate',
      hint: '高保枪低多杀=Jame 本 Jame' },
    { name: '复仇网络', x: 'revenge_rate', y: 'avenged_rate',
      hint: '团队粘性：右上=互相罩得住' },
    { name: '狙击手画像', x: 'awp_rate', y: 'avg_dist_m',
      hint: '大狙远景 vs 步枪近战' },
    { name: '闪光协同', x: 'blind_rate', y: 'flags_rate',
      hint: '致盲杀占比高=闪光配合好' },
    { name: '叛逆赌狗', x: 'rebel_rate', y: 'rebel_win_rate',
      hint: '队友eco你起长枪：赌得多不多/赌赢了没' },
    { name: '装逼现场', x: 'showoff_rate', y: 'eco_frag_rate',
      hint: '沙鹰鸟狙玩家：装逼多≠eco杀得多（或正好相反）' },
    { name: '白眼狼象限', x: 'free_pickup_rate', y: 'vulture_rate',
      hint: '右上=捡死人枪+吃供枪双修的吸血管' },
  ];

  var DATA = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function fmtVal(v, key) {
    if (v == null) return '—';
    var m = METRICS[key];
    if (m && m.pct) return (v * 100).toFixed(1) + '%';
    return (typeof v === 'number' && !Number.isInteger(v)) ? v.toFixed(2) : String(v);
  }

  function median(arr) {
    if (!arr.length) return 0;
    var s = arr.slice().sort(function (a, b) { return a - b; });
    var mid = Math.floor(s.length / 2);
    return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
  }

  function option() {
    var xk = document.getElementById('fl-x').value;
    var yk = document.getElementById('fl-y').value;
    var mx = METRICS[xk], my = METRICS[yk];
    var pts = DATA.players.map(function (p) {
      return {
        name: p.name, value: [p[xk], p[yk]],
        sid: p.steamid, kills: p.kills, demos: p.demos,
        symbolSize: 9 + Math.min(18, p.demos * 2.4),  // 点大小=样本量
      };
    });
    return {
      grid: { left: 64, right: 30, top: 40, bottom: 56 },
      tooltip: {
        confine: true,
        formatter: function (q) {
          var p = q.data;
          return '<b>' + esc(p.name) + '</b><br>' + esc(mx.label) + ': <b>' + fmtVal(p.value[0], xk) +
            '</b><br>' + esc(my.label) + ': <b>' + fmtVal(p.value[1], yk) +
            '</b><br>' + p.kills + ' 杀 · ' + p.demos + ' 场';
        },
      },
      xAxis: { type: 'value', name: mx.label, nameLocation: 'middle', nameGap: 30,
               nameTextStyle: { color: '#9aa0b8', fontSize: 12 },
               splitLine: { show: true, lineStyle: { color: 'rgba(120,120,160,.15)' } },
               axisLabel: { color: '#9aa0b8', formatter: mx.pct ? function (v) { return (v * 100).toFixed(0) + '%'; } : undefined } },
      yAxis: { type: 'value', name: my.label, nameLocation: 'middle', nameGap: 44,
               nameTextStyle: { color: '#9aa0b8', fontSize: 12 },
               splitLine: { show: true, lineStyle: { color: 'rgba(120,120,160,.15)' } },
               axisLabel: { color: '#9aa0b8', formatter: my.pct ? function (v) { return (v * 100).toFixed(0) + '%'; } : undefined } },
      series: [{
        type: 'scatter', data: pts,
        label: { show: true, position: 'top', color: '#c4b5fd', fontSize: 11,
                 formatter: function (q) { return q.data.name.length > 9 ? q.data.name.slice(0, 9) + '…' : q.data.name; } },
        itemStyle: { opacity: 0.88, borderColor: 'rgba(0,0,0,.5)', borderWidth: 1,
                     color: function (q) { return playerColor(q.data.name); } },
        markLine: {
          silent: true, symbol: 'none', lineStyle: { color: 'rgba(196,181,253,.4)', type: 'dashed' },
          label: { show: false },
          data: [
            { xAxis: median(DATA.players.map(function (p) { return p[xk]; })) },
            { yAxis: median(DATA.players.map(function (p) { return p[yk]; })) },
          ],
        },
      }],
    };
  }

  // per-player stable colors (assigned by board position once, kept on redraw)
  var PALETTE = ['#a78bfa', '#3ddc97', '#ffb02e', '#3d9bff', '#ff4d5e',
                 '#f472b6', '#34d399', '#fbbf24', '#60a5fa', '#f87171',
                 '#a3e635', '#c084fc', '#2dd4bf', '#fb923c'];

  function playerColor(name) {
    if (!(name in colorMap)) colorMap[name] = PALETTE[Object.keys(colorMap).length % PALETTE.length];
    return colorMap[name];
  }
  var colorMap = {};

  function board(title, rows, valueKey, unit) {
    var html = '<div class="card" style="margin-bottom:0"><h2 style="border:none">' + title + '</h2>';
    rows.forEach(function (p, i) {
      var v = p[valueKey];
      var txt = unit === 'pct' ? (v * 100).toFixed(1) + '%' : (unit === '$' ? v + '$' : v);
      if (valueKey === 'rebel_rate') {
        txt += ' <span class="sub">(' + (p.rebel_rounds || 0) + '局' + (p.rebel_wins || 0) + '胜)</span>';
      }
      html += '<div style="display:flex;justify-content:space-between;font-size:13px;padding:3px 0">' +
        '<span><i style="display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;background:' + playerColor(p.name) + '"></i>' +
        (i + 1) + '. <a href="/player/' + esc(p.steamid) + '">' + esc(p.name) + '</a></span>' +
        '<b style="color:' + playerColor(p.name) + '">' + txt + '</b></div>';
    });
    return html + '</div>';
  }

  function drawBoards() {
    var b = DATA.boards || {};
    document.getElementById('fl-boards').innerHTML =
      board('💸 发枪金主（价值）', b.donor || [], 'drops_value', '$') +
      board('🧟 吸血鬼（被供枪占比）', b.vulture || [], 'vulture_rate', 'pct') +
      board('💝 慷慨率', b.generous || [], 'drop_generosity', 'pct') +
      board('🌧️ 雪中送炭', b.poor_hero || [], 'drop_poor_share', 'pct') +
      board('🪦 白给大师', b.whiff || [], 'whiff_rate', 'pct') +
      board('💰 eco特专家', b.eco || [], 'eco_frag_rate', 'pct') +
      board('🔪 抢人头王', b.snipe || [], 'snipe_rate', 'pct') +
      board('🫠 被抢人头王', b.stolen || [], 'stolen_rate', 'pct') +
      board('🤝 队友伤害王', b.team_dmg || [], 'team_dmg_rpr', '') +
      board('🎯 残局孤胆', b.clutch || [], 'clutch_freq', 'pct') +
      board('🎪 花活集锦', b.flags || [], 'flags_rate', 'pct') +
      board('🏦 保枪大师', b.jame || [], 'jame_index', 'pct') +
      board('🤙 舔包王（捡死队友枪）', b.free_pickup || [], 'free_pickups', '') +
      board('🔥 叛逆赌狗王（胜率含局数）', b.rebel || [], 'rebel_rate', 'pct') +
      board('😎 装逼王（eco局沙鹰/鸟狙）', b.showoff || [], 'showoff_rate', 'pct') +
      board('🥬 纯eco铁公鸡', b.pure_eco || [], 'pure_eco_rate', 'pct');
  }

  var FILTERS = { stack: [], dates: [] };  // empty array = no filter

  function fetchAndDraw(after) {
    var qs = [];
    if (FILTERS.stack.length) qs.push('stack=' + FILTERS.stack.join(','));
    if (FILTERS.dates.length) qs.push('dates=' + FILTERS.dates.join(','));
    fetch('/api/funlab.json' + (qs.length ? '?' + qs.join('&') : ''), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) { DATA = d; drawBoards(); redrawChart(); if (after) after(); });
  }

  var redrawChart = function () {};

  function init() {
    var selX = document.getElementById('fl-x');
    var selY = document.getElementById('fl-y');
    if (!selX) return;
    // load unfiltered once to discover available stacks/dates
    fetch('/api/funlab.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        DATA = d;
        var keys = Object.keys(METRICS);
        selX.innerHTML = keys.map(function (k) {
          return '<option value="' + k + '"' + (k === 'drop_generosity' ? ' selected' : '') + '>' + METRICS[k].label + '</option>';
        }).join('');
        selY.innerHTML = keys.map(function (k) {
          return '<option value="' + k + '"' + (k === 'vulture_rate' ? ' selected' : '') + '>' + METRICS[k].label + '</option>';
        }).join('');
        document.getElementById('fl-presets').innerHTML = PRESETS.map(function (p, i) {
          return '<button class="chip chip-sm' + (i === 0 ? ' on' : '') + '" data-p="' + i +
            '" type="button" title="' + esc(p.hint) + '">' + esc(p.name) + '</button>';
        }).join('');
        var chart = echarts.init(document.getElementById('fl-quadrant'));
        redrawChart = function () { chart.setOption(option(), true); };
        selX.addEventListener('change', redrawChart);
        selY.addEventListener('change', redrawChart);
        document.querySelectorAll('#fl-presets [data-p]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            document.querySelectorAll('#fl-presets [data-p]').forEach(function (x) { x.classList.remove('on'); });
            btn.classList.add('on');
            var p = PRESETS[parseInt(btn.getAttribute('data-p'), 10)];
            selX.value = p.x; selY.value = p.y;
            redrawChart();
          });
        });
        // ---- lineup-size chips (排型) ----
        var stacks = Object.keys(d.lineup_counts || {}).map(Number).sort();
        var stackRow = document.getElementById('fl-stack-chips');
        if (stackRow) {
          stackRow.innerHTML = stacks.map(function (n) {
            var label = n === 1 ? '单排' : n + '排';
            return '<button class="chip chip-sm" data-stack="' + n + '" type="button">' +
              label + ' · ' + d.lineup_counts[n] + '场</button>';
          }).join('') || '<span class="sub">无场次</span>';
          stackRow.querySelectorAll('[data-stack]').forEach(function (btn) {
            btn.addEventListener('click', function () {
              var n = btn.getAttribute('data-stack');
              var i = FILTERS.stack.indexOf(n);
              if (i >= 0) { FILTERS.stack.splice(i, 1); btn.classList.remove('on'); }
              else { FILTERS.stack.push(n); btn.classList.add('on'); }
              fetchAndDraw();
            });
          });
        }
        // ---- date chips (今天/昨天/具体日期) ----
        var dates = d.dates || [];
        var dateRow = document.getElementById('fl-date-chips');
        if (dateRow) {
          var dayLabel = function (ds) {
            var today = new Date();
            var fmt = today.getFullYear() +
              String(today.getMonth() + 1).padStart(2, '0') +
              String(today.getDate()).padStart(2, '0');
            var y = new Date(today); y.setDate(today.getDate() - 1);
            var yfmt = y.getFullYear() + String(y.getMonth() + 1).padStart(2, '0') + String(y.getDate()).padStart(2, '0');
            var y2 = new Date(today); y2.setDate(today.getDate() - 2);
            var y2fmt = y2.getFullYear() + String(y2.getMonth() + 1).padStart(2, '0') + String(y2.getDate()).padStart(2, '0');
            if (ds === fmt) return '今天';
            if (ds === yfmt) return '昨天';
            if (ds === y2fmt) return '前天';
            return ds.slice(4, 6) + '/' + ds.slice(6, 8);
          };
          dateRow.innerHTML = dates.map(function (ds) {
            var cnt = (d.players || []).length; // per-date counts need server info; show label only
            return '<button class="chip chip-sm" data-date="' + ds + '" type="button">' + dayLabel(ds) + '</button>';
          }).join('') || '<span class="sub">无日期信息</span>';
          dateRow.querySelectorAll('[data-date]').forEach(function (btn) {
            btn.addEventListener('click', function () {
              var ds = btn.getAttribute('data-date');
              var i = FILTERS.dates.indexOf(ds);
              if (i >= 0) { FILTERS.dates.splice(i, 1); btn.classList.remove('on'); }
              else { FILTERS.dates.push(ds); btn.classList.add('on'); }
              fetchAndDraw();
            });
          });
        }
        drawBoards();
        redrawChart();
      });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
