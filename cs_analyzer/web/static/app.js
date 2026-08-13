// CsDemoAnalyzer web UI helpers: job polling + replay triggering.

function pollJob(jobId, onDone, onError, intervalMs) {
  intervalMs = intervalMs || 1500;
  const timer = setInterval(async () => {
    try {
      const r = await fetch('/api/jobs/' + jobId);
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

async function startReplay(demoHash, recipe, player, btn) {
  btn.disabled = true;
  btn.textContent = '渲染中…';
  const body = new URLSearchParams();
  body.set('recipe', recipe);
  body.set('player', player || '');
  try {
    const r = await fetch('/api/demo/' + demoHash + '/replay', {
      method: 'POST', body: body,
    });
    const j = await r.json();
    if (j.job_id) {
      pollJob(j.job_id, () => { location.reload(); }, (err) => {
        btn.disabled = false; btn.textContent = '失败，重试';
        alert('渲染失败: ' + err);
      });
    } else {
      btn.disabled = false; btn.textContent = '重试';
      alert('错误: ' + (j.error || 'unknown'));
    }
  } catch (e) {
    btn.disabled = false; btn.textContent = '重试';
    alert('请求失败: ' + e);
  }
}
