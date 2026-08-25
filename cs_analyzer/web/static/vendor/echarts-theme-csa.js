// CSA dark theme for vendored Apache ECharts (Phase G "Violet Observatory").
// Colors mirror the design tokens in style.css (:root).
(function () {
  'use strict';
  if (typeof echarts === 'undefined') return;
  echarts.registerTheme('csa', {
    color: ['#a78bfa', '#ffb02e', '#3d9bff', '#3ddc97', '#ff4d5e', '#22d3ee',
            '#f472b6', '#facc15', '#94a3b8', '#eceaf6'],
    backgroundColor: 'transparent',
    textStyle: { color: '#9aa0b8', fontFamily: 'Inter, "Segoe UI", "Microsoft YaHei", sans-serif' },
    title: { textStyle: { color: '#eceaf6' } },
    legend: { textStyle: { color: '#9aa0b8' } },
    tooltip: {
      backgroundColor: 'rgba(16, 17, 29, .96)', borderColor: '#363a5e',
      borderWidth: 1, padding: [8, 12],
      textStyle: { color: '#eceaf6' },
      extraCssText: 'box-shadow: 0 10px 32px rgba(0,0,0,.55); border-radius: 8px; backdrop-filter: blur(6px);',
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: '#262942' } },
      axisTick: { show: false },
      axisLabel: { color: '#9aa0b8' },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#9aa0b8' },
      splitLine: { lineStyle: { color: 'rgba(38, 41, 66, .6)' } },
      splitArea: { show: false },
    },
    dataView: { backgroundColor: '#10111d', textColor: '#eceaf6' },
  });
})();
