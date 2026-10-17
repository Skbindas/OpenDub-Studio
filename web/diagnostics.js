(() => {
  const el = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (m) => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
  }[m]));

  const bytes = (value) => {
    if (value === null || value === undefined) return "Unavailable";
    const n = Number(value);
    if (!Number.isFinite(n)) return "Unavailable";
    if (n < 1024) return n + " B";
    const units = ["KB","MB","GB","TB"];
    let x = n / 1024, i = 0;
    while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
    return x.toFixed(x >= 100 ? 0 : 1) + " " + units[i];
  };

  const card = (title, status, values) => {
    const label = status === "ok" ? "Ready" : status === "warning" ? "Warning" :
      status === "missing" ? "Missing" : status === "error" ? "Error" : "Info";
    return '<article class="diagnostic-card">' +
      '<div class="diagnostic-card-head"><strong>' + esc(title) +
      '</strong><span class="diagnostic-state ' + esc(status || "info") + '">' + label + '</span></div>' +
      values.map((v) => '<div class="diagnostic-value">' + esc(v || "—") + '</div>').join("") +
      '</article>';
  };

  const render = (report) => {
    const grid = el("diagnosticsGrid");
    const summary = el("diagnosticsSummary");
    const raw = el("diagnosticsRaw");
    const checked = el("diagnosticsCheckedAt");
    if (!grid || !summary) return;

    const gpu = report.gpu || {}, devices = gpu.devices || [];
    const py = report.python || {}, ff = report.ffmpeg || {}, fp = report.ffprobe || {};
    const mem = report.memory || {}, disk = report.disk || {};
    const cpu = report.system || {}, plan = report.processing_plan || {}, accel = report.acceleration || {};
    const integration = report.integrations || {};
    const speakerConfigured = integration.huggingface_token_configured && integration.diarization_runtime_installed;
    const accessBlocked = ["authorization_required", "error"].includes(integration.diarization_access?.status);
    const gpuValues = devices.length
      ? devices.map((g, i) => (devices.length > 1 ? "GPU " + (i + 1) + ": " : "") +
          (g.name || "Unknown GPU") + " · " + (g.vram_total_mb ?? "?") + " MB VRAM" +
          " (" + (g.vram_free_mb ?? "?") + " MB free)" +
          (g.driver_version ? " · Driver " + g.driver_version : ""))
      : [gpu.error || "No compatible NVIDIA GPU detected"];

    grid.innerHTML = [
      card("CPU", "info", [cpu.processor || "Model unavailable", `${cpu.physical_cpu_count ?? "?"} physical cores · ${cpu.logical_cpu_count ?? "?"} logical threads`]),
      card("GPU / VRAM", gpu.available ? (gpu.status || "ok") : "info", gpuValues.concat([`ASR CUDA: ${accel.asr_cuda ? "available" : "unavailable; CPU fallback"}`, `Separation CUDA: ${accel.separation_cuda ? "available" : "unavailable; CPU fallback"}`])),
      card("Processing capacity", plan.admitted ? "info" : "warning", [
        `${plan.heavy_workers ?? 0} heavy workers maximum · ${plan.speech_workers ?? 0} speech workers maximum`,
        `${plan.cpu_threads_per_worker ?? 1} CPU threads per heavy worker · ${plan.chunk_seconds ?? "?"}s planned chunks`,
        `${bytes(plan.reserved_ram_bytes)} RAM reserved for the system`,
        ...(plan.reasons || []),
        "Limits are checked again for each project; long-video parallel mode needs validation."
      ]),
      card("Python", py.status || "warning", ["Python " + (py.version || "Unavailable"), py.executable || "Path unavailable"]),
      card("FFmpeg", ff.status === "ok" && ff.shared_runtime?.required && ff.shared_runtime?.available === false ? "warning" : (ff.status || "missing"), [
        ff.version || ff.error || "Not detected",
        ff.path || "Path unavailable",
        ff.shared_runtime?.required && !ff.shared_runtime?.available
          ? "TorchCodec requires FFmpeg shared DLLs. Install “FFmpeg (Shared)” on Windows."
          : (ff.shared_runtime?.required ? "Shared FFmpeg DLLs detected" : "")
      ]),
      card("FFprobe", fp.status || "missing", [fp.version || fp.error || "Not detected", fp.path || "Path unavailable"]),
      card("RAM", mem.error ? "warning" : "ok", [
        bytes(mem.total_bytes) + " total",
        bytes(mem.available_bytes) + " available" +
          (mem.percent !== null && mem.percent !== undefined ? " · " + mem.percent + "% used" : "")
      ]),
      card("Disk space", disk.status || "error", [bytes(disk.free_bytes) + " free", disk.path || "Data directory unavailable"]),
      card("Storage devices", "info", (report.storage_devices || []).length ? report.storage_devices.map(d => `${d.FriendlyName || "Disk"} · ${d.MediaType === 4 || d.MediaType === "SSD" ? "SSD" : d.MediaType === 3 || d.MediaType === "HDD" ? "HDD" : "Type unavailable"} · ${d.BusType || "Bus unavailable"} · ${bytes(d.Size)}`) : ["Storage type unavailable; free workspace space is measured above"]),
      card("Speaker diarization", integration.diarization_ready ? "ok" : speakerConfigured && !accessBlocked ? "info" : "warning", [
        integration.diarization_ready ? "Ready · Community-1" : speakerConfigured && !accessBlocked ? "Configured · model access checked when run" : "Setup required",
        report.integrations?.diarization_runtime_installed ? "pyannote.audio installed" : "Install requirements-diarization.txt",
        report.integrations?.huggingface_token_configured ? "HF_TOKEN configured" : "HF_TOKEN not configured",
        report.integrations?.diarization_access?.status === "authorization_required"
          ? "Model access requires accepting Hugging Face conditions"
          : (report.integrations?.diarization_access?.reason || "Model access not checked")
      ])
    ].join("");

    const warnings = [];
    if (!ff.available) warnings.push("FFmpeg missing");
    if (!fp.available) warnings.push("FFprobe missing");
    if (ff.shared_runtime?.required && !ff.shared_runtime?.available) warnings.push("FFmpeg shared DLLs missing for TorchCodec");
    if (disk.status === "warning") warnings.push("Low disk space (<5 GB)");
    if (disk.status === "error") warnings.push("Disk check failed");
    if (!speakerConfigured || accessBlocked) warnings.push("Speaker diarization needs setup");
    if (plan.admitted === false) warnings.push(...(plan.reasons || ["Processing capacity unavailable"]));

    summary.innerHTML = warnings.length
      ? '<span class="diagnostic-indicator warning"></span><strong>Diagnostics completed with warnings:</strong> ' + esc(warnings.join(" · "))
      : '<span class="diagnostic-indicator ok"></span><strong>Local hardware checked.</strong> Runtime and model-access details are listed below.';

    if (checked) checked.textContent = "Checked " + (report.checked_at ? new Date(report.checked_at).toLocaleTimeString() : "just now");
    if (raw) raw.textContent = JSON.stringify(report, null, 2);

    const status = el("systemStatus");
    if (status) {
      status.innerHTML = '<span class="dot" style="background:' + (warnings.length ? "#c58b22" : "#248a5a") +
        '"></span> ' + (warnings.length ? "System check · warnings" : "System ready");
    }
  };

  const showError = (message) => {
    const summary = el("diagnosticsSummary");
    const grid = el("diagnosticsGrid");
    const raw = el("diagnosticsRaw");
    if (summary) summary.innerHTML = '<span class="diagnostic-indicator error"></span><strong>Diagnostics failed:</strong> ' + esc(message);
    if (grid) grid.innerHTML = card("Diagnostics", "error", [message, "Check the OpenDub terminal for the startup report."]);
    if (raw) raw.textContent = message;
    const status = el("systemStatus");
    if (status) status.innerHTML = '<span class="dot" style="background:#c94b5a"></span> Diagnostics unavailable';
    console.error("[OpenDub diagnostics] " + message);
  };

  let cachedReport = null;
  let pendingCheck = null;
  const check = (fresh = false) => {
    if (!fresh && cachedReport) { render(cachedReport); return Promise.resolve(cachedReport); }
    if (pendingCheck) return pendingCheck;
    pendingCheck = performCheck(fresh).finally(() => { pendingCheck = null; });
    return pendingCheck;
  };
  const performCheck = async (fresh) => {
    const summary = el("diagnosticsSummary");
    if (summary) summary.innerHTML = '<span class="diagnostic-spinner"></span> Checking local hardware and runtime…';
    try {
      const started = performance.now();
      const response = await fetch("/api/system/diagnostics?fresh=" + (fresh ? "1" : "0") + "&ts=" + Date.now(), {
        cache: "no-store",
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) {
        throw new Error("Diagnostics API returned HTTP " + response.status);
      }
      const report = await response.json();
      cachedReport = report;
      report._ui_response_ms = Math.round((performance.now() - started) * 100) / 100;
      render(report);
      console.info("[OpenDub diagnostics] UI received report in " + report._ui_response_ms + " ms", report);
    } catch (error) {
      showError(error instanceof Error ? error.message : String(error));
    }
  };

  const boot = () => {
    window.refreshStudioDiagnostics = (fresh = false) => check(fresh);
    el("downloadSupportBundleBtn")?.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/system/support-bundle?ts=" + Date.now());
        if (!res.ok) throw new Error("HTTP " + res.status);
        const bundle = await res.json();
        const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `opendub-support-bundle-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        alert("Failed to download support bundle: " + (err instanceof Error ? err.message : String(err)));
      }
    });
    check(false);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
