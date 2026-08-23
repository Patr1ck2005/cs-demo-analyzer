// CSA dark theme for vendored Apache ECharts (Phase E M6).
// Colors mirror the design tokens in style.css (:root).
(function () {
  'use strict';
  if (typeof echarts === 'undefined') return;
  echarts.registerTheme('csa', {
    color: ['#4da3ff', '#ffb02e', '#3d9bff', '#3ddc97', '#ff4d5e', '#b48cff',
            '#00c4b3', '#ff8f5e', '#8b98ab', '#e8edf4'],
    backgroundColor: 'transparent',
    textStyle: { color: '#8b98ab', fontFamily: 'Inter, "Segoe UI", "Microsoft YaHei", sans-serif' },
    title: { textStyle: { color: '#e8edf4' } },
    legend: { textStyle: { color: '#8b98ab' } },
    tooltip: {
      backgroundColor: '#121722', borderColor: '#242e42', textStyle: { color: '#e8edf4' },
      extraCssText: 'box-shadow: 0 2px 10px rgba(0,0,0,.35);',
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: '#242e42' } },
      axisTick: { show: false },
      axisLabel: { color: '#8b98ab' },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#8b98ab' },
      splitLine: { lineStyle: { color: 'rgba(36,46,66,.6)' } },
      splitArea: { show: false },
    },
  });
})();
