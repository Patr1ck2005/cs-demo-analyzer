// 2D map replay viewer (Phase B2, MVP: pre-rendered video + drag-seek timeline).
(function () {
  const m = location.pathname.match(/\/demo\/([^/]+)\/viewer/);
  if (!m) return;
  const HASH = m[1];

  const video = document.getElementById('viewer-video');
  const canvas = document.getElementById('tl-canvas');
  const tip = document.getElementById('tl-tip');
  const ctx2d = canvas ? canvas.getContext('2d') : null;
  const DPR = window.devicePixelRatio || 1;
  let data = null;
  let totalSec = 0;
  let dragging = false;

  function secOfTick(tick) {
    if (!data) return 0;
    for (const s of data.segments) {
      if (tick >= s.start_tick && tick <= s.end_tick) {
        const span = Math.max(s.end_tick - s.start_tick, 1);
        const p = Math.min(Math.max((tick - s.start_tick) / span, 0), 1);
        return (s.video_start + p * s.n_frames) / data.fps;
      }
    }
    return 0;
  }

  function tickOfSec(sec) {
    if (!data) return null;
    for (const s of data.segments) {
      const a = s.video_start / data.fps;
      const b = s.video_end / data.fps;
      if (sec >= a && sec < b) {
        const frame = Math.floor(sec * data.fps) - s.video_start;
        if (frame >= s.n_frames) return { tick: s.end_tick, round: s.round };
        const p = frame / Math.max(s.n_frames, 1);
        return { tick: Math.round(s.start_tick + p * (s.end_tick - s.start_tick)), round: s.round };
      }
    }
    const last = data.segments[data.segments.length - 1];
    return last ? { tick: last.end_tick, round: last.round } : null;
  }

  function draw(playheadSec) {
    if (!ctx2d || !data) return;
    const W = canvas.clientWidth;
    const H = canvas.clientHeight;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    ctx2d.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx2d.clearRect(0, 0, W, H);
    const x = (s) => (s / totalSec) * W;
    const kills = (data.events && data.events.kills) || [];
    const utils = (data.events && data.events.utilities) || [];

    data.segments.forEach((s) => {
      const x0 = x(s.video_start / data.fps);
      const x1 = x(s.video_end / data.fps);
      const color = s.winner_side === 'T' ? '#fbbf24' : '#60a5fa';
      ctx2d.fillStyle = color;
      ctx2d.globalAlpha = 0.22;
      ctx2d.fillRect(x0, 2, Math.max(x1 - x0, 1), H - 4);
      ctx2d.globalAlpha = 1;
      ctx2d.strokeStyle = color;
      ctx2d.lineWidth = 1;
      ctx2d.strokeRect(x0 + 0.5, 2.5, Math.max(x1 - x0 - 1, 1), H - 5);
      ctx2d.fillStyle = '#dbe4ee';
      ctx2d.font = '10px "Microsoft YaHei", sans-serif';
      ctx2d.textAlign = 'center';
      ctx2d.fillText('R' + s.round, (x0 + x1) / 2, H / 2 + 3.5);
    });

    utils.forEach((u) => {
      const px = x(secOfTick(u.tick));
      if (px >= 0 && px <= W) {
        ctx2d.fillStyle = '#8fa3b8';
        ctx2d.fillRect(px - 0.5, H - 9, 1, 5);
      }
    });

    kills.forEach((k) => {
      const px = x(secOfTick(k.tick));
      if (px >= 0 && px <= W) {
        ctx2d.beginPath();
        ctx2d.arc(px, 8, 2.4, 0, Math.PI * 2);
        ctx2d.fillStyle = '#f87171';
        ctx2d.fill();
      }
    });

    if (playheadSec != null) {
      const px = x(playheadSec);
      ctx2d.strokeStyle = '#ffffff';
      ctx2d.lineWidth = 1.6;
      ctx2d.beginPath();
      ctx2d.moveTo(px, 0);
      ctx2d.lineTo(px, H);
      ctx2d.stroke();
    }
  }

  function tipText(px) {
    if (!data) return '';
    const sec = (px / canvas.clientWidth) * totalSec;
    const pos = tickOfSec(sec);
    if (!pos) return '';
    const seg = data.segments.find((s) => s.round === pos.round);
    let t = '回合 ' + pos.round;
    if (seg) t += ' · ' + (seg.winner_side === 'T' ? 'T 获胜' : 'CT 获胜');
    const kills = (data.events && data.events.kills) || [];
    const near = kills.find((k) => Math.abs(secOfTick(k.tick) - sec) < 1.5);
    if (near) t += '　💀 ' + (near.attacker || '?') + ' → ' + (near.victim || '?') + (near.weapon ? ' (' + near.weapon + ')' : '');
    return t;
  }

  function showTip(px) {
    const txt = tipText(px);
    if (!txt) { tip.style.display = 'none'; return; }
    tip.textContent = txt;
    tip.style.display = 'block';
    const w = tip.offsetWidth;
    tip.style.left = (px - w / 2) + 'px';
  }

  function seekToPx(px) {
    if (!data || !video) return;
    const sec = (px / canvas.clientWidth) * totalSec;
    video.currentTime = Math.max(0, Math.min(sec, video.duration || totalSec));
  }

  function redraw() {
    draw(video ? video.currentTime : null);
    const pos = video && data ? tickOfSec(video.currentTime) : null;
    const tickEl = document.getElementById('cur-tick');
    if (tickEl) tickEl.textContent = pos ? 'tick ' + pos.tick : '';
  }

  // ---- ready flow ----
  if (video) {
    fetch('/api/demo/' + HASH + '/replay-map')
      .then((r) => r.json())
      .then((d) => {
        if (d.status !== 'ready') { location.reload(); return; }
        data = d;
        totalSec = d.total_frames / d.fps;
        video.src = d.video_url;
        // round jump select
        const sel = document.getElementById('sel-round');
        d.segments.forEach((s) => {
          const o = document.createElement('option');
          o.value = s.round;
          o.textContent = '回合 ' + s.round;
          sel.appendChild(o);
        });
        sel.addEventListener('change', () => {
          const s = d.segments.find((x) => x.round === Number(sel.value));
          if (s) video.currentTime = s.video_start / d.fps;
        });
        draw(video.currentTime);
        // play/pause
        const btn = document.getElementById('btn-play');
        btn.addEventListener('click', () => {
          if (video.paused) { video.play(); btn.textContent = '暂停'; }
          else { video.pause(); btn.textContent = '播放'; }
        });
        video.addEventListener('play', () => { btn.textContent = '暂停'; });
        video.addEventListener('pause', () => { btn.textContent = '播放'; });
        // speed
        const sp = document.getElementById('sel-speed');
        sp.addEventListener('change', () => { video.playbackRate = Number(sp.value); });
        // timeline interactions
        canvas.addEventListener('mousedown', (e) => {
          dragging = true;
          seekToPx(e.offsetX);
          showTip(e.offsetX);
          video.pause();
        });
        canvas.addEventListener('mousemove', (e) => {
          if (dragging) { seekToPx(e.offsetX); showTip(e.offsetX); }
          else showTip(e.offsetX);
        });
        canvas.addEventListener('mouseleave', () => { dragging = false; tip.style.display = 'none'; });
        window.addEventListener('mouseup', () => { dragging = false; });
        video.addEventListener('timeupdate', redraw);
        window.addEventListener('resize', () => { redraw(); });
      })
      .catch(() => alert('无法加载回放数据'));
  }

  // ---- pre-render flow ----
  const form = document.getElementById('frm-prerender');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const statusEl = document.getElementById('pr-status');
      const speed = document.getElementById('pr-speed').value;
      const btn = form.querySelector('button');
      btn.disabled = true;
      btn.textContent = '渲染中…';
      const body = new URLSearchParams();
      body.set('speed', speed);
      fetch('/api/demo/' + HASH + '/replay-map', { method: 'POST', body })
        .then((r) => r.json())
        .then((j) => {
          if (!j.job_id) throw new Error(j.error || 'unknown');
          statusEl.textContent = '渲染中，请稍候…';
          pollJob(j.job_id, () => { location.reload(); }, (err) => {
            btn.disabled = false;
            btn.textContent = '重试';
            statusEl.textContent = '渲染失败: ' + err;
          });
        })
        .catch((err) => {
          btn.disabled = false;
          btn.textContent = '重试';
          statusEl.textContent = '请求失败: ' + err;
        });
    });
  }
})();
