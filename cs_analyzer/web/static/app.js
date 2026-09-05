// CsDemoAnalyzer web UI helpers: job polling + Phase G motion utilities.
(function () {
  'use strict';
  const REDUCED = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- count-up: animate numeric text from 0 to its final value ----
  // Only pure numbers (int/float, optional %) are animated; anything else
  // keeps its SSR text untouched.
  function countUp(el) {
    if (REDUCED || el.dataset.counted) return;
    const raw = (el.textContent || '').trim();
    const m = raw.match(/^(\d+(?:\.\d+)?)(%)?$/);
    if (!m) return;
    const target = parseFloat(m[1]);
    if (!isFinite(target) || target === 0) { el.dataset.counted = '1'; return; }
    const suffix = m[2] || '';
    const decimals = (m[1].split('.')[1] || '').length;
    const dur = 600;
    const t0 = performance.now();
    el.dataset.counted = '1';
    function frame(ts) {
      const p = Math.min((ts - t0) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3); // ease-out cubic
      el.textContent = (target * eased).toFixed(decimals) + suffix;
      if (p < 1) requestAnimationFrame(frame);
      else el.textContent = m[1] + suffix;
    }
    requestAnimationFrame(frame);
  }

  // ---- stagger: tag tbody rows with --i for the CSS cascade delay ----
  function staggerRows() {
    for (const tb of document.querySelectorAll('tbody')) {
      let i = 0;
      for (const tr of tb.children) tr.style.setProperty('--i', String(i++));
    }
  }

  function initMotion() {
    staggerRows();
    document.querySelectorAll('.stat-value').forEach(countUp);
    // score-hero big digits (T/CT spans inside .score)
    document.querySelectorAll('.score-hero .score > span:not(.vs)').forEach(countUp);
    // OB scoreboard live scores start small — animate only on load snapshot
    ['score-t', 'score-ct'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) countUp(el);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMotion);
  } else {
    initMotion();
  }
})();

function pollJob(jobId, onDone, onError, intervalMs) {
  intervalMs = intervalMs || 1500;
  const timer = setInterval(async () => {
    try {
      const r = await fetch('/api/jobs/' + jobId);
      if (!r.ok) throw new Error('HTTP ' + r.status); // 404 etc: job registry lost it
      const j = await r.json();
      if (j.status === 'done') {
        clearInterval(timer);
        onDone(j.result);
      } else if (j.status === 'error') {
        clearInterval(timer);
        onError(j.error);
      }
    } catch (e) {
      clearInterval(timer);
      onError(String(e));
    }
  }, intervalMs);
}
