// Video export studio (Phase B3): demo picker + replay/radar background renders.
(function () {
  // ---- landing page: pick a demo then jump to a studio type ----
  const demoSel = document.getElementById('studio-demo');
  const goBtns = document.querySelectorAll('[data-go]');
  if (demoSel && goBtns.length) {
    const statusEl = document.getElementById('studio-status');
    goBtns.forEach((b) => b.addEventListener('click', () => {
      const h = demoSel.value;
      if (!h) { statusEl.textContent = '请先选择一个 demo'; return; }
      location.href = b.dataset.go + h;
    }));
    return;
  }

  const m = location.pathname.match(/\/studio\/[^/]+\/([^/]+)/);
  if (!m) return;
  const HASH = m[1];
  const statusEl = document.getElementById('st-status');
  const resultEl = document.getElementById('st-result');
  const videoEl = document.getElementById('st-video');
  const dlEl = document.getElementById('st-download');

  function showResult(url) {
    resultEl.style.display = 'block';
    videoEl.src = url;
    dlEl.href = url;
  }

  function submit(endpoint, body) {
    statusEl.textContent = '渲染中…（可切走，完成后回来刷新）';
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((r) => r.json())
      .then((j) => {
        if (!j.job_id) throw new Error(j.error || 'unknown');
        pollJob(j.job_id, (url) => {
          statusEl.textContent = '';
          showResult(url);
        }, (err) => { statusEl.textContent = '渲染失败: ' + err; });
      })
      .catch((err) => { statusEl.textContent = '请求失败: ' + err; });
  }

  // ---- replay studio: recipe + nested style overrides ----
  const frm = document.getElementById('frm-studio-replay');
  const btnRender = document.getElementById('btn-render');
  if (frm && btnRender) {
    btnRender.addEventListener('click', () => {
      const recipe = document.getElementById('rc-recipe').value;
      const player = document.getElementById('rc-player').value.trim();
      const override = {};
      frm.querySelectorAll('[data-sec]').forEach((el) => {
        let val;
        if (el.type === 'checkbox') val = el.checked;
        else if (el.value === '') return;
        else if (el.dataset.num === '1') val = Number(el.value);
        else if (el.dataset.list === '1') val = el.value.split(',').map((s) => s.trim()).filter(Boolean);
        else val = el.value;
        if (!override[el.dataset.sec]) override[el.dataset.sec] = {};
        override[el.dataset.sec][el.name] = val;
      });
      submit('/api/studio/replay', { demo_hash: HASH, recipe, player, override });
    });
  }

  // ---- radar studio ----
  const btnRadar = document.getElementById('btn-radar');
  if (btnRadar) {
    btnRadar.addEventListener('click', () => {
      const radar = {
        title: document.getElementById('rc-title').value.trim(),
        subtitle: document.getElementById('rc-subtitle').value.trim(),
        attributes: document.getElementById('rc-attrs').value,
      };
      const quality = document.getElementById('rc-quality').value;
      submit('/api/studio/radar', { demo_hash: HASH, radar, quality });
    });
  }
})();
