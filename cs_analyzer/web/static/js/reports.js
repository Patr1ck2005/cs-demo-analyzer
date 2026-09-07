// Phase L5: 报告导出 — launcher + export history.
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var currentHash = '';

  function loadHistory() {
    fetch('/api/report/exports.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var tb = document.querySelector('#rp-history tbody');
        tb.innerHTML = (d.exports || []).map(function (e) {
          return '<tr><td>' + esc(e.file) + '</td><td class="num">' + e.size_kb + ' KB</td>' +
            '<td>' + esc(e.mtime) + '</td><td><a href="' + esc(e.url) + '" download>下载</a></td></tr>';
        }).join('') || '<tr><td colspan="4" class="sub">还没有导出</td></tr>';
      });
  }

  function doExport(fmt) {
    if (!currentHash) return;
    var png = document.getElementById('rp-png');
    var pdf = document.getElementById('rp-pdf');
    // F9: one export at a time — a second click while chromium is rendering
    // would spawn a second browser AND collide on the same-second filename.
    if (!png || !pdf || png.disabled || pdf.disabled) return;
    png.disabled = pdf.disabled = true;
    var st = document.getElementById('rp-status');
    st.textContent = '正在渲染（约 5-15 秒）…';
    function release() { png.disabled = pdf.disabled = false; }
    fetch('/api/report/' + currentHash + '/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format: fmt }),
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; }); })
      .then(function (res) {
        release();
        if (res.ok && res.d.ok) {
          st.innerHTML = '完成：<a href="' + esc(res.d.url) + '" target="_blank">' + esc(res.d.file) + '</a>';
          loadHistory();
        } else {
          st.textContent = res.d && res.d.error ? res.d.error : '导出失败';
        }
      })
      .catch(function () { release(); st.textContent = '导出失败（网络/服务端错误）'; });
  }

  function init() {
    var sel = document.getElementById('rp-demo');
    if (!sel) return;
    fetch('/api/report/demos.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        sel.innerHTML = (d.demos || []).map(function (m) {
          return '<option value="' + esc(m.demo_hash) + '">' + esc(m.map_name) + ' · ' + esc(m.filename) + '</option>';
        }).join('');
        currentHash = sel.value || '';
        sel.addEventListener('change', function () { currentHash = sel.value; });
        document.getElementById('rp-png').addEventListener('click', function () { doExport('png'); });
        document.getElementById('rp-pdf').addEventListener('click', function () { doExport('pdf'); });
      });
    document.getElementById('rp-preview').addEventListener('click', function (ev) {
      if (currentHash) ev.target.href = '/report/' + currentHash;
      else { ev.preventDefault(); return false; }
    });
    loadHistory();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
