// 复盘提升包 B3: highlight clip export — pure-browser webm recording.
// No ffmpeg, no server rendering (project principle): a composite canvas
// redraws the three viewer layers each rAF, canvas.captureStream(30) feeds
// MediaRecorder, the blob downloads as `{map}_R{round}.webm`.
//
// Modes:
//   manual — #btn-rec toggles: start now / stop + download;
//   auto   — ?rec=1 (optional &recname=) arms on load: seek to the round
//            start, play, auto-stop at the segment end.
//
// Everything reads through window.__viewerDebug (state/D/segments) —
// zero changes to viewer_canvas.js playback logic. Feature-gated: the
// button stays hidden when MediaRecorder/captureStream are unavailable.
(function () {
  const btn = document.getElementById('btn-rec');
  if (!btn) return;
  if (typeof MediaRecorder === 'undefined' ||
      !HTMLCanvasElement.prototype.captureStream) {
    btn.title = '此浏览器不支持 canvas 录制';
    return; // stays hidden
  }
  btn.hidden = false;

  const LAYER_IDS = ['map-layer', 'fx-layer', 'main-layer'];
  const dbg = () => window.__viewerDebug || null;

  let rec = null;
  let chunks = [];
  let composited = null;
  let rafId = 0;
  let stoppedByRoundEnd = false;
  let autoArmed = false;
  let downloadName = '';

  function segOfTick(tick) {
    const d = dbg();
    if (!d || !d.D || !d.D.segments) return null;
    return d.D.segments.find((s) => tick >= s.start_tick && tick <= s.end_tick)
      || d.D.segments[d.D.segments.length - 1];
  }

  function composite() {
    const d = dbg();
    if (!d) return;
    const base = document.getElementById('map-layer');
    if (!base) return;
    if (!composited || composited.width !== base.width ||
        composited.height !== base.height) {
      composited = document.createElement('canvas');
      composited.width = base.width;
      composited.height = base.height;
    }
    const ctx = composited.getContext('2d');
    ctx.fillStyle = '#0b0c16';
    ctx.fillRect(0, 0, composited.width, composited.height);
    for (const id of LAYER_IDS) {
      const c = document.getElementById(id);
      if (c && c.width && c.height) ctx.drawImage(c, 0, 0);
    }
  }

  function pump() {
    if (!rec) return;
    composite();
    rafId = requestAnimationFrame(pump);
  }

  function pickMime() {
    for (const m of ['video/webm;codecs=vp9', 'video/webm;codecs=vp8',
                     'video/webm']) {
      if (MediaRecorder.isTypeSupported(m)) return m;
    }
    return '';
  }

  function start(name) {
    const base = document.getElementById('map-layer');
    const mime = pickMime();
    if (!base || !mime) { btn.textContent = '不支持录制'; return; }
    composite();
    const cs = composited.captureStream(30);
    chunks = [];
    rec = new MediaRecorder(cs, { mimeType: mime, videoBitsPerSecond: 6_000_000 });
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      const blob = new Blob(chunks, { type: 'video/webm' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name || defaultName();
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      btn.textContent = '⏺ 录制';
      btn.classList.remove('on');
      if (stoppedByRoundEnd) { stoppedByRoundEnd = false; close(); }
    };
    rec.start(250);
    btn.textContent = '⏹ 停止并下载';
    btn.classList.add('on');
    cancelAnimationFrame(rafId);
    pump();
  }

  function stop(byRoundEnd) {
    stoppedByRoundEnd = !!byRoundEnd;
    if (rec && rec.state !== 'inactive') rec.stop();
    cancelAnimationFrame(rafId);
    rafId = 0;
  }

  function defaultName() {
    const d = dbg();
    const map = (d && d.D && d.D.map_name) || 'map';
    const seg = d ? segOfTick(d.state.tick) : null;
    return `${map}_R${seg ? seg.round : 'x'}.webm`;
  }

  function close() {
    // ?rec=1 auto mode: return to the plain viewer URL once the clip lands
    if (autoArmed) {
      autoArmed = false;
      const u = new URL(location.href);
      u.searchParams.delete('rec');
      u.searchParams.delete('recname');
      history.replaceState(null, '', u.pathname + u.search);
    }
  }

  btn.addEventListener('click', () => {
    if (rec && rec.state === 'recording') stop(false);
    else start('');
  });

  // ---- auto mode: ?rec=1 arms recording of the deep-linked round ----
  const q = new URLSearchParams(location.search);
  if (q.get('rec') === '1') {
    autoArmed = true;
    downloadName = q.get('recname') || '';
    const waitData = () => {
      const d = dbg();
      if (!d || !d.D || !d.D.segments || !d.D.segments.length) {
        setTimeout(waitData, 400);
        return;
      }
      const seg = segOfTick(d.state.tick) || d.D.segments[0];
      const t0 = Date.now();
      const waitArmed = () => {
        // recording must not outlive ~115s of round + margin; and a dead
        // recorder (encoder absent at runtime) stops the wait
        if (rec && rec.state === 'recording') {
          const s2 = segOfTick(d.state.tick);
          if (s2 && s2.round !== seg.round) stop(true);
          else setTimeout(waitArmed, 250);
        } else if (Date.now() - t0 > 30000) {
          // autoplay/simeline not ready in time — give up quietly (manual
          // chip still works)
          return;
        } else {
          setTimeout(waitArmed, 250);
        }
      };
      // seek to the segment start, then play; arm the recorder once ticks
      // are moving (the frame loop drives both rendering and playback)
      d.state.tick = seg.start_tick;
      const btnPlay = document.getElementById('btn-play');
      if (btnPlay) btnPlay.click();
      const waitTickMoves = () => {
        if (d.state.tick > seg.start_tick) { start(downloadName); waitArmed(); return; }
        if (Date.now() - t0 > 30000) return;
        setTimeout(waitTickMoves, 200);
      };
      setTimeout(waitTickMoves, 600);
    };
    waitData();
  }
})();
