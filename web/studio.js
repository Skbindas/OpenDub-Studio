/* Real media previews, measured spectrum and keyboard-accessible dialogs. */
(() => {
  const el = id => document.getElementById(id);
  const players = {source: el("sourcePreview"), vocals: el("vocalsPlayer"), background: el("backgroundPlayer"), mix: el("mixPlayer")};
  let context, analyser, activePlayer, frame;
  const sources = new WeakMap();
  const canvas = el("measuredSpectrum");
  const brush = canvas.getContext("2d");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");

  function clearSpectrum(message = "Play a preview to measure its audio.") {
    cancelAnimationFrame(frame);
    brush.clearRect(0, 0, canvas.width, canvas.height);
    brush.strokeStyle = "#cbd8e8";
    brush.beginPath(); brush.moveTo(0, canvas.height - 12); brush.lineTo(canvas.width, canvas.height - 12); brush.stroke();
    el("spectrumStatus").textContent = message;
  }
  function draw() {
    if (!activePlayer || activePlayer.paused || document.hidden || reduced.matches) return;
    const bins = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(bins);
    brush.clearRect(0, 0, canvas.width, canvas.height);
    const count = 80, width = canvas.width / count;
    for (let i = 0; i < count; i++) {
      const start = Math.floor(i * bins.length / count), end = Math.floor((i + 1) * bins.length / count);
      let value = 0;
      for (let k = start; k < end; k++) value = Math.max(value, bins[k]);
      const height = value / 255 * (canvas.height - 12);
      brush.fillStyle = i < count / 2 ? "#2256c7" : "#087c70";
      brush.fillRect(i * width + 2, canvas.height - height - 6, width - 3, height);
    }
    frame = requestAnimationFrame(draw);
  }
  document.addEventListener("play", async event => {
      const player = event.target;
      if (!(player instanceof HTMLMediaElement)) return;
      document.querySelectorAll("audio,video").forEach(other => { if (other !== player) other.pause(); });
      activePlayer = player;
      try {
        context ||= new AudioContext();
        analyser ||= context.createAnalyser();
        analyser.fftSize = 2048;
        if (!sources.has(player)) {
          const source = context.createMediaElementSource(player);
          source.connect(analyser); sources.set(player, source);
        }
        analyser.connect(context.destination);
        await context.resume();
        el("spectrumMax").textContent = (context.sampleRate / 2000).toFixed(1) + " kHz";
        clearSpectrum(reduced.matches ? "Live graph paused for reduced motion; audio still plays." : "Measured playback amplitude by frequency");
        draw();
      } catch {
        clearSpectrum("Spectrum unavailable. Use the audio controls to review.");
      }
    }, true);
    document.addEventListener("pause", event => { if(activePlayer === event.target) clearSpectrum("Playback paused"); }, true);
    document.addEventListener("ended", event => { if(activePlayer === event.target) clearSpectrum("Playback finished"); }, true);
    document.addEventListener("error", event => {
      const player = event.target;
      if (!(player instanceof HTMLMediaElement)) return;
      const status = player.id === "sourcePreview" ? el("sourcePreviewStatus") : el(player.id.replace("Player", "Status"));
      if(status && player.getAttribute("src")) status.textContent = "Preview could not load. Refresh audio or regenerate this artifact.";
    }, true);
  document.addEventListener("visibilitychange", () => {
    cancelAnimationFrame(frame);
    if(!document.hidden) draw();
  });
  reduced.addEventListener("change", () => { clearSpectrum(); draw(); });
  clearSpectrum();

  window.refreshStudioMedia = async () => {
    const projectId = state.selected;
    if (!projectId) return;
    try {
      const result = await api("/api/projects/" + projectId + "/media-assets");
      if (state.selected !== projectId) return;
      for (const [key, player] of Object.entries(players)) {
        const asset = result.assets[key];
        const status = el(key === "source" ? "sourcePreviewStatus" : key + "Status");
        const url = asset?.url;
        if (url && player.getAttribute("src") !== url) { player.src = url; player.load(); }
        if (!url && player.getAttribute("src")) { player.pause(); player.removeAttribute("src"); player.load(); }
        player.classList.toggle("hidden", !url);
        status.textContent = url ? (key === "background" ? "Separated music/effects. Default mix uses 0 dB gain; listen for artifacts." : "Ready to preview") : key === "source" ? "Upload a source video first." : "Not generated yet";
      }
    } catch (error) {
      el("sourcePreviewStatus").textContent = "Could not load project media: " + error.message;
    }
  };
  el("refreshPreviewsBtn").addEventListener("click", window.refreshStudioMedia);

  // Modal focus is driven by actual visibility, including legacy open/close buttons.
  document.querySelectorAll('[role="dialog"]').forEach(dialog => {
    let previousFocus, wasOpen = false;
    const focusable = () => [...dialog.querySelectorAll('button:not(:disabled),input,select,a[href],summary,textarea')].filter(node => node.getClientRects().length);
    new MutationObserver(() => {
      const open = !dialog.classList.contains("hidden");
      if (open && !wasOpen) {
        previousFocus = document.activeElement;
        (dialog.querySelector("input") || focusable()[0])?.focus();
      } else if (!open && wasOpen) {
        (previousFocus?.isConnected && !dialog.contains(previousFocus) ? previousFocus : el("newProjectBtn"))?.focus();
      }
      wasOpen = open;
    }).observe(dialog, {attributes:true, attributeFilter:["class"]});
    dialog.addEventListener("keydown", event => {
      if(event.key === "Escape") { dialog.classList.add("hidden"); event.stopPropagation(); }
      if(event.key !== "Tab") return;
      const nodes = focusable(), first = nodes[0], last = nodes[nodes.length - 1];
      if(event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if(!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });
    dialog.addEventListener("click", event => { if(event.target === dialog) dialog.classList.add("hidden"); });
  });
  document.querySelectorAll('.workspace-nav a').forEach(link => link.addEventListener("click", () => {
    const target = document.querySelector(link.getAttribute("href"));
    if(target && !target.classList.contains("hidden")) { target.tabIndex = -1; target.focus({preventScroll:true}); }
  }));
  window.refreshStudioMedia();
})();
