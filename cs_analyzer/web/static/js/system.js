// M3 还债 (第 2/3 处): system page logic — extracted verbatim from the
// system.html inline block (match_detail.js/teams.js precedent; behavior
// parity is the acceptance criterion; no Jinja inside this file).
(async function () {
  // cache & versions
  try {
    const r = await fetch('/api/system/status.json');
    if (r.ok) {
      const s = await r.json();
      document.getElementById('sys-cache').innerHTML =
        `缓存条目 <b>${s.cache_entries}</b> 个 · 占用 <b>${s.cache_size_mb}</b> MB<br>` +
        `解析器 PARSER <b>${s.parser_version}</b> · viewer-data <b>v${s.viewer_data_version}</b> · layers <b>v${s.layer_version}</b>`;
      renderPerf(s);
    }
  } catch (e) { /* card stays placeholder */ }

  // Phase T1 performance panel: snapshot inventory + prewarm diagnostics
  function renderPerf(s) {
    const el = document.getElementById('sys-perf');
    if (!el) return;
    const snap = s.snapshots || { snapshots: [] };
    const wu = s.warmup || {};
    const cur = (snap.snapshots || []).filter(x => x.current).length;
    const total = (snap.snapshots || []).length;
    const wuT = wu.t_done && wu.t_started ? (wu.t_done - wu.t_started) : null;
    let html = `<div style="margin-bottom:8px">快照 <b>${cur}/${total}</b> 与当前库指纹一致` +
      ` · 指纹 <code class="kbd">${(snap.fingerprint || '').slice(0, 12)}</code>` +
      (wuT != null ? ` · 本次预热 <b>${wuT.toFixed(1)}s</b>（快照命中 ${wu.snapshot_hits ? wu.snapshot_hits.length : 0} 项）` : '') +
      `</div>`;
    html += '<table style="width:100%"><thead><tr><th>快照</th><th>状态</th><th>大小</th><th>落盘时间</th></tr></thead><tbody>' +
      (snap.snapshots || []).map(x => {
        const st = !x.exists ? '<span class="badge t0">未生成</span>'
          : x.current ? '<span class="badge ok">有效</span>'
          : '<span class="badge ct">过期</span>';
        return `<tr><td><code>${x.name}</code></td><td>${st}</td>` +
          `<td>${x.size_kb != null ? x.size_kb + ' KB' : '—'}</td>` +
          `<td class="sub">${x.saved_at || '—'}</td></tr>`;
      }).join('') + '</tbody></table>' +
      `<div class="sub" style="margin-top:8px">快照命中时重启后预热秒级完成；新增 demo / 解析器升级 / 代码更新会自动失效重算。` +
      `快照文件位于 <code>output/web/snapshots/</code>，可随时删除（下次启动自动重建）。</div>`;
    el.innerHTML = html;
  }

  // jobs (poll every 2s; stop after 5 consecutive failures instead of
  // silently spinning forever when the server goes away)
  const jobsEl = document.getElementById('sys-jobs');
  let pollFailures = 0;
  async function pollJobs() {
    try {
      const r = await fetch('/api/jobs');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const jobs = await r.json();
      pollFailures = 0;
      if (!jobs.length) { jobsEl.textContent = '暂无任务。'; return; }
      jobsEl.innerHTML = jobs.slice(0, 12).map((j) => {
        const cls = j.status === 'done' ? 'ok' : j.status === 'error' ? 't0' : 'ct';
        // F8: label = the original demo FILENAME (external, user-influenced)
        // and error = str(exception) — both must be escaped before innerHTML.
        return `<div style="padding:3px 0"><span class="badge ${cls}">${j.status}</span> ` +
          `${CSACommon.esc(j.label || j.id)} ${j.error ? '· <span style="color:var(--err)">' + CSACommon.esc(j.error) + '</span>' : ''}</div>`;
      }).join('');
    } catch (e) {
      pollFailures += 1;
      if (pollFailures >= 5) {
        clearInterval(jobsTimer);
        jobsEl.textContent = '任务队列不可达（服务异常？）— 已停止自动刷新。';
      }
    }
  }
  pollJobs();
  const jobsTimer = setInterval(pollJobs, 2000);

  // unparsed files
  const upEl = document.getElementById('sys-unparsed');
  async function pollUnparsed() {
    try {
      const r = await fetch('/api/system/unparsed.json');
      if (!r.ok) return;
      const u = await r.json();
      upEl.textContent = u.files.length
        ? `${u.files.length} 个 .dem 未入库：${u.files.slice(0, 6).join('、')}${u.files.length > 6 ? ' …' : ''}`
        : 'demos/ 下所有文件均已入库。';
    } catch (e) { /* keep previous frame */ }
  }
  pollUnparsed();
  document.getElementById('sys-import').addEventListener('click', async () => {
    const btn = document.getElementById('sys-import');
    btn.disabled = true;
    try {
      await fetch('/system/import', { method: 'POST' });
      setTimeout(() => { pollUnparsed(); pollJobs(); btn.disabled = false; }, 800);
    } catch (e) { btn.disabled = false; }
  });

  // 复盘提升包 B2: auto-import watcher toggle + status
  const autoCb = document.getElementById('sys-auto-import');
  const autoSt = document.getElementById('sys-auto-status');
  async function pollAutoImport() {
    try {
      const r = await fetch('/api/system/auto-import.json');
      if (!r.ok) return;
      const s = await r.json();
      autoCb.checked = s.enabled;
      const failedList = (s.failed || []).slice(0, 3)
        .map((f) => CSACommon.esc(f.name || f.hash)).join('、');
      autoSt.innerHTML = `自动入库：${s.enabled ? '开启' : '关闭'} · 监视 <code>${CSACommon.esc(s.watched)}</code>` +
        ` · ${CSACommon.esc(s.last_action)}` +
        (s.failed_n ? ` · <span style="color:var(--err)">${s.failed_n} 个解析失败（不重试）${failedList ? '：' + failedList : ''}</span>` : '');
    } catch (e) { /* keep previous frame */ }
  }
  pollAutoImport();
  setInterval(pollAutoImport, 10000);
  autoCb.addEventListener('change', async () => {
    try {
      await fetch('/api/system/auto-import.json', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: autoCb.checked }),
      });
    } catch (e) { /* status line refreshes on next poll */ }
    pollAutoImport();
  });

  // S2-A5: platform source dirs dry-run scan (reports only, never imports)
  const scanBtn = document.getElementById('sys-scan-sources');
  const scanBox = document.getElementById('sys-scan-result');
  scanBtn.addEventListener('click', async () => {
    scanBtn.disabled = true;
    scanBox.style.display = 'block';
    scanBox.innerHTML = '<span class="warm-dots">扫描平台源目录中（逐 zip 校验内层内容哈希，可能需要几十秒）…</span>';
    try {
      const r = await fetch('/api/system/scan-sources.json');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      const rows = d.sources.map((s) => {
        if (!s.exists) return `<div style="padding:3px 0">❓ <b>${CSACommon.esc(s.name)}</b> — 目录不存在：${CSACommon.esc(s.path)}</div>`;
        const parts = [`${s.zips} 包`];
        if (s.new) parts.push(`<span style="color:var(--ok)">${s.new} 新</span>`);
        if (s.duplicates) parts.push(`${s.duplicates} 重复`);
        if (s.corrupt) parts.push(`<span style="color:var(--err)">${s.corrupt} 损坏</span>`);
        return `<div style="padding:3px 0">📦 <b>${CSACommon.esc(s.name)}</b> — ${parts.join(' · ')}` +
          (s.new_files.length ? `（${CSACommon.esc(s.new_files.slice(0, 4).join('、'))}${s.new_files.length > 4 ? ' …' : ''}）` : '') + `</div>`;
      }).join('');
      scanBox.innerHTML = `<div style="margin-bottom:4px">平台源扫描（dry-run，未导入）：共 <b>${d.total_new}</b> 个新 demo · demos/ 现有 ${d.known_demos} 个。</div>${rows}` +
        `<div class="sub" style="margin-top:6px">新 demo 需复制到 demos/ 后用"一键入库"解析。</div>`;
    } catch (e) {
      scanBox.innerHTML = '扫描失败' + (e && e.message === 'HTTP 404'
        ? '（未配置 configs/demo_sources.yaml）' : '（网络错误或服务异常）。');
    } finally {
      scanBtn.disabled = false;
    }
  });
})();
