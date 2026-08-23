// CsDemoAnalyzer web UI helpers: job polling.

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
