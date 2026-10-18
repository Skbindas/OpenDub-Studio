function filterLibraryVoices(rows, query = "", mode = "all") {
  const needle = String(query).trim().toLocaleLowerCase();
  return rows.filter(v => v.sample_available !== false)
    .filter(v => [v.display_name,v.character_name,v.character_id].filter(Boolean).join(" ").toLocaleLowerCase().includes(needle))
    .filter(v => mode === "all" || (mode === "audition" && v.clone?.status === "completed") || (mode === "accepted" && v.audition_accepted) || (mode === "blocked" && v.selection_blockers?.length));
}
/* Reference evidence and cloned auditions are distinct. No automatic promotion. */
(() => {
  let voices = [];
  const list = document.getElementById("voiceLibraryList");
  const summary = document.getElementById("voiceLibrarySummary");
  const button = document.getElementById("loadVoiceLibraryBtn");
  const search = document.getElementById("voiceLibrarySearch");
  const filter = document.getElementById("voiceLibraryFilter");
  const labels = {not_audited:"Not audited", needs_review:"Review required", single_speaker_candidate:"Single speaker candidate",
    multiple_speakers:"Multiple speakers", overlapping_speakers:"Overlapping voices", rejected_no_speech:"No reliable speech",
    rejected_non_speech:"Non-speech reference", audit_failed:"Audit failed"};
  function option(value, selected) { return `<option value="${value}" ${selected === value ? "selected" : ""}>${value.replaceAll("_", " ")}</option>`; }
  function repairLabel(repair) {
    const context = /context-(\d+)/.exec(repair.version || "");
    return `${repair.speaker_id}${context ? ` · source context ${context[1]}s` : ""}`;
  }
  function contentHint(clone) {
    const check = clone?.content_check;
    if (!check) return "Content check pending; listen before approval.";
    return check.substantial_omission_suspected
      ? "Substantial missing speech suspected. Compare a repaired audition before approval."
      : "No substantial missing speech detected. Confirm pronunciation and similarity by listening.";
  }
  function render() {
    const shown = filterLibraryVoices(voices, search.value, filter.value);
    list.querySelectorAll('audio').forEach(audio => audio.pause());
    list.innerHTML = shown.map(v => {
      const status = v.audit?.status || "not_audited";
      const review = v.review || {};
      const repair = (v.repairs || []).find(r => r.clone_audio_url && r.audit?.status === "single_speaker_candidate" && r.clone?.reference_sha256 === r.sha256 && !r.clone?.content_check?.substantial_omission_suspected && !r.clone?.content_check?.substantial_addition_suspected);
      const checks = [["single_speaker","Only one speaker"],["speech_present","Real speech present"],
        ["background_clean","No audible music or effects"],["identity_confirmed","Source identity checked"],
        ["clone_identity_passed","Clone sounds like reference"],["naturalness_passed","Clone speech sounds natural"],
        ["dialogue_content_passed","Clone speaks every requested word"]];
      return `<article class="voice-library-card"><h3>${escapeHtml(v.display_name || v.character_name)}</h3>
        <label class="voice-direct-sample">Original reference<audio controls preload="none" aria-label="${escapeHtml(v.display_name)} original reference" src="${escapeHtml(v.audio_url)}"></audio></label>
        <button class="ghost pick-library-voice" data-voice-id="${escapeHtml(v.character_id)}" ${v.selection_blockers?.length ? "disabled" : ""}>Choose for a character</button>
        ${v.audit?.method === "user_reviewed_upload" ? `<p class="hint">Your source review · automatic ASR and speaker analysis have not been run.</p>` : ""}
        <p class="character-meta">${v.audition_accepted ? "Audition accepted" : "Listening review pending"} · ${escapeHtml(v.perceived_voice?.type || "Voice type unreviewed")}</p>
        ${v.selection_blockers?.length ? `<p class="voice-warning">Needs repair: ${v.selection_blockers.map(x=>escapeHtml(labels[x] || x.replaceAll("_", " "))).join(" · ")}</p>` : ""}
        <p class="voice-review-status">${escapeHtml(labels[status] || status)}. ${v.eligible_for_defaults ? "Verified default candidate" : "Not ready for defaults"}</p>
        <p class="hint">${Number(v.duration_sec || 0).toFixed(1)}s reference. Detected speakers: ${v.audit?.speaker_count_detected ?? "not checked"}.</p>
        ${v.selection_blockers?.length && repair ? `<div class="repair-audition"><strong>Separate-speaker repair audition</strong><p class="hint">A new candidate is available. Listen before selecting; the old reference stays intact.</p><audio controls preload="none" aria-label="${escapeHtml(v.display_name)} repaired audition" src="${escapeHtml(repair.clone_audio_url)}"></audio><button class="ghost review-repair" data-choice="${escapeHtml(repair.version)}/${repair.index}">Review this repair</button></div>` : ""}
        <details class="voice-evidence"><summary>Reference, repairs & quality evidence</summary>
        <p class="hint">Source catalog label (unverified): ${escapeHtml(v.character_name)} · ${escapeHtml(v.character_id)}</p>
        <label>Existing reference · background may be present<audio controls preload="none" src="${escapeHtml(v.audio_url)}"></audio></label>
        ${v.source_audio_url ? `<label>Original movie excerpt · dialogue, music & effects<audio controls preload="none" src="${escapeHtml(v.source_audio_url)}"></audio></label>` : ''}
        ${(v.repairs || []).map(r=>r.audio_url ? `<label>Repaired ${escapeHtml(repairLabel(r))} · identity needs review<audio controls preload="none" src="${escapeHtml(r.audio_url)}"></audio></label>${r.clone_audio_url ? `<label>Genuine audition from repaired ${escapeHtml(repairLabel(r))} · identity needs review<audio controls preload="none" src="${escapeHtml(r.clone_audio_url)}"></audio></label><p class="hint">${contentHint(r.clone)}</p>` : ''}` : `<p class="hint">${escapeHtml(repairLabel(r))}: another clean source interval is needed.</p>`).join('')}
        </details>
        ${v.clone?.status === "completed" && v.clone?.reference_conditioned ? `<label>Genuine cloned audition<audio controls preload="none" src="/api/voices/${encodeURIComponent(v.character_id)}/clone-preview"></audio></label>` : `<p class="hint">Current reference has no cloned audition.${(v.repairs || []).some(r=>r.clone_audio_url) ? ' Repaired-speaker auditions are available above.' : ''}</p>`}
        ${v.clone?.status === "completed" ? `<p class="hint">Vocals only. The final dub adds the preserved original music and effects.${v.audition_accepted ? ' Your audition review is saved.' : ''}</p>` : ''}
        ${v.clone?.status === "completed" && !v.audition_accepted ? `<p class="hint">${contentHint(v.clone)}</p>` : ''}
        ${v.clone?.text ? `<p class="hint">Requested dialogue: ${escapeHtml(v.clone.text)}</p>` : ''}
        ${v.clone?.content_check ? `<p class="hint">Automatic transcript: ${escapeHtml(v.clone.content_check.transcript)}. Confirm the actual words by listening.</p>` : ''}
        <details><summary>Review voice quality and apparent age</summary>
          ${(v.repairs || []).some(r=>r.clone_audio_url) ? `<label>Reference to review<select data-review="repair_choice"><option value="">Current reference</option>${v.repairs.filter(r=>r.clone_audio_url).map(r=>`<option value="${escapeHtml(r.version)}/${r.index}">${escapeHtml(repairLabel(r))}</option>`).join('')}</select></label>` : ''}
          <p class="hint">Catalog labels are unverified. Exact age cannot be established from sound.</p>
          <label>Perceived voice type<select data-review="perceived_type">${["unknown","masculine","feminine","androgynous"].map(x=>option(x,v.perceived_voice?.type)).join("")}</select></label>
          <label>Apparent age band<select data-review="age_band">${["unknown","toddler","child","adolescent","young_adult","adult","middle_aged","older"].map(x=>option(x,v.perceived_voice?.age_band)).join("")}</select></label>
          ${checks.map(([key,label])=>`<label class="voice-review-check"><input type="checkbox" data-review="${key}" ${review[key] ? "checked" : ""}>${label}</label>`).join("")}
          <label>Review notes<textarea data-review="notes" maxlength="2000">${escapeHtml(review.notes || "")}</textarea></label>
          <label>Exact reference words<textarea data-review="reference_text" maxlength="4000">${escapeHtml(v.audit?.speech_text || "")}</textarea></label>
          <button class="ghost save-voice-review" data-voice-id="${escapeHtml(v.character_id)}" ${status === "not_audited" ? "disabled" : ""}>Save review</button>
          <p class="hint" role="status"></p></details></article>`;
    }).join("") || (voices.some(v=>v.sample_available!==false) ? '<p>No matching voices. Use Browse all to clear filters.</p>' : '<p>No installed references yet. Add your own recording above.</p>');
    list.querySelectorAll('.pick-library-voice').forEach(btn => btn.addEventListener('click',()=>{
      window.SpeakerWorkflow?.pickVoice(btn.dataset.voiceId);
    }));
    list.querySelectorAll('audio').forEach(audio=>audio.addEventListener('play',()=>{
      document.querySelectorAll('audio, video').forEach(other=>{if(other!==audio)other.pause();});
    }));
    list.querySelectorAll(".review-repair").forEach(btn => btn.addEventListener("click", () => {
      const card = btn.closest("article"), select = card.querySelector('[data-review="repair_choice"]');
      if(select){ select.closest("details").open = true; select.value = btn.dataset.choice; select.dispatchEvent(new Event("change")); select.focus(); }
    }));
    list.querySelectorAll(".save-voice-review").forEach(btn => btn.addEventListener("click", async () => {
      const card = btn.closest("article"), feedback = btn.nextElementSibling, body = {};
      card.querySelectorAll("[data-review]").forEach(input => { body[input.dataset.review] = input.type === "checkbox" ? input.checked : input.value; });
      if(body.repair_choice) { const [version,index]=body.repair_choice.split('/'); body.reference_version=version; body.reference_index=Number(index); }
      delete body.repair_choice;
      btn.disabled = true;
      try { await api(`/api/voices/${encodeURIComponent(btn.dataset.voiceId)}/review`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); feedback.textContent = "Review saved. Refresh library for current readiness."; }
      catch(error) { feedback.textContent = error.message; }
      finally { btn.disabled = false; }
    }));
    list.querySelectorAll('[data-review="repair_choice"]').forEach(select=>select.addEventListener('change',()=>{
      const card=select.closest('article'), voice=voices.find(v=>v.character_id===card.querySelector('.save-voice-review').dataset.voiceId);
      const chosen=(voice.repairs || []).find(r=>`${r.version}/${r.index}`===select.value);
      card.querySelector('[data-review="reference_text"]').value=chosen?.audit?.speech_text || voice.audit?.speech_text || '';
      card.querySelectorAll('input[type="checkbox"][data-review]').forEach(input=>{input.checked=false;});
    }));
  }
  async function loadLibrary() {
    button.disabled = true; summary.textContent = "Loading saved voice evidence...";
    try {
      const bank = await api("/api/voices/bank"); voices = bank.voices;
      summary.textContent = `${bank.voices.filter(v=>v.sample_available!==false).length} installed samples · ${bank.total} catalog entries · ${bank.verified} verified default candidates · ${bank.clone_runtime.completed_auditions || 0} cloned auditions · ${bank.accepted_auditions || 0} accepted auditions · ${bank.repaired_auditions || 0} repaired-speaker auditions.`;
      render();
    } catch(error) { summary.textContent = "Library unavailable: " + error.message; list.replaceChildren(); }
    finally { button.disabled = false; }
  }
  button.addEventListener('click',()=>{search.value='';filter.value='all';return loadLibrary();});
  window.addEventListener('opendub:voice-library-changed',loadLibrary);
  loadLibrary();
  search.addEventListener("input", render);
  filter.addEventListener("change", render);
})();
