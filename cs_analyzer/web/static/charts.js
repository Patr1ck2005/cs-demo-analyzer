// Shared ECharts helpers (Phase E M6): theme init, mount helper, option
// builders for radar / map-position / matrix / bars / trends charts.
// Requires /static/vendor/echarts.min.js + echarts-theme-csa.js loaded first.
(function () {
  'use strict';

  const TOKENS = {
    text: '#eceaf6', muted: '#9aa0b8', faint: '#636a85',
    line: '#262942', accent: '#a78bfa', t: '#ffb02e', ct: '#3d9bff',
    ok: '#3ddc97', err: '#ff4d5e',
  };

  const instances = [];

  /** Init a themed ECharts instance on `el` (id or element). */
  function mount(el, option) {
    const dom = typeof el === 'string' ? document.getElementById(el) : el;
    if (!dom || typeof echarts === 'undefined') return null;
    dom.classList.remove('chart-loading'); // drop the skeleton placeholder
    const chart = echarts.init(dom, 'csa');
    chart.setOption(option);
    instances.push(chart);
    return chart;
  }

  window.addEventListener('resize', () => instances.forEach((c) => c.resize()));

  // ---- radar: per-demo player comparison (six axes, 0-100 normalized) ----
  function radarOption(payload, maxSeries) {
    const series = payload.series.slice(0, maxSeries || 10);
    return {
      tooltip: { trigger: 'item' },
      legend: { type: 'scroll', bottom: 0, textStyle: { color: TOKENS.muted, fontSize: 11 } },
      radar: {
        indicator: payload.indicators,
        radius: '62%',
        center: ['50%', '46%'],
        splitArea: { areaStyle: { color: ['rgba(38,41,66,.25)', 'rgba(38,41,66,.08)'] } },
        axisLine: { lineStyle: { color: TOKENS.line } },
        splitLine: { lineStyle: { color: TOKENS.line } },
        axisName: { color: TOKENS.muted, fontSize: 11 },
      },
      series: [
        {
          type: 'radar',
          symbolSize: 3,
          data: series.map((s, i) => ({
            name: s.name,
            value: s.values,
            raw: s.raw,
            lineStyle: { width: i === 0 ? 2.5 : 1.2, opacity: i === 0 ? 1 : 0.55 },
            areaStyle: { opacity: i === 0 ? 0.25 : 0.08 },
            itemStyle: { color: i === 0 ? TOKENS.accent : undefined },
          })),
          tooltip: {
            formatter: (p) => {
              const raw = p.raw || [];
              const names = ['KPR', '存活率', 'ADR', '爆头率%', '首杀/回合', 'Rating'];
              return `<b>${p.name}</b><br/>` + p.value.map((v, i) =>
                `${names[i]}: ${raw[i]} <span style="color:#636a85">(${v})</span>`).join('<br/>');
            },
          },
        },
      ],
    };
  }

  // ---- map-position charts: scatter over the radar PNG (CSS background) ----
  // Server sends [0..1]-normalized points; the container carries the radar
  // image as a CSS background so ECharts only draws hidden-axis scatter.
  function mapChartOption(kind, payload) {
    let series = [];
    if (kind === 'heatmap') {
      series = [{
        name: '位置采样',
        type: 'scatter',
        data: (payload.heatmap && payload.heatmap.points) || [],
        symbolSize: 7,
        itemStyle: { color: 'rgba(255,176,46,.5)', borderColor: 'rgba(0,0,0,.5)', borderWidth: 1 },
        large: true,
      }];
    } else {
      const colors = { smoke: '#9E9E9E', flash: '#FFFFFF', he: '#FF8800', molly: '#FF6600' };
      series = ((payload.utility && payload.utility.kinds) || []).map((k) => ({
        name: k.label,
        type: 'scatter',
        data: k.points,
        symbolSize: 8,
        itemStyle: {
          color: colors[k.kind] || '#ffffff', opacity: 0.8,
          borderColor: 'rgba(0,0,0,.5)', borderWidth: 1,
        },
      }));
    }
    return {
      tooltip: { trigger: 'item' },
      legend: kind === 'utility'
        ? { bottom: 0, textStyle: { color: TOKENS.muted, fontSize: 11 } }
        : undefined,
      grid: { left: 6, right: 6, top: 6, bottom: kind === 'utility' ? 32 : 6 },
      xAxis: { type: 'value', min: 0, max: 1, show: false },
      // points are image-space (0 = top): invert the axis so north stays up
      yAxis: { type: 'value', min: 0, max: 1, show: false, inverse: true },
      series,
    };
  }

  /** Mount a map-position chart with the radar PNG as the container background. */
  function mountMapChart(el, kind, payload) {
    const dom = typeof el === 'string' ? document.getElementById(el) : el;
    if (!dom) return null;
    if (payload.heatmap && payload.heatmap.has_map_image && payload.map_image) {
      dom.style.backgroundImage = `url("${payload.map_image}")`;
    }
    return mount(dom, mapChartOption(kind, payload));
  }

  /** Mount the opening-routes chart with the radar PNG background.
   * side: 'T' | 'CT' (P3) — reads payload.sides[side], falling back to the
   * legacy top-level keys when `sides` is absent. */
  function mountRoutesChart(el, payload, side) {
    const dom = typeof el === 'string' ? document.getElementById(el) : el;
    if (!dom) return null;
    if (payload.map_image) dom.style.backgroundImage = `url("${payload.map_image}")`;
    const pack = (side && payload.sides && payload.sides[side])
      || { routes: payload.routes, k: payload.k };
    // drop a stale legend from a previous mount
    if (dom.parentElement) {
      const old = dom.parentElement.querySelector('.routes-legend');
      if (old) old.remove();
    }
    const chart = mount(dom, routesOption({ routes: pack.routes || [] }));
    // HTML legend below the square (kept outside so the grid == image box)
    const palette = ['#ffb02e', '#3d9bff', '#3ddc97', '#ff4d5e'];
    const routes = pack.routes || [];
    if (dom.parentElement && routes.length) {
      const legend = document.createElement('div');
      legend.className = 'routes-legend';
      legend.innerHTML = routes.map((r, i) =>
        `<span><i style="background:${palette[i % palette.length]}"></i>` +
        `路线 ${i + 1} · ${(r.share * 100).toFixed(0)}% · R${r.rounds.join('/R')}</span>`).join('');
      dom.parentElement.appendChild(legend);
    }
    return chart;
  }

  // ---- aggregate: player × demo Rating matrix ----
  function matrixOption(payload) {
    const players = payload.matrix.players;
    const demos = payload.matrix.demos;
    const data = [];
    payload.matrix.values.forEach((row, i) => {
      row.forEach((v, j) => { if (v != null) data.push([j, i, v]); });
    });
    return {
      tooltip: {
        position: 'top',
        formatter: (p) =>
          `${players[p.value[1]]} @ ${demos[p.value[0]]}<br/>Rating: <b>${p.value[2]}</b>`,
      },
      grid: { height: '55%', top: 12, left: 8, right: 20, containLabel: true },
      xAxis: { type: 'category', data: demos, splitArea: { show: true },
               axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: { type: 'category', data: players, splitArea: { show: true } },
      visualMap: {
        min: 0.4, max: 1.3, calculable: true, orient: 'horizontal',
        left: 'center', bottom: 0,
        inRange: { color: ['#16182a', '#a78bfa', '#ffb02e'] },
      },
      series: [{ type: 'heatmap', data, label: { show: true, fontSize: 9, color: TOKENS.text } }],
    };
  }

  // ---- aggregate: per-player average bars ----
  function barsOption(payload) {
    return {
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, textStyle: { color: TOKENS.muted, fontSize: 11 } },
      grid: { left: 8, right: 16, top: 20, bottom: 46, containLabel: true },
      xAxis: { type: 'category', data: payload.bars.names,
               axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: [
        { type: 'value', name: 'KPR', min: 0 },
        { type: 'value', name: 'ADR', min: 0 },
      ],
      series: [
        { name: '场均KPR', type: 'bar', data: payload.bars.kpr, barMaxWidth: 26 },
        { name: '场均ADR', type: 'bar', yAxisIndex: 1, data: payload.bars.adr, barMaxWidth: 26 },
        { name: '场均Rating', type: 'line', data: payload.bars.rating, smooth: true, symbolSize: 5 },
      ],
    };
  }

  // ---- aggregate: per-demo T-side score trend ----
  function trendsOption(payload) {
    const series = payload.trends.map((d) => ({
      name: d.name,
      type: 'line',
      data: (d.trend || []).map((t) => [t.round, t.t_score]),
      smooth: true,
      symbolSize: 4,
      lineStyle: { width: 1.5 },
    }));
    return {
      tooltip: { trigger: 'item' },
      legend: { type: 'scroll', bottom: 0, textStyle: { color: TOKENS.muted, fontSize: 10 } },
      grid: { left: 8, right: 16, top: 20, bottom: 46, containLabel: true },
      xAxis: { type: 'value', name: '回合', minInterval: 1 },
      yAxis: { type: 'value', name: 'T 方得分' },
      series,
    };
  }

  // ---- Phase F M7/M8: advanced analysis charts ----

  // duel matrix: players × players win-rate heatmap (cells < min_duels greyed)
  function duelsOption(payload) {
    const players = payload.players;
    const data = payload.cells.map((c) => ({
      value: [c[0], c[1], c[2]], k: c[3], d: c[4], enough: c[5],
    }));
    return {
      tooltip: {
        position: 'top',
        formatter: (p) => {
          const row = players[p.value[1]], col = players[p.value[0]];
          return `${row} vs ${col}<br/>胜率 <b>${(p.value[2] * 100).toFixed(0)}%</b> ` +
            `(${p.data.k}杀 / ${p.data.d}死)${p.data.enough ? '' : ' · 样本不足'}`;
        },
      },
      grid: { height: '60%', top: 12, left: 100, right: 20 },
      xAxis: { type: 'category', data: players, splitArea: { show: true },
               axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: { type: 'category', data: players, splitArea: { show: true } },
      visualMap: {
        min: 0, max: 1, calculable: true, orient: 'horizontal',
        left: 'center', bottom: 0,
        inRange: { color: ['#3d9bff', '#16182a', '#ffb02e'] },
        formatter: (v) => (v * 100).toFixed(0) + '%',
      },
      series: [{
        type: 'heatmap', data,
        label: { show: true, fontSize: 9, color: TOKENS.text,
                 formatter: (p) => (p.data.enough ? (p.value[2] * 100).toFixed(0) : '·') },
      }],
    };
  }

  // economy: per-round team spend bars colored BY BUY CLASS (P1) — the
  // payload's buy/win_by_buy/loss_streaks were fetched but never drawn before
  function economyOption(payload) {
    const buyColor = { eco: '#9aa0b8', force: '#ffb02e', full: '#3ddc97' };
    const buyZh = { eco: 'eco', force: '强起', full: '长枪' };
    const mk = (side) => ({
      name: side === 'T' ? 'T 消费' : 'CT 消费',
      type: 'bar',
      data: payload.series[side].spend.map((v, i) => {
        const buy = payload.series[side].buy[i];
        return { value: v, buy: buy || '' };
      }),
      itemStyle: { color: side === 'T' ? '#ffb02e' : '#3d9bff' },
      barMaxWidth: 14,
    });
    return {
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          let out = params[0].axisValue + ' 回合';
          for (const p of params) {
            const row = payload.rounds_info && payload.rounds_info[p.dataIndex];
            const won = row ? (row.winner === p.seriesName.slice(0, 1) ? ' ✓' : '') : '';
            out += `<br/>${p.seriesName}: $${p.value == null ? '-' : p.value}`;
            if (p.data.buy) out += ` <span style="color:#636a85">(${buyZh[p.data.buy] || p.data.buy})</span>${won}`;
          }
          if (payload.loss_streaks) {
            out += `<br/><span style="color:#636a85">最长连败 T:${payload.loss_streaks.T ?? '-'} · CT:${payload.loss_streaks.CT ?? '-'}</span>`;
          }
          return out;
        },
      },
      legend: { bottom: 0, textStyle: { color: TOKENS.muted, fontSize: 11 } },
      grid: { left: 8, right: 16, top: 20, bottom: 46, containLabel: true },
      xAxis: { type: 'category', data: payload.rounds.map((r) => 'R' + r),
               axisLabel: { color: (i) => undefined } },
      yAxis: { type: 'value', name: '队伍消费 $' },
      series: [mk('T'), mk('CT')],
    };
  }

  // P1: win rate per buy class, grouped bars per side
  function economyWinByBuyOption(payload) {
    const classes = ['eco', 'force', 'full'];
    const zh = { eco: 'eco', force: '强起', full: '长枪' };
    const sides = ['T', 'CT'];
    const series = sides.map((side, si) => ({
      name: side,
      type: 'bar',
      barMaxWidth: 18,
      data: classes.map((c) => {
        const cell = (payload.win_by_buy || {})[side] || {};
        const d = cell[c];
        return d && d.n ? {
          value: Math.round(d.win_rate * 100),
          n: d.n, wins: d.wins,
        } : { value: 0, n: 0 };
      }),
      itemStyle: { color: si === 0 ? TOKENS.t : TOKENS.ct },
    }));
    return {
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const c = classes[params[0].dataIndex];
          return `${zh[c]}局<br/>` + params.map((p) =>
            `${p.seriesName}: <b>${p.value}%</b> (${p.data.wins ?? 0}/${p.data.n})`).join('<br/>');
        },
      },
      legend: { bottom: 0, textStyle: { color: TOKENS.muted, fontSize: 11 } },
      grid: { left: 8, right: 16, top: 20, bottom: 46, containLabel: true },
      xAxis: { type: 'category', data: classes.map((c) => zh[c]) },
      yAxis: { type: 'value', name: '胜率 %', max: 100 },
      series,
    };
  }

  // utility: flash value ranking bars (horizontal)
  function utilityFlashOption(payload) {
    const f = payload.flashers.slice(0, 10);
    return {
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const p = params[0];
          const row = payload.flashers[p.dataIndex];
          return `${row.name}<br/>致盲敌人 <b>${row.enemy_blind_s}s</b> · 误伤队友 ${row.friendly_blind_s}s` +
            `<br/>投掷 ${row.throws} 次 · 场均价值 ${row.value_per_throw}s` +
            (row.flash_assists ? `<br/>闪光助攻 <b>${row.flash_assists}</b>` : '');
        },
      },
      grid: { left: 8, right: 30, top: 10, bottom: 24, containLabel: true },
      xAxis: { type: 'value', name: '闪光价值 (s)' },
      yAxis: { type: 'category', data: f.map((x) => x.name).reverse(),
               axisLabel: { fontSize: 10 } },
      series: [{
        type: 'bar',
        data: f.map((x) => x.value).reverse(),
        itemStyle: { color: '#eceaf6' },
        barMaxWidth: 16,
        label: { show: true, position: 'right', fontSize: 9, color: TOKENS.muted,
                 formatter: (p) => p.value.toFixed(1) + 's' },
      }],
    };
  }

  // P2: smoke denial ranking — computed since Phase F but never rendered
  function utilitySmokeOption(payload) {
    const rows = (payload.smoke || []).filter((r) => r.smoke_kills || r.smoke_deaths)
      .slice(0, 10);
    if (!rows.length) return null;
    return {
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const row = rows[params[0].dataIndex];
          return `${row.name}<br/>烟中击杀 <b>${row.smoke_kills}</b> · 烟中死亡 ${row.smoke_deaths}`;
        },
      },
      grid: { left: 8, right: 30, top: 10, bottom: 24, containLabel: true },
      xAxis: { type: 'value', minInterval: 1 },
      yAxis: { type: 'category', data: rows.map((x) => x.name).reverse(),
               axisLabel: { fontSize: 10 } },
      series: [
        { name: '烟中击杀', type: 'bar',
          data: rows.map((x) => x.smoke_kills).reverse(),
          itemStyle: { color: TOKENS.ok }, barMaxWidth: 12,
          label: { show: true, position: 'right', fontSize: 9, color: TOKENS.muted } },
        { name: '烟中死亡', type: 'bar',
          data: rows.map((x) => -x.smoke_deaths).reverse(),
          itemStyle: { color: TOKENS.err }, barMaxWidth: 12 },
      ],
    };
  }

  // opening routes: centroid polylines over the radar background
  // (image-space coords, same inverse-y convention as the heatmap; the grid
  // must coincide with the background image box, so zero padding + HTML legend)
  function routesOption(payload) {
    const palette = ['#ffb02e', '#3d9bff', '#3ddc97', '#ff4d5e'];
    const routes = payload.routes || [];
    const series = routes.map((r, i) => ({
      name: `路线 ${i + 1}`,
      type: 'lines',
      coordinateSystem: 'cartesian2d',
      polyline: true,
      data: [{ coords: r.route.map((p) => [p[0], p[1]]) }],
      lineStyle: { color: palette[i % palette.length], width: 4, opacity: 0.9,
                   curveness: 0, cap: 'round' },
      symbol: ['none', 'arrow'],
      symbolSize: 10,
    }));
    return {
      tooltip: { trigger: 'item' },
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: 'value', min: 0, max: 1, show: false },
      yAxis: { type: 'value', min: 0, max: 1, show: false, inverse: true },
      series,
    };
  }

  window.CSACharts = {
    mount,
    radarOption,
    mountMapChart,
    matrixOption,
    barsOption,
    trendsOption,
    duelsOption,
    economyOption,
    economyWinByBuyOption,
    utilityFlashOption,
    utilitySmokeOption,
    routesOption,
    mountRoutesChart,
    TOKENS,
  };
})();
