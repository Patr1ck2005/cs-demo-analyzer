// Phase M: 趣味数据实验室 — quadrant scatter over cross-library fun metrics.
// 口径全部按 docs/funlab-metrics.md v5（用户已裁决）。v5 口径审计：
// 指标口径字典由服务端下发（funlab_data.METRIC_DEFS），页面/轴/榜单统一引用。
(function () {
  'use strict';

  var METRICS = {};   // {key: {label, pct}} — 由 /api/funlab.json 的 metric_defs 填充
  var DEFS = { metrics: {}, boards: {} };

  function loadDefs(d) {
    var defs = d.metric_defs || {};
    Object.keys(defs).forEach(function (k) {
      METRICS[k] = { label: defs[k].label, pct: defs[k].pct };
    });
    DEFS.metrics = defs;
    DEFS.boards = d.board_defs || {};
  }

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

  function board(bid, title, rows, valueKey, unit) {
    var def = DEFS.boards[bid] || DEFS.metrics[valueKey] || null;
    var html = '<div class="card" style="margin-bottom:0"><h2 style="border:none">' + title + '</h2>';
    if (def && (def.formula || def.note)) {
      html += '<div class="sub" style="font-size:11px;line-height:1.5;margin:-8px 0 6px">口径: ' +
        esc(def.formula || '') + (def.note ? '。' + esc(def.note) : '') + '</div>';
    }
    rows.forEach(function (p, i) {
      var v = p[valueKey];
      var txt = unit === 'pct' ? (v * 100).toFixed(1) + '%'
        : (unit === 'pr' ? (v).toFixed(2) + '/回合'
        : (unit === '$' ? v + '$' : v));
      if (valueKey === 'rebel_rate') {
        txt += ' <span class="sub">(' + (p.rebel_rounds || 0) + '局' + (p.rebel_wins || 0) + '胜)</span>';
      }
      if (valueKey === 'free_pickup_pr') {
        txt += ' <span class="sub">(' + (p.free_pickups || 0) + '次)</span>';
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
      board('donor', '💸 发枪金主（价值）', b.donor || [], 'drops_value', '$') +
      board('vulture', '🧟 吸血鬼（被供枪占比）', b.vulture || [], 'vulture_rate', 'pct') +
      board('generous', '💝 慷慨率', b.generous || [], 'drop_generosity', 'pct') +
      board('poor_hero', '🌧️ 雪中送炭', b.poor_hero || [], 'drop_poor_share', 'pct') +
      board('whiff', '🪦 白给大师', b.whiff || [], 'whiff_rate', 'pct') +
      board('eco', '💰 eco特专家', b.eco || [], 'eco_frag_rate', 'pct') +
      board('snipe', '🔪 抢人头王', b.snipe || [], 'snipe_rate', 'pct') +
      board('stolen', '🫠 被抢人头王', b.stolen || [], 'stolen_rate', 'pct') +
      board('team_dmg', '🤝 队友伤害王', b.team_dmg || [], 'team_dmg_rpr', '') +
      board('clutch', '🎯 残局孤胆', b.clutch || [], 'clutch_freq', 'pct') +
      board('flags', '🎪 花活集锦', b.flags || [], 'flags_rate', 'pct') +
      board('jame', '🏦 保枪大师', b.jame || [], 'jame_index', 'pct') +
      board('free_pickup', '🤙 舔包王（每回合）', b.free_pickup || [], 'free_pickup_pr', 'pr') +
      board('rebel', '🔥 叛逆赌狗王（胜率含局数）', b.rebel || [], 'rebel_rate', 'pct') +
      board('showoff', '😎 装逼王（eco局沙鹰/鸟狙）', b.showoff || [], 'showoff_rate', 'pct') +
      board('pure_eco', '🥬 纯eco铁公鸡', b.pure_eco || [], 'pure_eco_rate', 'pct');
  }

  var FILTERS = { stack: [], dates: [] };  // empty array = no filter

  // ---- Phase N: 风格星系（谁和谁打得像）----
  var GALAXY = { showTraj: true, last: null };  // V3: 演变轨迹开关
  // script runs at the bottom of <body> — the toggle exists already;
  // DOMContentLoaded has usually fired, so register immediately + guard
  function _bindTrajToggle() {
    var tg = document.getElementById('sm-traj-toggle');
    if (tg && !tg.dataset.trajBound) {
      tg.dataset.trajBound = '1';
      tg.addEventListener('change', function () {
        GALAXY.showTraj = tg.checked;
        if (GALAXY.last) drawGalaxy(GALAXY.last);
      });
    }
  }
  _bindTrajToggle();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _bindTrajToggle);
  }
  function drawGalaxy(sm) {
    var dom = document.getElementById('sm-galaxy');
    if (!dom || !sm || !sm.points || !sm.points.length) {
      if (dom) dom.innerHTML = '<div class="empty-state" style="padding:40px"><div class="empty-title">' +
        esc((sm && sm.note) || '样本不足') + '</div></div>';
      return;
    }
    var pc = sm.pca || {};
    var note = document.getElementById('sm-pc-note');
    if (note) {
      note.textContent = 'PC1+PC2 解释方差 ' +
        Math.round(((pc.var_pc1 || 0) + (pc.var_pc2 || 0)) * 100) + '% · ' +
        (sm.features_used || []).length + ' 个特征入向量 · 剔除常量 ' +
        (sm.features_excluded || []).length + ' 个 · 切簇系数 ' + sm.cut_ratio;
    }
    var pts = sm.points.map(function (p) {
      return {
        name: p.name, value: [p.x, p.y],
        label: p.label, demos: p.demos, kills: p.kills,
        nearest: p.nearest, color: p.color, cluster: p.cluster,
        symbolSize: 10 + Math.min(16, p.demos * 1.8),
      };
    });
    var chart = echarts.init(dom);
    var trajSeries = [];
    if (GALAXY.showTraj && (sm.trajectories || []).length) {
      sm.trajectories.forEach(function (t, ti) {
        if (t.points.length < 2) return;
        trajSeries.push({
          name: t.name + ' 演变', type: 'lines', coordinateSystem: 'cartesian2d',
          polyline: true, silent: true, z: 2,
          lineStyle: { color: 'rgba(196,181,253,.55)', width: 1.6, type: 'dashed' },
          effect: { show: true, period: 5, trailLength: 0, symbol: 'arrow', symbolSize: 5, color: '#c4b5fd' },
          data: [{ coords: t.points.map(function (pt) { return [pt.x, pt.y]; }) }],
          tooltip: { show: false },
        });
        // window dots on top of the polyline
        trajSeries.push({
          name: t.name + ' 节点', type: 'scatter', silent: true, z: 3,
          symbolSize: 5, itemStyle: { color: '#c4b5fd', opacity: 0.9 },
          data: t.points.map(function (pt) { return { value: [pt.x, pt.y],
            label: { show: ti < 2, position: 'right', fontSize: 9, color: '#9aa0b8',
                     formatter: 'W' + pt.window } } }),
        });
      });
    }
    chart.setOption({
      grid: { left: 8, right: 24, top: 16, bottom: 8, containLabel: true },
      tooltip: {
        confine: true,
        formatter: function (q) {
          var p = q.data;
          var html = '<b>' + esc(p.name) + '</b> <span style="color:#636a85">' + p.demos + '场</span><br>' +
            '<span style="color:' + p.color + '">●</span> ' + esc(p.label);
          if (p.nearest) {
            html += '<br>最像: <b>' + esc(p.nearest.name) + '</b> (距离 ' + p.nearest.dist + ')';
          }
          return html;
        },
      },
      xAxis: { type: 'value', name: 'PC1', nameLocation: 'middle', nameGap: 24,
               nameTextStyle: { color: '#9aa0b8', fontSize: 11 },
               splitLine: { show: true, lineStyle: { color: 'rgba(120,120,160,.12)' } },
               axisLabel: { color: '#9aa0b8', fontSize: 10 } },
      yAxis: { type: 'value', name: 'PC2', nameLocation: 'middle', nameGap: 36,
               nameTextStyle: { color: '#9aa0b8', fontSize: 11 },
               splitLine: { show: true, lineStyle: { color: 'rgba(120,120,160,.12)' } },
               axisLabel: { color: '#9aa0b8', fontSize: 10 } },
      series: [{
        type: 'scatter', data: pts,
        label: { show: true, position: 'top', color: '#c4b5fd', fontSize: 11,
                 formatter: function (q) { return q.data.name.length > 10 ? q.data.name.slice(0, 10) + '…' : q.data.name; } },
        itemStyle: { opacity: 0.9, borderColor: 'rgba(0,0,0,.5)', borderWidth: 1,
                     color: function (q) { return q.data.color; } },
      }].concat(trajSeries),
    });
    var box = document.getElementById('sm-portraits');
    if (box) {
      box.innerHTML = sm.points.map(function (p) {
        var near = p.nearest ? '<a href="/player/' + esc(p.steamid) + '">' : '';
        return '<div style="padding:6px 0;border-bottom:1px solid rgba(120,120,160,.12)">' +
          '<div style="font-size:13px"><span style="color:' + p.color + '">●</span> <b>' + esc(p.name) + '</b> ' +
          '<span class="sub">' + p.demos + '场</span></div>' +
          '<div class="sub" style="font-size:12px;margin-top:2px">' + esc(p.label) + '</div>' +
          (p.nearest ? '<div class="sub" style="font-size:11px">最像: ' + esc(p.nearest.name) +
            ' · 距离 ' + p.nearest.dist + '</div>' : '') +
          '</div>';
      }).join('');
    }
  }

  // F2: fetch race guard — responses from superseded requests are dropped
  // (last click wins), and a failed fetch reverts to the LAST successfully
  // applied filter set so the chips never claim a filter that isn't shown.
  var fetchSeq = 0;
  var applied = { stack: [], dates: [] };
  function syncChips() {
    document.querySelectorAll('#fl-stack-chips [data-stack]').forEach(function (b) {
      b.classList.toggle('on', FILTERS.stack.indexOf(b.getAttribute('data-stack')) >= 0);
    });
    document.querySelectorAll('#fl-date-chips [data-date]').forEach(function (b) {
      b.classList.toggle('on', FILTERS.dates.indexOf(b.getAttribute('data-date')) >= 0);
    });
  }
  function fetchAndDraw(after) {
    var qs = [];
    if (FILTERS.stack.length) qs.push('stack=' + FILTERS.stack.join(','));
    if (FILTERS.dates.length) qs.push('dates=' + FILTERS.dates.join(','));
    var seq = ++fetchSeq;
    fetch('/api/funlab.json' + (qs.length ? '?' + qs.join('&') : ''), { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (seq !== fetchSeq) return;  // a newer click superseded us
        applied = { stack: FILTERS.stack.slice(), dates: FILTERS.dates.slice() };
        loadDefs(d); DATA = d; drawBoards(); redrawChart(); if (after) after();
      })
      .catch(function () {
        if (seq !== fetchSeq) return;
        FILTERS.stack = applied.stack.slice();
        FILTERS.dates = applied.dates.slice();
        syncChips();
      });
  }
  // acceptance hook (scripts/accept_buttons.py): filter state introspection
  window.__funlabDebug = {
    state: function () {
      return {
        FILTERS: { stack: FILTERS.stack.slice(), dates: FILTERS.dates.slice() },
        applied: { stack: applied.stack.slice(), dates: applied.dates.slice() },
      };
    },
  };

  var redrawChart = function () {};

  // ---- 口径说明（v5：用户点开即可见每个指标的计算口径）----
  function updateAxisDefs() {
    var box = document.getElementById('fl-axis-def');
    if (!box) return;
    var xk = document.getElementById('fl-x').value;
    var yk = document.getElementById('fl-y').value;
    var line = function (tag, key) {
      var m = DEFS.metrics[key];
      return '<b>' + tag + '</b> ' + (m ? esc(m.label) + '：' + esc(m.formula || '—') : '—');
    };
    box.innerHTML = line('横轴', xk) + '<br>' + line('纵轴', yk);
  }

  function renderDefsPanel() {
    var box = document.getElementById('fl-defs');
    if (!box) return;
    var groups = [
      { name: '经济系（发枪 · 吸血 · eco 个性）', keys: [
        'drop_generosity', 'vulture_rate', 'drop_poor_share', 'drop_profit_rate',
        'drop_waste_rate', 'free_pickup_rate', 'free_pickup_pr',
        'showoff_rate', 'pure_eco_rate', 'rebel_rate', 'rebel_win_rate'] },
      { name: '击杀系', keys: [
        'eco_frag_rate', 'eco_hard_rate', 'whiff_rate', 'snipe_rate', 'stolen_rate',
        'clutch_freq', 'multi_rate', 'avg_dist_m', 'awp_rate'] },
      { name: '花活系（判定列来自 player_death）', keys: [
        'wallbang_rate', 'thrusmoke_rate', 'noscope_rate', 'blind_rate',
        'air_rate', 'knife_rate', 'flags_rate'] },
      { name: '团队系', keys: ['team_dmg_rpr', 'avenged_rate', 'revenge_rate', 'jame_index'] },
    ];
    box.innerHTML = groups.map(function (g) {
      return '<div style="margin-bottom:10px"><div class="sub" style="margin-bottom:4px">' +
        esc(g.name) + '</div>' +
        g.keys.filter(function (k) { return DEFS.metrics[k]; }).map(function (k) {
          var m = DEFS.metrics[k];
          return '<details style="padding:4px 0;border-bottom:1px solid rgba(120,120,160,.12)">' +
            '<summary style="cursor:pointer;font-size:13px">' + esc(m.label) + '</summary>' +
            '<div class="sub" style="font-size:12px;padding:4px 0 0 12px;line-height:1.6">口径: ' +
            esc(m.formula || '—') + (m.note ? '<br>说明: ' + esc(m.note) : '') + '</div></details>';
        }).join('') + '</div>';
    }).join('');
  }

  function init() {
    var selX = document.getElementById('fl-x');
    var selY = document.getElementById('fl-y');
    if (!selX) return;
    // ---- 加载态（用户反馈：冷启动空下拉框像坏了）----
    // 首次进入/服务端预热时 /api/funlab.json 会阻塞几十秒，必须明确告知，
    // 而不是留一组空控件。
    var LOADING = '<span class="sub warm-dots">全库扫描中，稍等片刻自动填充…</span>';
    selX.innerHTML = selY.innerHTML = '<option>加载中…</option>';
    var hint = document.getElementById('fl-axis-def');
    if (hint) hint.innerHTML = LOADING;
    var presetRow0 = document.getElementById('fl-presets');
    if (presetRow0) presetRow0.innerHTML = LOADING;
    var stackRow0 = document.getElementById('fl-stack-chips');
    if (stackRow0) stackRow0.innerHTML = LOADING;
    var dateRow0 = document.getElementById('fl-date-chips');
    if (dateRow0) dateRow0.innerHTML = LOADING;
    var quadrant0 = document.getElementById('fl-quadrant');
    if (quadrant0) quadrant0.innerHTML = '<div class="empty-state" style="padding:60px 0">' +
      '<div class="empty-title">散点图加载中<span class="warm-dots">…</span></div>' +
      '<div>首次进入需要全库扫描（冷启动约 1-3 分钟），完成后自动填充，无需刷新。</div></div>';
    var galaxy0 = document.getElementById('sm-galaxy');
    if (galaxy0) galaxy0.innerHTML = '<div class="empty-state" style="padding:60px 0">' +
      '<div class="empty-title">风格星系加载中<span class="warm-dots">…</span></div></div>';
    // load unfiltered once to discover available stacks/dates
    fetch('/api/funlab.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        loadDefs(d);
        DATA = d;
        if (quadrant0) quadrant0.innerHTML = '';  // 清掉加载占位再挂 canvas
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
        redrawChart = function () { chart.setOption(option(), true); updateAxisDefs(); };
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
        renderDefsPanel();
        redrawChart();
        fetch('/api/style-map.json', { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (sm) { GALAXY.last = sm; drawGalaxy(sm); })
          .catch(function () {
            var g = document.getElementById('sm-galaxy');
            if (g) g.innerHTML = '<div class="empty-state" style="padding:40px"><div class="empty-title">风格星系加载失败</div></div>';
          });
      })
      .catch(function () {
        var hint = document.getElementById('fl-axis-def');
        if (hint) hint.innerHTML = '<span class="sub">数据加载失败 — 请确认服务已启动后刷新页面</span>';
      });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
