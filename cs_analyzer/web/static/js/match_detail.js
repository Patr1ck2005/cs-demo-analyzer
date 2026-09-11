// M1 复盘教练线: match detail page logic — extracted verbatim from the
// match_detail.html inline block (teams.js precedent, R3-F4; behavior
// parity is the acceptance criterion). Demo hash arrives via
// <script src=... data-hash="{{ demo.hash }}"> — no Jinja inside this file.
(async function () {
  const H = (document.currentScript && document.currentScript.dataset.hash) || '';
  const fetchJson = (url) => fetch(url).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));

  // ---- tab engine: ?tab= is the source of truth; panels lazily fetch ----
  // review (M1) is pure SSR — its loader is a deliberate no-op.
  const TABS = ['overview', 'kills', 'economy', 'utility', 'routes', 'tactics', 'review'];
  let routesPayload = null;
  const loaders = {
    overview: async () => {
      try {
        const payload = await fetchJson(`/api/demo/${H}/charts.json`);
        if (payload.series && payload.series.length) {
          CSACharts.mount('radar-chart', CSACharts.radarOption(payload, 10));
        } else { hideSkeleton('radar-chart'); }
      } catch (e) { hideSkeleton('radar-chart'); }
      loadMatchHighlights();
      loadWinProbability();
      loadLossAttribution();
    },
    kills: async () => {
      mountPayloadChart('duels-chart', (p) => p.cells.length ? CSACharts.duelsOption(p) : null);
      mountPayloadChart('weapon-mix-chart', weaponMixOption);
      mountPayloadChart('hitgroups-chart', hitgroupsOption);
    },
    economy: async () => {
      try {
        const p = await fetchJson(`/api/demo/${H}/analysis/economy.json`);
        const el = document.getElementById('economy-chart');
        el.classList.remove('chart-loading');
        if (p.rounds && p.rounds.length) CSACharts.mount(el, CSACharts.economyOption(p));
        if (p.win_by_buy) CSACharts.mount('winbybuy-chart', CSACharts.economyWinByBuyOption(p));
        hideSkeleton('winbybuy-chart');
        if (p.loss_streaks) {
          document.getElementById('eco-streaks').textContent =
            `最长连败 — T: ${p.loss_streaks.T ?? '-'} · CT: ${p.loss_streaks.CT ?? '-'}`;
        }
        if (p.thresholds) {
          const th = p.thresholds;
          document.getElementById('eco-thresholds').textContent =
            `eco <$${th.eco_max} · 强起 <$${th.force_max} · 长枪 ≥$${th.force_max}（队伍均消）`;
        }
        loadEvTable();
      } catch (e) { hideSkeleton('economy-chart'); hideSkeleton('winbybuy-chart'); }
    },
    utility: async () => {
      try {
        const p = await fetchJson(`/api/demo/${H}/analysis/utility.json`);
        const el = document.getElementById('utility-chart');
        el.classList.remove('chart-loading');
        if (p.flashers && p.flashers.length) CSACharts.mount(el, CSACharts.utilityFlashOption(p));
        const smokeOpt = CSACharts.utilitySmokeOption(p);
        const smokeEl = document.getElementById('smoke-chart');
        smokeEl.classList.remove('chart-loading');
        if (smokeOpt) CSACharts.mount(smokeEl, smokeOpt);
        else smokeEl.innerHTML =
          '<div class="empty-state"><div class="empty-title">本场没有烟中击杀</div></div>';
      } catch (e) { hideSkeleton('utility-chart'); hideSkeleton('smoke-chart'); }
    },
    routes: async () => {
      try {
        routesPayload = await fetchJson(`/api/demo/${H}/analysis/routes.json`);
        const el = document.getElementById('routes-chart');
        el.classList.remove('chart-loading');
        renderRoutes('T');
        loadPostplant();
      } catch (e) {
        const el = document.getElementById('routes-chart');
        if (el) el.classList.remove('chart-loading');
      }
    },
    tactics: async () => { loadAim(); loadWeaponSplits(); loadWeaponTimeline(); },
  };
  function renderRoutes(side) {
    if (!routesPayload) return;
    CSACharts.mountRoutesChart('routes-chart', routesPayload, side);
    const pack = routesPayload.sides && routesPayload.sides[side];
    if (!pack || !pack.routes.length) {
      const wrap = document.querySelector('#routes-chart').parentElement;
      let empty = wrap.querySelector('.routes-empty');
      if (!empty) {
        empty = document.createElement('div');
        empty.className = 'sub routes-empty';
        empty.textContent = '该方样本不足（少于 3 个有效回合），无法聚类';
        wrap.appendChild(empty);
      }
    }
  }
  document.querySelectorAll('.route-side').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.route-side').forEach((b) =>
        b.classList.toggle('on', b === btn));
      renderRoutes(btn.dataset.side);
    });
  });
  function loadPostplant() {
    fetchJson(`/api/demo/${H}/analysis/postplant.json`)
      .then((p) => {
        const box = document.getElementById('postplant-cards');
        const s = p.summary || {};
        if (!s.planted_rounds) {
          box.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-title">本场没有下包回合</div></div>';
          return;
        }
        const card = (label, val, sub) =>
          `<div class="stat-card"><div class="stat-label">${label}</div>` +
          `<div class="stat-value">${val}</div><div class="sub">${sub || ''}</div></div>`;
        box.innerHTML =
          card('下包回合', s.planted_rounds, '') +
          card('T 守包成功率', s.t_hold_rate != null ? Math.round(s.t_hold_rate * 100) + '%' : '-', `CT 拆弹 ${s.defusal_count ?? 0} 次`) +
          card('CT 拆弹率', s.defusal_rate != null ? Math.round(s.defusal_rate * 100) + '%' : '',
               `尝试 ${s.defuse_attempts ?? 0} · 放弃 ${s.defuse_aborts ?? 0}`) +
          card('平均拆弹用时', s.avg_time_to_defuse_s != null ? s.avg_time_to_defuse_s + 's' : '-', '');
      })
      .catch(() => {
        document.getElementById('postplant-cards').innerHTML =
          '<div class="empty-state" style="grid-column:1/-1"><div class="empty-title">数据不可用</div></div>';
      });
  }
  async function loadAim() {
    const tb = document.querySelector('#aim-table tbody');
    try {
      const p = await fetchJson(`/api/demo/${H}/analysis/aim.json`);
      const rows = p.players || [];
      tb.innerHTML = rows.length ? rows.map((r) =>
        `<tr><td>${CSACommon.esc(r.name)}</td><td class="num">${r.shots_fired}</td>` +
        `<td class="num">${r.fire_kills}</td><td class="num">${(r.fire_kill_rate * 100).toFixed(1)}%</td>` +
        `<td class="num">${r.walk_share != null ? (r.walk_share * 100).toFixed(0) + '%' : '-'}</td>` +
        `<td class="num">${r.scope_share != null ? (r.scope_share * 100).toFixed(0) + '%' : '-'}</td>` +
        `<td class="num">${r.crouch_share != null ? (r.crouch_share * 100).toFixed(0) + '%' : '-'}</td>` +
        `<td class="num">${r.avg_first_shot_s != null ? r.avg_first_shot_s : '-'}</td></tr>`).join('')
        : '<tr><td colspan="8" class="sub">无开火数据</td></tr>';
    } catch (e) { tb.innerHTML = '<tr><td colspan="8" class="sub">数据不可用</td></tr>'; }
  }
  const WCAT = [['sniper', '狙击'], ['rifle', '步枪'], ['pistol', '手枪'],
                ['smg', '冲锋枪'], ['heavy', '重火力'], ['knife', '刀'], ['grenade', '投掷物']];
  async function loadWeaponSplits() {
    const tb = document.querySelector('#weapons-table tbody');
    try {
      const p = await fetchJson(`/api/demo/${H}/analysis/weapons.json`);
      const rows = p.players || [];
      tb.innerHTML = rows.length ? rows.map((r) => {
        const cells = WCAT.map(([c]) =>
          `<td class="num">${r.kills_by_category[c] || 0}${r.deaths_by_category[c] ? `<span class="sub">/${r.deaths_by_category[c]}</span>` : ''}</td>`).join('');
        const tops = (r.top_weapons || []).map((w) => w.weapon).join(' · ');
        return `<tr><td>${CSACommon.esc(r.name)}</td>${cells}<td class="sub" style="text-align:left">${CSACommon.esc(tops)}</td></tr>`;
      }).join('') : '<tr><td colspan="9" class="sub">无击杀数据</td></tr>';
    } catch (e) { tb.innerHTML = '<tr><td colspan="9" class="sub">数据不可用</td></tr>'; }
  }
  // weapon-mix donut + hitgroups stacked bars (both from kill_context/hitgroups)
  async function loadWeaponTimeline() {
    const el = document.getElementById('weapon-timeline-chart');
    try {
      const p = await fetchJson(`/api/demo/${H}/analysis/weapon_timeline.json`);
      const players = (p.players || []).filter((x) => x.holds.length);
      if (!players.length) { hideSkeleton('weapon-timeline-chart'); return; }
      const WZH = { ak47: 'AK-47', m4a4: 'M4A4', m4a1: 'M4A1', usp: 'USP-S', glock: '格洛克',
                    deagle: '沙鹰', awp: 'AWP', knife: '刀', c4: 'C4', inferno: '燃烧弹',
                    smokegrenade: '烟雾弹', flashbang: '闪光弹', hegrenade: '手雷',
                    mp9: 'MP9', mac10: 'MAC-10', galil: '加利尔', famas: '法玛斯',
                    aug: 'AUG', sg553: 'SG553', m249: 'M249', negev: '内格夫',
                    p90: 'P90', ump45: 'UMP-45', p250: 'P250', tec9: 'Tec-9', fiveseven: 'FN57' };
      const wname = (w) => WZH[w] || w;
      const playerSel = (name) => encodeURIComponent(name);
      const weaponColor = (n) => {
        let hash = 0; for (let i = 0; i < n.length; i++) hash = (hash * 31 + n.charCodeAt(i)) | 0;
        const hue = Math.abs(hash) % 360;
        return `hsl(${hue}, 60%, 62%)`;
      };
      const option = {
        tooltip: {
          formatter: (q) => {
            const d = q.data;
            if (d == null || d.weap == null) return q.seriesName;
            return `${q.seriesName}<br/>${wname(d.weap)} · ${d.secs}s` +
                   (d.kills ? ` · <b>${d.kills} 杀</b>` : '') + `<br/>回合 ${d.round}`;
          },
        },
        legend: { show: false },
        grid: { left: 8, right: 16, top: 20, bottom: 30, containLabel: true },
        xAxis: { type: 'value', name: '回合', min: 0.5, max: (p.rounds || 24) + 0.5,
                 axisLabel: { color: '#9aa0b8' }, splitLine: { lineStyle: { color: '#222438' } } },
        yAxis: { type: 'category', inverse: true, data: players.map((x) => x.name),
                 axisLabel: { color: '#c9cede', fontSize: 11 }, axisTick: { show: false } },
        series: players.map((pl, pIdx) => ({
          name: pl.name, type: 'custom', renderItem: renderTimelineItem,
          encode: { x: [1, 2], y: 0 }, clip: true,
          data: (function () {
            const out = [];
            const roundsTotal = p.rounds || 1;
            for (let r = 1; r <= roundsTotal; r++) {
              const w = pl.round_equips[String(r)];
              if (!w) continue;
              const h = pl.holds.find((x) => x.weapon === w);
              out.push({ value: [pIdx, r - 0.4, r + 0.4], weap: w,
                         secs: h ? h.seconds : 0, kills: h ? h.kills : 0, round: r,
                         itemStyle: { color: weaponColor(w) } });
            }
            return out;
          })(),
        })),
      };
      function renderTimelineItem(_params, api) {
        const yIdx = api.value(0);
        const start = api.coord([api.value(1), yIdx]);
        const end = api.coord([api.value(2), yIdx]);
        const h = Math.min(api.size([0, 1])[1] * 0.62, 22);
        if (!start || !end) return;
        return {
          type: 'rect',
          shape: { x: start[0], y: start[1] - h / 2,
                   width: Math.max(end[0] - start[0], 2), height: h },
          style: api.style(),
        };
      }
      CSACharts.mount('weapon-timeline-chart', option);
    } catch (e) { hideSkeleton('weapon-timeline-chart'); }
  }
  const EV_BUY = { eco: 'eco', force: '强起', full: '长枪' };
  const EV_BIN = { losing: '落后', even: '持平', winning: '领先' };
  async function loadEvTable() {
    const tb = document.querySelector('#ev-table tbody');
    try {
      const p = await fetchJson(`/api/ev/table.json`);
      const noteEl = document.getElementById('ev-note');
      if (noteEl) {
        noteEl.textContent = 'V2 · ' + (p.note || '') + ` · 本表 N=${(p.total_rounds || 0)}`;
      }
      const rows = (p.cells || []).filter((c) => c.n > 0);
      tb.innerHTML = rows.length ? rows.map((c) => {
        const wr = c.win_rate != null
          ? `<span class="${c.win_rate >= 0.5 ? 'pos' : ''}">${(c.win_rate * 100).toFixed(0)}%</span>`
          : `<span class="sub">灰</span>`;
        const sv = c.survived != null ? c.survived.toFixed(2) : '—';
        return `<tr><td>${EV_BUY[c.buy] || c.buy}</td>` +
          `<td><span class="badge ${c.side === 'T' ? 't' : 'ct'}">${c.side}</span></td>` +
          `<td>${EV_BIN[c.score_bin] || c.score_bin}</td>` +
          `<td>${c.streak_bin === 'cold' ? '连败≥2' : '无'}</td>` +
          `<td class="num">${c.n}</td><td class="num">${wr}</td><td class="num">${sv}</td></tr>`;
      }).join('') : '<tr><td colspan="7" class="sub">暂无数据</td></tr>';
    } catch (e) { tb.innerHTML = '<tr><td colspan="7" class="sub">数据不可用</td></tr>'; }
  }
  async function loadWinProbability() {    const note = document.getElementById('winprob-note');
    try {
      const p = await fetchJson(`/api/demo/${H}/analysis/win_probability.json`);
      const srcTag = p.curve_source === 'oos' ? 'V2·跨场' : 'V2·单场';
      if (note && p.note) note.textContent = srcTag + ' · ' + p.note;
      const rounds = p.rounds || [];
      if (!rounds.length) { hideSkeleton('winprob-chart'); return; }
      const series = [];
      const markers = [];
      for (const rnd of rounds) {
        if (!rnd.length) continue;
        const r = rnd[0].round;
        const xs = rnd.map((s) => s.tick);
        const ys = rnd.map((s) => Math.round(s.p_win * 1000) / 10);
        series.push({ name: `R${r}`, type: 'line', showSymbol: false, smooth: true,
                      data: xs.map((x, i) => [x, ys[i]]),
                      lineStyle: { width: 2 }, z: 3 });
        // V2 OOS curve has no per-point band (p_lo/p_hi null) — the band
        // series render only for the in-sample fallback curve.
        const hasBand = rnd.some((s) => s.p_lo !== null && s.p_lo !== undefined);
        if (hasBand) {
          const bandLo = rnd.map((s) => Math.round(s.p_lo * 1000) / 10);
          const bandHi = rnd.map((s) => Math.round(s.p_hi * 1000) / 10);
          series.push({ name: `R${r}b1`, type: 'line', data: xs.map((x, i) => [x, bandLo[i]]),
                        lineStyle: { opacity: 0 }, stack: `band${r}`, symbol: 'none', silent: true, z: 1 });
          series.push({ name: `R${r}b2`, type: 'line', data: xs.map((x, i) => [x, bandHi[i] - bandLo[i]]),
                        lineStyle: { opacity: 0 }, areaStyle: { color: 'rgba(167,139,250,.10)' },
                        stack: `band${r}`, symbol: 'none', silent: true, z: 1 });
        }
        for (let i = 0; i < rnd.length; i++) {
          const s = rnd[i];
          if (s.planted && (i === 0 || !rnd[i - 1].planted)) {
            markers.push({ value: [s.tick, 50], symbol: 'pin', symbolSize: 30,
                           itemStyle: { color: '#ffb02e' },
                           label: { show: true, formatter: '包', color: '#000', fontSize: 10 } });
          } else if (i > 0 && s.alive_diff !== rnd[i - 1].alive_diff) {
            markers.push({ value: [s.tick, 50], symbol: 'circle', symbolSize: 6,
                           itemStyle: { color: s.alive_diff > 0 ? '#3ddc97' : '#ff4d5e' } });
          }
        }
      }
      const ticksAll = rounds.flatMap((r) => r.map((s) => s.tick));
      const option = {
        tooltip: { trigger: 'axis' },
        legend: { show: false },
        grid: { left: 8, right: 16, top: 16, bottom: 34, containLabel: true },
        xAxis: { type: 'value', min: Math.min(...ticksAll), max: Math.max(...ticksAll),
                 axisLabel: { color: '#9aa0b8', formatter: (v) => Math.round(v / 1000) + 'k' },
                 splitLine: { show: false } },
        yAxis: { type: 'value', min: 0, max: 100, name: 'T 胜率 %',
                 axisLabel: { color: '#9aa0b8' }, splitLine: { lineStyle: { color: '#222438' } } },
        series: [...series, { type: 'scatter', data: markers, silent: true, z: 5 }],
      };
      CSACharts.mount('winprob-chart', option);
    } catch (e) { hideSkeleton('winprob-chart'); }
  }
  const MIX_ZH = { rifle: '步枪', sniper: '狙击枪', pistol: '手枪', smg: '冲锋枪',
                   heavy: '重火力', knife: '刀', grenade: '投掷物', gear: '装备',
                   bomb: 'C4', world: '环境', inferno: '火焰', unknown: '未知' };
  function weaponMixOption(p) {
    const mix = p.weapon_mix || {};
    const cats = {};
    for (const [w, n] of Object.entries(mix)) cats[w] = (cats[w] || 0) + n;
    const entries = Object.entries(cats).filter(([, n]) => n > 0);
    if (!entries.length) return null;
    return {
      tooltip: { trigger: 'item', formatter: (q) => `${MIX_ZH[q.name] || q.name}: <b>${q.value}</b> 杀 (${q.percent}%)` },
      legend: { bottom: 0, textStyle: { color: '#9aa0b8', fontSize: 10 } },
      series: [{
        type: 'pie', radius: ['42%', '70%'], center: ['50%', '44%'],
        data: entries.map(([w, n]) => ({ name: w, value: n })),
        label: { show: false },
      }],
    };
  }
  function hitgroupsOption(p) {
    const groups = p.groups || [];
    const players = (p.players || []).slice(0, 8).reverse();
    if (!players.length) return null;
    const colors = { head: '#ff4d5e', chest: '#a78bfa', stomach: '#3ddc97',
                     arm: '#3d9bff', leg: '#ffb02e', generic: '#636a85' };
    return {
      tooltip: { trigger: 'axis',
                 formatter: (params) => params[0].name + '<br/>' +
                   params.filter((q) => q.value).map((q) =>
                     `${(p.labels || {})[q.seriesName] || q.seriesName}: <b>${q.value}</b>`).join('<br/>') },
      legend: { bottom: 0, textStyle: { color: '#9aa0b8', fontSize: 10 } },
      grid: { left: 8, right: 16, top: 12, bottom: 46, containLabel: true },
      xAxis: { type: 'value', name: '伤害' },
      yAxis: { type: 'category', data: players.map((x) => x.name), axisLabel: { fontSize: 10 } },
      series: groups.map((g) => ({
        name: g, type: 'bar', stack: 'total', barMaxWidth: 14,
        itemStyle: { color: colors[g] || '#636a85' },
        data: players.map((x) => x.damage[g] || 0),
      })),
    };
  }
  function hideSkeleton(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('chart-loading');
  }
  const loaded = new Set();
  function mountPayloadChart(id, build) {
    const el = document.getElementById(id);
    const url = el && el.dataset.chartPayload;
    if (!el || !url) return;
    fetchJson(url)
      .then((p) => {
        const opt = build(p);
        el.classList.remove('chart-loading');
        if (opt) CSACharts.mount(el, opt);
      })
      .catch(() => el.classList.remove('chart-loading'));
  }
  function activate(tab) {
    document.querySelectorAll('#match-tabs .tab-btn').forEach((b) =>
      b.classList.toggle('on', b.dataset.tab === tab));
    document.querySelectorAll('.tab-panel').forEach((p) =>
      p.toggleAttribute('hidden', p.dataset.panel !== tab));
    if (!loaded.has(tab)) {
      loaded.add(tab);
      (loaders[tab] || (() => {}))();
    } else {
      // charts mounted while the panel was hidden (zero-size, e.g. the user
      // switched tabs mid-fetch) init at 0x0 — resize them now that the
      // panel is visible again
      document.querySelectorAll(`[data-panel="${tab}"] .echart, [data-panel="${tab}"] [id$="-chart"]`).forEach((el) => {
        if (window.echarts && el.tagName !== 'CANVAS') {
          const inst = echarts.getInstanceByDom(el);
          if (inst) inst.resize();
        }
      });
    }
  }
  document.querySelectorAll('#match-tabs .tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      const url = new URL(location.href);
      url.searchParams.set('tab', tab);
      history.replaceState(null, '', url);
      activate(tab);
    });
  });
  const initial = TABS.includes(new URLSearchParams(location.search).get('tab'))
    ? new URLSearchParams(location.search).get('tab') : 'overview';
  activate(initial);

  // ---- per-match highlights (M5 payload; fails soft) ----
  function loadMatchHighlights() {
    const box = document.getElementById('match-highlights');
    if (!box) return;
    fetchJson(`/api/demo/${H}/highlights.json`)
      .then((payload) => {
        const TIER = { ace: 'ACE', k4: '4K', k3: '3K', k2: '2K', '1v2': '1v2', '1v3': '1v3', '1v4': '1v4', '1v5': '1v5' };
        const hs = payload.highlights || [];
        box.innerHTML = hs.length ? hs.map((h) =>
          `<a class="hl-card" href="${h.deep_link}">` +
          `<div class="hl-tier">${TIER[h.tier] || h.tier}</div>` +
          `<div class="hl-body"><div class="hl-name">${CSACommon.esc(h.name)}</div>` +
          `<div class="hl-meta">R${h.round} · ${h.kills} 杀 · ${h.side}</div></div>` +
          `<span class="hl-go">▶ 回放</span></a>`).join('')
          : '<div class="empty-state" style="grid-column:1/-1"><div class="empty-title">本场暂无高光</div></div>';
      })
      .catch(() => {
        box.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="empty-title">本场暂无高光</div></div>';
      });
  }

  // ---- R5 失利归因：逐回合标签 chips（双队并列；点击 → 回放器定位）----
  const TAG_ZH = {
    lost_opening: '掉首口', untraded: '无贸易死', lost_force: '强起失利',
    lost_eco: 'eco失利', utility_deficit: '道具劣势', lost_clutch: '残局失守',
  };
  async function loadLossAttribution() {
    const box = document.getElementById('lossattr-panel');
    if (!box) return;
    try {
      const p = await fetchJson(`/api/demo/${H}/loss-attribution.json`);
      const rounds = p.rounds || [];
      const lost = rounds.filter((r) => r.tags && r.tags.length);
      if (!lost.length) {
        box.innerHTML = '<div class="sub" style="padding:6px">本场的失利回合均未命中任何结构化标签</div>';
        return;
      }
      const teamTitle = (side) => side === 'T' ? 'T 方' : 'CT 方';
      box.innerHTML = rounds.map((r) => {
        const chips = (r.tags || []).map((t) =>
          `<a class="loss-tag t-${t}" href="/match/${H}/viewer?round=${r.round}&t=0" ` +
          `title="${CSACommon.esc((p.tag_defs && p.tag_defs[t]) || t)} → 回放器定位 R${r.round}">${TAG_ZH[t] || t}</a>`).join('');
        return `<div style="display:flex;gap:6px;align-items:center;font-size:12px;padding:2px 0">` +
          `<a href="/match/${H}/viewer?round=${r.round}&t=0" class="badge ${r.winner_side === 'T' ? 't' : 'ct'}" ` +
          `style="min-width:38px;text-align:center">R${r.round}</a>` +
          `<span class="sub" style="min-width:78px">${teamTitle(r.loser_side)} 败 · ${r.buy === 'unknown' ? '买法未知' : ({ eco: 'eco', force: '强起', full: '长枪' })[r.buy] || r.buy}</span>` +
          `<span>${chips || '<span class="sub">无标签</span>'}</span></div>`;
      }).join('') +
      `<div class="sub" style="font-size:11px;margin-top:6px">标签口径：${Object.entries(p.tag_defs || {}).map(([k, v]) => `${TAG_ZH[k] || k}=${v}`).join('；')}</div>`;
    } catch (e) {
      box.innerHTML = '<div class="sub" style="padding:6px">失利归因数据不可用</div>';
    }
  }

  document.querySelectorAll('tr.row-link').forEach((tr) => {
    tr.addEventListener('click', (e) => {
      if (e.target.closest('a') || e.target.closest('button')) return;
      location.href = tr.dataset.href;
    });
  });
  loadLossAttribution();
})();
