// 还债 3/3: career page logic — extracted from the player_career.html inline
// block (match_detail.js/teams.js/system.js precedent; behavior parity is
// the acceptance criterion). Per-player numbers (sid/radar raw/demos)
// arrive via the player-data JSON block — no Jinja inside this file.
(async function () {
  const DATA = JSON.parse(document.getElementById('player-data').textContent);
  const SID = DATA.sid;
  // R1 统计严谨层：生涯卡置信区间（fail-soft —— 加载失败保持占位符静默）
  try {
    const cf = await fetch(`/api/player/${SID}/career-conf.json`)
      .then((r) => { if (!r.ok) throw r.status; return r.json(); });
    const put = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
    const f2 = (x) => (+x).toFixed(2);
    const f1 = (x) => (+x).toFixed(1);
    const line = (c, fmt) => c ? `[${fmt(c.lo)}–${fmt(c.hi)}] · n=${c.n}` + (c.gated ? '（样本不足）' : '') : '—';
    put('conf-rating', '区间 ' + line(cf.rating, f2) + ' · 收缩 ' + f2(cf.rating.shrunk));
    put('conf-adr', '区间 ' + line(cf.adr, f1) + ' · 收缩 ' + f1(cf.adr.shrunk));
    put('conf-kpr', '区间 ' + line(cf.kpr, f2) + ' · 收缩 ' + f2(cf.kpr.shrunk));
    put('conf-hs', '区间 ' + line(cf.hs, f1));
  } catch (e) {
    // S2-V4: failure must settle the placeholders, not leave "…"
    ['conf-rating', 'conf-adr', 'conf-kpr', 'conf-hs'].forEach((id) => {
      const el = document.getElementById(id);
      if (el && el.textContent === '…') el.textContent = '区间不可用';
    });
  }
  // radar: server-injected ranges (RADAR_AXES) — must match the per-demo
  // radar normalization exactly (B4: old hardcoded ranges were wrong)
  const AXES = JSON.parse(document.getElementById('radar-ranges').textContent);
  const norm = (v, lo, hi) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const raw = DATA.raw;
  // raw order matches RADAR_AXES keys; see app.player_career
  const values = raw.map((v, i) => Math.round(norm(v, AXES[i].min, AXES[i].max)));
  const axes = AXES.map((a) => a.label);
  try {
    CSACharts.mount('career-radar', {
      tooltip: { trigger: 'item' },
      radar: {
        indicator: axes.map((n) => ({ name: n, max: 100 })),
        radius: '62%', center: ['50%', '46%'],
        splitArea: { areaStyle: { color: ['rgba(38,41,66,.25)', 'rgba(38,41,66,.08)'] } },
        axisLine: { lineStyle: { color: '#262942' } },
        splitLine: { lineStyle: { color: '#262942' } },
        axisName: { color: '#9aa0b8', fontSize: 11 },
      },
      series: [{
        type: 'radar', symbolSize: 3,
        data: [{ name: '生涯均值', value: values, raw,
                 lineStyle: { width: 2.5 }, areaStyle: { opacity: 0.25 },
                 itemStyle: { color: '#a78bfa' } }],
        tooltip: {
          formatter: (q) => `<b>${q.name}</b><br/>` + q.value.map((v, i) =>
            `${axes[i]}: ${q.raw[i]} <span style="color:#636a85">(${v})</span>`).join('<br/>'),
        },
      }],
    });
  } catch (e) { /* radar stays skeleton */ }

  // trend: Rating/ADR/RWS per demo, chronological by match id (P4)
  // server already orders demos chronologically (match_key)
  const demos = DATA.demos;
  try {
    CSACharts.mount('career-trend', {
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, textStyle: { color: '#9aa0b8', fontSize: 11 } },
      grid: { left: 8, right: 16, top: 20, bottom: 46, containLabel: true },
      xAxis: { type: 'category', data: demos.map((d) => d.name),
               axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: [
        { type: 'value', name: 'Rating', min: 0, scale: true },
        { type: 'value', name: 'ADR / RWS', min: 0 },
      ],
      series: [
        { name: 'Rating', type: 'line', smooth: true, symbolSize: 6,
          data: demos.map((d) => d.rating), lineStyle: { width: 2.5 }, itemStyle: { color: '#a78bfa' } },
        { name: 'ADR', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 5,
          data: demos.map((d) => d.adr), lineStyle: { width: 1.5 }, itemStyle: { color: '#3d9bff' } },
        { name: 'RWS', type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 5,
          data: demos.map((d) => d.rws), lineStyle: { width: 1.5, type: 'dashed' }, itemStyle: { color: '#3ddc97' } },
      ],
    });
  } catch (e) { /* trend stays skeleton */ }

  // P4: per-match deep-dive — wire the orphaned player charts API
  // (heatmap + utility landings + style metrics) via a match picker
  const picker = document.getElementById('career-match-pick');
  if (picker && demos.length) {
    const opts = DATA.demos.map((d) => ({ hash: d.hash, label: d.name }));
    picker.innerHTML = '<option value="">选择场次查看热力图…</option>' +
      opts.map((o, i) => `<option value="${i}">${o.label}</option>`).join('');
    let mounted = null;
    picker.addEventListener('change', async () => {
      const box = document.getElementById('career-heatmap');
      const hint = document.getElementById('career-heatmap-hint');
      if (picker.value === '') { // placeholder row picked — clear, don't load demo 0
        box.classList.remove('chart-loading');
        box.style.backgroundImage = 'none';
        if (hint) hint.style.display = 'flex';
        if (mounted) { mounted.dispose(); mounted = null; }
        return;
      }
      if (hint) hint.style.display = 'none';
      const i = Number(picker.value);
      if (!opts[i]) return;
      box.classList.add('chart-loading');
      try {
        const payload = await fetch(`/api/demo/${opts[i].hash}/player/${SID}/charts.json`)
          .then((r) => { if (!r.ok) throw r.status; return r.json(); });
        box.classList.remove('chart-loading');
        box.style.backgroundImage = payload.heatmap && payload.heatmap.has_map_image
          ? `url("${payload.map_image}")` : 'none';
        if (mounted) mounted.dispose();
        mounted = CSACharts.mountMapChart(box, 'heatmap', payload);
      } catch (e) {
        box.classList.remove('chart-loading');
        box.style.backgroundImage = 'none';
      }
    });
  }

  // R3 枪法科学：跨库向量（aim_peek/wave2 物化；404/无数据时保留占位）
  try {
    const aim = await fetch('/api/aim-science.json')
      .then((r) => { if (!r.ok) throw r.status; return r.json(); });
    const mine = (aim.players || []).find((x) => x.steamid === SID);
    const notes = document.getElementById('aimsci-notes');
    if (notes) notes.textContent = (aim.notes || {}).preaim_def + '；' + (aim.notes || {}).counter_def + '；' + (aim.notes || {}).boundaries;
    const tb = document.getElementById('aimsci-tbody');
    if (tb) {
      const rows = (aim.players || []).slice(0, 10).map((x) => {
        const me = x.steamid === SID;
        const f2 = (v) => v == null ? '—' : (+v).toFixed(2);
        const f1 = (v) => v == null ? '—' : (+v).toFixed(1);
        const pc = (v) => v == null ? '—' : (v * 100).toFixed(0) + '%';
        const dsN = x.duel_stopped_n, dmN = x.duel_moving_n;
        const dsW = dsN ? (100 * x.duel_stopped_wins / dsN).toFixed(0) + '% (' + dsN + ')' : '—';
        const dmW = dmN ? (100 * x.duel_moving_wins / dmN).toFixed(0) + '% (' + dmN + ')' : '—';
        const conf = (c) => c ? ` <span class="csa-conf${c.gated ? ' csa-conf-gated' : ''}">[${pc(c.lo)}–${pc(c.hi)}]</span>` : '';
        return `<tr class="${me ? 'csa-me-row' : ''}">` +
          `<td><a href="/player/${x.steamid}">${CSACommon.esc(x.name)}</a>${me ? ' ⭐' : ''}</td>` +
          `<td class="num">${f1(x.preaim_med_deg)}°</td>` +
          `<td class="num">${pc(x.preaim_lt10_rate)}${conf(x.preaim_lt10_conf)}</td>` +
          `<td class="num">${f2(x.counter_med_s)}s</td>` +
          `<td class="num">${pc(x.counter_fast_rate)}${conf(x.counter_fast_conf)}</td>` +
          `<td class="num">${pc(x.stopped_fire_rate == null ? null : x.stopped_fire_rate)}</td>` +
          `<td class="num">停 ${dsW} · 动 ${dmW}</td></tr>`;
      }).join('');
      tb.innerHTML = rows || '<tr><td colspan="7" class="sub">暂无数据</td></tr>';
    }
  } catch (e) {
    const tb = document.getElementById('aimsci-tbody');
    if (tb) tb.innerHTML = '<tr><td colspan="7" class="sub">枪法科学数据未就绪（后台预热中，稍后刷新）</td></tr>';
  }

  // Round 2 对枪实力：跨库 duelmo memo（duel_peek/wave2 物化；503 时保留占位）
  try {
    const dm = await fetch('/api/duel-model.json')
      .then((r) => { if (!r.ok) throw r.status; return r.json(); });
    const notes = document.getElementById('duelmo-notes');
    if (notes) notes.textContent = (dm.notes || {}).sample_def + '；' + (dm.notes || {}).label_def
      + '；' + (dm.notes || {}).diff_def + '；' + (dm.notes || {}).boundaries;
    const tb = document.getElementById('duelmo-tbody');
    if (tb) {
      const pc = (v) => v == null ? '—' : (v * 100).toFixed(1) + '%';
      const rowHtml = (x) => {
        const me = x.steamid === SID;
        const gated = (x.conf || {}).gated;
        const cls = (me ? 'csa-me-row' : '') + (gated ? ' csa-conf-gated' : '');
        const diffTxt = x.diff == null ? '—'
          : (x.diff >= 0 ? '+' : '') + (x.diff * 100).toFixed(1) + 'pt'
            + (x.diff_shrunk == null ? '' : ` <span class="sub">（收缩 ${(x.diff_shrunk * 100).toFixed(1)}pt）</span>`);
        const conf = x.conf ? ` <span class="csa-conf${gated ? ' csa-conf-gated' : ''}">[${pc(x.conf.lo)}–${pc(x.conf.hi)}]</span>` : '';
        return `<tr class="${cls}">` +
          `<td><a href="/player/${x.steamid}">${CSACommon.esc(x.name)}</a>${me ? ' ⭐' : ''}</td>` +
          `<td class="num">${x.n}${gated ? ' <span class="sub">少</span>' : ''}</td>` +
          `<td class="num">${pc(x.win_rate)}${conf}</td>` +
          `<td class="num">${pc(x.expected_rate)}</td>` +
          `<td class="num">${diffTxt}</td></tr>`;
      };
      const list = dm.players || [];
      let rows = list.slice(0, 12).map(rowHtml).join('');
      // 收尾 V-A1: 对枪块的语义是"我的对枪实力"——榜单 200+ 人，Top 12 之外
      // 的选手此前在自己的生涯页看不到本人行；有榜内数据就追加显示。
      const meIdx = list.findIndex((x) => x.steamid === SID);
      if (meIdx >= 12) {
        rows += '<tr><td colspan="5" class="sub">…</td></tr>' + rowHtml(list[meIdx]);
      }
      tb.innerHTML = rows || '<tr><td colspan="5" class="sub">暂无数据</td></tr>';
    }
  } catch (e) {
    const tb = document.getElementById('duelmo-tbody');
    if (tb) tb.innerHTML = '<tr><td colspan="5" class="sub">对枪模型数据未就绪（后台预热中，稍后刷新）</td></tr>';
  }

  // R5 失利模式：该选手参战队伍的败回合标签分布（fail-soft）
  try {
    const lp = await fetch(`/api/loss-patterns.json?player=${SID}`)
      .then((r) => { if (!r.ok) throw r.status; return r.json(); });
    const tb = document.getElementById('loss-pattern-tbody');
    const TAGS = {
      lost_opening: '掉首口', untraded: '无贸易死', lost_force: '强起失利',
      lost_eco: 'eco失利', utility_deficit: '道具劣势', lost_clutch: '残局失守',
    };
    const pc = (v) => (v * 100).toFixed(0) + '%';
    if (tb) {
      tb.innerHTML = (lp.tags || []).map((t) =>
        `<tr><td><span class="loss-tag t-${t.tag}">${TAGS[t.tag] || t.tag}</span>` +
        `<span class="sub" style="font-size:11px"> ${CSACommon.esc(lp.tag_defs[t.tag] || '')}</span></td>` +
        `<td class="num">${t.count}</td>` +
        `<td class="num">${pc(t.share)} <span class="csa-conf${t.conf.gated ? ' csa-conf-gated' : ''}">[${pc(t.conf.lo)}–${pc(t.conf.hi)}] · n=${t.conf.n}</span></td></tr>`
      ).join('') || '<tr><td colspan="3" class="sub">暂无数据</td></tr>';
    }
  } catch (e) {
    const tb = document.getElementById('loss-pattern-tbody');
    if (tb) tb.innerHTML = '<tr><td colspan="3" class="sub">失利模式数据未就绪（后台预热中）</td></tr>';
  }

  // highlights for this player (M5 payload; explicit failure state)
  try {
    const r = await fetch('/api/highlights.json');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const payload = await r.json();
    const mine = (payload.highlights || []).filter((h) => h.steamid === SID).slice(0, 6);
    const box = document.getElementById('career-highlights');
    if (mine.length) {
      box.innerHTML = mine.map((h) =>
        `<a class="hl-card" href="${h.deep_link}">` +
        `<div class="hl-tier">${h.tier}</div>` +
        `<div class="hl-body"><div class="hl-name">${CSACommon.esc(h.name)}</div>` +
        `<div class="hl-meta">${CSACommon.esc(h.map_name)} · R${h.round} · ${h.kills} 杀</div></div>` +
        `<span class="hl-go">▶ 回放</span></a>`).join('');
    } else {
      box.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-title">该选手暂无高光</div></div>';
    }
  } catch (e) {
    document.getElementById('career-highlights').innerHTML =
      '<div class="empty-state" style="grid-column:1/-1"><div class="empty-title">高光数据加载失败</div></div>';
  }

  document.querySelectorAll('tr.row-link').forEach((tr) => {
    tr.addEventListener('click', (e) => {
      if (e.target.closest('a') || e.target.closest('button')) return;
      location.href = tr.dataset.href;
    });
  });
})();
