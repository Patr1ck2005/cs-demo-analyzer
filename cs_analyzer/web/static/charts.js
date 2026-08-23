// Shared ECharts helpers (Phase E M6): theme init, mount helper, option
// builders for radar / map-position / matrix / bars / trends charts.
// Requires /static/vendor/echarts.min.js + echarts-theme-csa.js loaded first.
(function () {
  'use strict';

  const TOKENS = {
    text: '#e8edf4', muted: '#8b98ab', faint: '#5c6a80',
    line: '#242e42', accent: '#4da3ff', t: '#ffb02e', ct: '#3d9bff',
    ok: '#3ddc97', err: '#ff4d5e',
  };

  const instances = [];

  /** Init a themed ECharts instance on `el` (id or element). */
  function mount(el, option) {
    const dom = typeof el === 'string' ? document.getElementById(el) : el;
    if (!dom || typeof echarts === 'undefined') return null;
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
        splitArea: { areaStyle: { color: ['rgba(36,46,66,.25)', 'rgba(36,46,66,.08)'] } },
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
                `${names[i]}: ${raw[i]} <span style="color:#5c6a80">(${v})</span>`).join('<br/>');
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
      yAxis: { type: 'value', min: 0, max: 1, show: false },
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
      grid: { height: '55%', top: 12, left: 90, right: 20 },
      xAxis: { type: 'category', data: demos, splitArea: { show: true },
               axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: { type: 'category', data: players, splitArea: { show: true } },
      visualMap: {
        min: 0.4, max: 1.3, calculable: true, orient: 'horizontal',
        left: 'center', bottom: 0,
        inRange: { color: ['#1a2130', '#4da3ff', '#ffb02e'] },
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

  window.CSACharts = {
    mount,
    radarOption,
    mountMapChart,
    matrixOption,
    barsOption,
    trendsOption,
    TOKENS,
  };
})();
