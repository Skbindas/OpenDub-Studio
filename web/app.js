const state = {
  projects: [],
  selected: localStorage.getItem("opendub:selectedProject"),
  poller: null,
  sound: false,
  autoDubPoller: null,
  autoDubStartTime: null,
  autoDownloadedRuns: new Set(),
  isAutoDubbing: false
};

const AUTO_DUB_STAGES = [
  {
    index: 1,
    key: "frame_audio_extraction",
    title: "Frame & Audio Extraction",
    activeLabel: "Extracting frames & probing audio stems..."
  },
  {
    index: 2,
    key: "language_detection",
    title: "Automatic Source Language Detection",
    activeLabel: "Auto-detecting source language via Whisper ASR..."
  },
  {
    index: 3,
    key: "character_voice_matching",
    title: "Speaker Identity & Voice Assignment",
    activeLabel: "Matching speaker identities and assigned voices..."
  },
  {
    index: 4,
    key: "hindi_translation",
    title: "Hindi Dialogue Translation & Prosody",
    activeLabel: "Translating & adapting dialogue into natural Hindi..."
  },
  {
    index: 5,
    key: "multi_character_tts",
    title: "Multi-Character Neural TTS Generation",
    activeLabel: "Generating multi-character neural Hindi speech..."
  },
  {
    index: 6,
    key: "vocal_removal_render",
    title: "Background Separation, Mix & Video Render",
    activeLabel: "Muting original dialogue (preserving BGM/SFX) & rendering master video..."
  }
];

function normalizeLanguageCode(lang){
  const s = String(lang || "").trim().toLowerCase();
  const map = {
    "auto": "auto", "auto detect": "auto",
    "hindi": "hi", "hi": "hi",
    "english": "en", "en": "en",
    "korean": "ko", "ko": "ko",
    "chinese": "zh", "zh": "zh",
    "japanese": "ja", "ja": "ja",
    "spanish": "es", "es": "es",
    "french": "fr", "fr": "fr",
    "german": "de", "de": "de",
    "russian": "ru", "ru": "ru"
  };
  return map[s] || (s.length === 2 ? s : "auto");
}

function formatAutoDubTime(totalSeconds){
  const s = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const m = Math.floor(s / 60);
  const remSec = s % 60;
  return `${String(m).padStart(2, "0")}m ${String(remSec).padStart(2, "0")}s`;
}

const $ = (id) => document.getElementById(id);

function beep(type="click"){
  if(!state.sound) return;
  try{
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type="sine"; o.frequency.value = type==="done" ? 760 : 520;
    g.gain.value = .035; o.connect(g); g.connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + (type==="done" ? .12 : .06));
  }catch{}
}

async function api(url, options={}){
  const res = await fetch(url, options);
  if(!res.ok){
    let detail = "Request failed";
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

function formatBytes(bytes=0){
  if(bytes < 1024) return bytes+" B";
  const units=["KB","MB","GB","TB"]; let n=bytes/1024, i=0;
  while(n>=1024 && i<units.length-1){n/=1024;i++}
  return n.toFixed(n>=100?0:1)+" "+units[i];
}

function formatDuration(ms){
  if(!ms) return "-";
  const s=Math.floor(ms/1000), h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60;
  return h ? `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}` : `${String(m).padStart(2,"0")}:${String(sec).padStart(2,"0")}`;
}

function formatGiB(bytes){
  if(bytes===null||bytes===undefined||!Number.isFinite(Number(bytes))) return "Unavailable";
  return (Number(bytes)/1073741824).toFixed(1)+" GB";
}

function diagnosticCard(title,status,lines){
  const label=status==="ok"?"Ready":status==="missing"?"Missing":status==="error"?"Error":status==="warning"?"Warning":"Info";
  return '<article class="diagnostic-card"><div class="diagnostic-card-head"><strong>'+escapeHtml(title)+'</strong><span class="diagnostic-state '+escapeHtml(status||"info")+'">'+label+'</span></div>'+lines.map(line=>'<div class="diagnostic-value">'+escapeHtml(line||"-")+'</div>').join("")+'</article>';
}

async function loadDiagnostics(fresh=false){
  return window.refreshStudioDiagnostics?.(fresh);
}

function openDiagnosticsModal(){
  const modal=$("diagnosticsModal");
  if(!modal) return;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden","false");
  loadDiagnostics();
}
function closeDiagnosticsModal(){
  const modal=$("diagnosticsModal");
  if(!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden","true");
}

function renderProjects(){
  const list=$("projectList");
  if(!state.projects.length){
    list.innerHTML='<div class="project-meta" style="padding:15px 6px">No projects yet.</div>';
    $("emptyState").classList.remove("hidden"); $("projectPanel").classList.add("hidden"); return;
  }
  list.innerHTML=state.projects.map(p=>`
    <button type="button" class="project-item ${state.selected===p.id?"active":""}" aria-pressed="${state.selected===p.id}" data-id="${p.id}">
      <div class="project-name">${escapeHtml(p.name)}</div>
      <div class="project-meta">${escapeHtml(p.status)} · ${formatDuration(p.duration_ms)}</div>
    </button>`).join("");
  list.querySelectorAll(".project-item").forEach(el=>el.onclick=()=>selectProject(el.dataset.id));
  $("emptyState").classList.toggle("hidden",!!state.selected);
  $("projectPanel").classList.toggle("hidden",!state.selected);
}

function escapeHtml(v){
  return String(v??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m]));
}

async function loadCharacters(){
  if(!state.selected) return;
  const list=$("characterList");
  if(!list) return;
  try{
    const projectId=state.selected;
    const data=await api("/api/projects/"+projectId+"/characters");
    if(state.selected !== projectId) return;
    const characters=Array.isArray(data.characters)?data.characters:[];
    if(data.status==="setup_required" || data.status==="skipped"){
      const needsAccess=data.status==="setup_required";
      list.innerHTML=
        '<div class="character-notice '+(needsAccess?"skipped":"info")+'">'+
        '<div class="character-notice-title">'+(needsAccess?"Speaker diarization access is required":"Speaker identification is currently skipped")+'</div>'+
        '<div class="character-notice-body">'+escapeHtml(data.notice||"Speaker diarization did not produce speaker clusters.")+'</div>'+
        (needsAccess?'<div class="character-notice-actions"><a class="ghost" href="'+escapeHtml(data.model_url||"https://huggingface.co/pyannote/speaker-diarization-community-1")+'" target="_blank" rel="noopener">Open Hugging Face Community-1</a></div>': '<div class="character-notice-actions"><button id="openDiarizationBtn" class="ghost">Open Speaker Identification</button></div>')+
        '</div>';
      const openBtn=$("openDiarizationBtn");
      if(openBtn) openBtn.onclick=()=>{
        const btn=$("diarizeBtn");
        if(btn){btn.scrollIntoView({behavior:"smooth",block:"center"});btn.focus();}
      };
      return;
    }
    if(!characters.length){
      list.innerHTML='<div class="character-notice info"><div class="character-notice-title">No character registry yet</div><div class="character-notice-body">Run speaker diarization first, then use “Sync Speakers” to create global character records.</div></div>';
      return;
    }

    // Update Global Character List
    list.innerHTML=characters.map(ch=>{
      const review=ch.review_required!==false;
      const aliases=(ch.aliases||[]).join(", ") || "None";
      return '<article class="character-card">'+
        '<div class="section-head compact"><div><strong>'+escapeHtml(ch.display_name||ch.source_speaker_id||"Character")+'</strong>'+
        '<div class="character-meta">'+escapeHtml(ch.source_speaker_id||"Unknown speaker")+' · '+(review?"Review required":"Reviewed")+'</div></div></div>'+
        '<div class="character-fields">'+
        '<label>Name<input data-character-field="display_name" data-character-id="'+escapeHtml(ch.character_id)+'" value="'+escapeHtml(ch.display_name||"")+'"></label>'+
        '<label>Type<select data-character-field="character_type" data-character-id="'+escapeHtml(ch.character_id)+'">'+
        ["unknown","adult","child","animal","creature","narrator","other"].map(type=>'<option value="'+type+'" '+(ch.character_type===type?"selected":"")+'>'+({'unknown':'Not classified','adult':'Adult','child':'Child','animal':'Animal','creature':'Creature','narrator':'Narrator','other':'Other'}[type])+'</option>').join("")+
        '</select></label>'+
        '<label>Notes<textarea data-character-field="notes" data-character-id="'+escapeHtml(ch.character_id)+'" rows="2">'+escapeHtml(ch.notes||"")+'</textarea></label>'+
        '<div class="character-voice-fields"><strong>Voice Assignment</strong>'+
        '<label>Provider<select data-voice-field="provider" data-character-id="'+escapeHtml(ch.character_id)+'">'+
        [["","Not assigned"],["piper","Piper (local)"],["cloned","Reviewed clone"],["openai_compatible","OpenAI-compatible (metadata)"],["custom","Custom (metadata)"]].map(([value,label])=>'<option value="'+value+'" '+((ch.voice_profile||{}).provider===value?"selected":"")+'>'+label+'</option>').join("")+
        '</select></label>'+
        '<label>Voice ID<input data-voice-field="voice_id" data-character-id="'+escapeHtml(ch.character_id)+'" value="'+escapeHtml((ch.voice_profile||{}).voice_id||"")+'" placeholder="Provider voice identifier"></label>'+
        '<label>Piper model path<input data-voice-field="model_path" data-character-id="'+escapeHtml(ch.character_id)+'" value="'+escapeHtml((ch.voice_profile||{}).model_path||"")+'" placeholder="voices/hi.onnx"></label>'+
        '<label>Language<input data-voice-field="language" data-character-id="'+escapeHtml(ch.character_id)+'" value="'+escapeHtml((ch.voice_profile||{}).language||"")+'" placeholder="Hindi"></label>'+
        '<div class="character-meta">Voice status: '+escapeHtml((ch.voice_profile||{}).status||"not_configured")+'. Provider selection stores configuration metadata; it does not install a provider or store API credentials.</div></div>'+
        '<div class="character-meta">Aliases: '+escapeHtml(aliases)+'</div>'+
        '<button class="ghost save-character" data-character-id="'+escapeHtml(ch.character_id)+'">Save Character</button>'+
        '</div></article>';
    }).join("");

    list.querySelectorAll(".save-character").forEach(btn=>{
      btn.onclick=async()=>{
        const id=btn.dataset.characterId;
        const values={};
        list.querySelectorAll('[data-character-id="'+CSS.escape(id)+'"][data-character-field]').forEach(field=>{
          values[field.dataset.characterField]=field.value;
        });
        const voice={...(characters.find(ch=>ch.character_id===id)?.voice_profile||{})};
        list.querySelectorAll('[data-character-id="'+CSS.escape(id)+'"][data-voice-field]').forEach(field=>{
          voice[field.dataset.voiceField]=field.value.trim()||null;
        });
        values.voice_profile=voice;
        btn.disabled=true;
        try{ await api("/api/projects/"+state.selected+"/characters/"+id,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(values)}); await loadCharacters(); }
        catch(e){ alert("Character save failed: "+e.message); }
        finally{ btn.disabled=false; }
      };
    });

    // Also populate Voice Cloning Studio Character Library Grid


  }catch(e){
    console.warn("[OpenDub characters] "+e.message);
    list.innerHTML='<div class="character-meta">Character registry unavailable: '+escapeHtml(e.message)+'</div>';
  }
}

function formatSpeechTime(seconds){
  const ms = Math.max(0, Math.round(Number(seconds || 0) * 1000));
  const whole = Math.floor(ms / 1000);
  return `${String(Math.floor(whole / 60)).padStart(2,"0")}:${String(whole % 60).padStart(2,"0")}.${String(ms % 1000).padStart(3,"0")}`;
}

async function addCharacter(){
  if(!state.selected) return;
  const name=$("newCharacterName").value.trim();
  if(!name){$("newCharacterName").focus();return;}
  try{
    await api('/api/projects/'+state.selected+'/characters',{method:'POST',body:JSON.stringify({display_name:name})});
    $("newCharacterName").value='';
    await loadCharacters();
  }catch(e){alert(e.message);}
}

async function syncCharacters(){
  if(!state.selected) return;
  const btn=$("syncCharactersBtn");
  const old=btn?.textContent;
  if(btn){btn.disabled=true;btn.textContent="Syncing…";}
  try{
    const result=await api("/api/projects/"+state.selected+"/characters/sync",{method:"POST"});
    await loadCharacters();
    if(result.status==="skipped") console.info("[OpenDub characters] Speaker sync skipped:",result.notice||"Diarization not configured.");
  }catch(e){
    alert("Speaker sync failed: "+e.message);
  }finally{
    if(btn){btn.disabled=false;btn.textContent=old||"Sync Speakers";}
  }
}

async function loadProjects(){
  state.projects=await api("/api/projects");
  if(state.selected && !state.projects.some(p=>p.id===state.selected)) state.selected=null;
  if(!state.selected && state.projects.length) state.selected=state.projects[0].id;
  renderProjects();
  if(state.selected){ await refreshSelected(); await loadCharacters().catch(()=>{}); }
}

async function selectProject(id){
  stopAutoDubPoller(); state.isAutoDubbing=false;
  document.querySelectorAll("audio, video").forEach(player => { player.pause(); player.removeAttribute("src"); player.load(); });
  $("transcriptView").innerHTML=""; $("transcriptView").dataset.kind=""; $("transcriptView").classList.add("hidden");
  $("characterList").innerHTML="";
  $("downloadRender").classList.add("hidden");
  $("qaReportBadge").classList.add("hidden");
  state.selected=id; localStorage.setItem("opendub:selectedProject",id); beep(); renderProjects(); await refreshSelected();
}

function pipelineStateBadge(stage){
  const map={
    completed:["done","Done"],
    review_required:["review","Review"],
    not_started:["pending","Pending"],
    blocked:["blocked","Blocked"]
  };
  const value=map[stage.status]||["pending",stage.status||"Pending"];
  return '<span class="pipeline-state-pill '+value[0]+'">'+escapeHtml(value[1])+'</span>';
}

async function loadPipelineState(){
  if(!state.selected) return;
  try{
    const projectId=state.selected;
    const data=await api("/api/projects/"+projectId+"/pipeline/state");
    if(state.selected !== projectId) return;
    const list=$("pipelineStateStages"), next=$("pipelineNext");
    if(list){
      list.innerHTML=(data.stages||[]).map(stage=>
        '<div class="pipeline-state-item">'+
          '<span class="pipeline-state-index">'+escapeHtml(String((data.stages||[]).indexOf(stage)+1))+'</span>'+
          '<span class="pipeline-state-label">'+escapeHtml(stage.label)+'</span>'+
          pipelineStateBadge(stage)+
        '</div>'
      ).join("");
    }
    if(next){
      const n=data.next_recommended;
      next.innerHTML=n
        ? '<b>Next recommended:</b> '+escapeHtml(n.label)+' <span>· '+escapeHtml(n.detail||"")+'</span>'
        : '<b>Pipeline complete.</b>';
    }
    return data;
  }catch(e){
    console.warn("[OpenDub pipeline] "+e.message);
  }
}

async function loadFullAnalysis(){
  if(!state.selected) return false;
  if($("transcriptView").dataset.kind === "translation" && $("transcriptView").dataset.projectId === state.selected) return true;
  try{
    const projectId=state.selected;
    const data=await api("/api/projects/"+projectId+"/analysis?limit=250");
    if(state.selected !== projectId) return false;
    const summary=data.summary||{}, statuses=data.stage_status||{}, view=$("transcriptView");
    const source=summary.source_media||{};
    $("timelineBadge").textContent="Full analysis ready";
    $("timelineBadge").className="status-chip";

    await loadCharacters().catch(()=>{});
    if(!view) return true;
    view.classList.remove("hidden");
    const statusRows=Object.entries(statuses).map(([name,status])=>
      '<span class="analysis-stage '+escapeHtml(status||"unknown")+'">'+escapeHtml(name.replaceAll("_"," "))+
      ' · '+escapeHtml(status||"unknown")+'</span>').join(" ");
    const segmentRows=(data.segments||[]).slice(0,120).map(x=>
      '<div class="transcript-row"><time>'+formatDuration((x.start_sec||0)*1000)+' - '+formatDuration((x.end_sec||0)*1000)+'</time>'+
      '<span><b>'+escapeHtml(x.speaker_id||"Speaker review")+'</b> · '+escapeHtml(x.text||"")+
      (x.speaker_confidence!=null?' <small>speaker '+Math.round(Number(x.speaker_confidence)*100)+'%</small>':'')+
      '</span></div>').join("");
    const gaps=(summary.analysis_gaps||[]).map(x=>'<li>'+escapeHtml(x)+'</li>').join("");
    view.innerHTML=
      '<h3>Full Analysis · '+escapeHtml(summary.language||"language not detected")+'</h3>'+
      '<div class="analysis-summary-grid">'+
      '<div><strong>Scenes</strong><span>'+Number(summary.scenes||0)+'</span></div>'+
      '<div><strong>Dialogue segments</strong><span>'+Number(summary.segments||0)+'</span></div>'+
      '<div><strong>Source</strong><span>'+escapeHtml(source.format_name||"unknown")+'</span></div>'+
      '<div><strong>Duration</strong><span>'+formatDuration(Number(source.duration_sec||0)*1000)+'</span></div>'+
      '</div>'+
      '<div class="analysis-stage-list">'+statusRows+'</div>'+
      (gaps?'<p class="hint"><b>Remaining analysis scopes</b></p><ul class="analysis-gaps">'+gaps+'</ul>':'')+
      '<div class="analysis-segment-list">'+segmentRows+'</div>'+
      (data.truncated?'<p class="hint">Showing the first 120 dialogue segments in the studio view. The persistent timeline contains the complete analysis.</p>':'');
    return true;
  }catch(e){
    if(e.message && !e.message.includes("Full analysis has not completed yet")) console.warn("[OpenDub analysis] "+e.message);
    return false;
  }
}

async function refreshSelected(){
  if(!state.selected) return;
  try{
    const projectId=state.selected;
    const p=await api("/api/projects/"+projectId);
    if(state.selected !== projectId) return;
    $("projectTitle").textContent=p.name;
    const targetSelect = $("targetLanguage");
    if(targetSelect){
      const normCode = normalizeLanguageCode(p.target_language || "hi");
      if(Array.from(targetSelect.options).some(o => o.value === normCode)){
        targetSelect.value = normCode;
      } else if(Array.from(targetSelect.options).some(o => o.value === p.target_language)){
        targetSelect.value = p.target_language;
      }
    }
    if(p.source_path){
      $("sourceInfo").innerHTML=`<div class="upload-icon">✓</div><strong>Movie uploaded</strong><span>${formatBytes(p.source_size)} · ${formatDuration(p.duration_ms)}</span>`;
    }
    else { $("sourceInfo").innerHTML='<div class="upload-icon">↑</div><strong>No movie uploaded</strong><span>MP4, MKV, MOV, AVI, WebM</span>'; }
    $("runAutoDubBtn").disabled = !p.source_path || state.isAutoDubbing;
    const latest=(p.jobs||[])[0];
    if(latest){
      const running=["queued","running","retrying"].includes(latest.status);
      $("jobProgress").classList.toggle("hidden",!running);
      $("jobPercent").textContent=Math.round((latest.progress||0)*100)+"%";
      $("jobBar").style.width=((latest.progress||0)*100)+"%";
      $("jobMessage").textContent=latest.message||latest.status;
      const cancelBtn=$("cancelJobBtn"); if(cancelBtn){cancelBtn.classList.toggle("hidden",!running);cancelBtn.dataset.jobId=latest.id||"";}
      if(latest.status==="completed"){ $("jobProgress").classList.remove("hidden"); $("timelineBadge").textContent="Analysis ready"; $("timelineBadge").className="status-chip"; beep("done");}
    }
    if(state.poller){ clearInterval(state.poller); state.poller=null; }
    if(latest && ["completed","failed","cancelled"].includes(latest.status)){ await loadFullAnalysis(); await translateTranscript({readOnly:true}); }
    await loadPipelineState();
    if(latest && ["queued","running","retrying"].includes(latest.status)){
      state.poller=setInterval(refreshSelected,1200);
    }
    await checkProjectAutoDubStatus(state.selected).catch(()=>{});
    await window.refreshStudioMedia?.();
  }catch(e){ console.error(e); }
}

function openModal(){ $("modal").classList.remove("hidden"); $("projectName").focus(); }
function closeModal(){ $("modal").classList.add("hidden"); }

async function createProject(){
  const name=$("projectName").value.trim() || "Untitled Dubbing Project";
  const target=$("modalTarget").value || "Hindi";
  const p=await api("/api/projects",{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({name,target_language:target,source_language:"auto"})
  });
  closeModal(); state.selected=p.id; localStorage.setItem("opendub:selectedProject",p.id); beep(); await loadProjects();
}

function setUploadProgress(percent, title, detail, stateLabel, loadedBytes=0, totalBytes=0){
  const wrap=$("uploadProgress"), bar=$("uploadProgressBar"), pct=$("uploadProgressPercent");
  const titleEl=$("uploadProgressTitle"), detailEl=$("uploadProgressDetail");
  const bytesEl=$("uploadProgressBytes"), stateEl=$("uploadProgressState");
  if(!wrap) return;
  wrap.classList.remove("hidden");
  wrap.dataset.state=stateLabel||"uploading";
  if(bar) bar.style.width=Math.max(0,Math.min(100,percent))+"%";
  if(pct) pct.textContent=Math.round(percent)+"%";
  if(titleEl) titleEl.textContent=title||"Uploading movie…";
  if(detailEl) detailEl.textContent=detail||"Transferring file to the project workspace";
  if(bytesEl){
    const shownLoaded=totalBytes ? Math.min(totalBytes,Math.max(0,loadedBytes)) : loadedBytes;
    bytesEl.textContent=totalBytes ? formatBytes(shownLoaded)+" / "+formatBytes(totalBytes) : "";
  }
  if(stateEl) stateEl.innerHTML='<span class="upload-spinner"></span>'+escapeHtml(stateLabel||"Uploading");
}

function finishUploadProgress(success, message){
  const wrap=$("uploadProgress");
  if(!wrap) return;
  wrap.dataset.state=success?"complete":"error";
  const bar=$("uploadProgressBar");
  if(bar) bar.style.width=(success?100:0)+"%";
  $("uploadProgressTitle").textContent=success?"Upload complete":"Upload failed";
  $("uploadProgressDetail").textContent=message||"";
  $("uploadProgressPercent").textContent=success?"100%":"-";
  $("uploadProgressState").innerHTML=success
    ? '<span class="upload-check">✓</span>Ready'
    : '<span class="upload-error">!</span>Error';
}

async function renameProject(){
  if(!state.selected) return;
  const current=$("projectTitle")?.textContent?.trim() || "";
  const name=prompt("Project name",current);
  if(name===null || !name.trim() || name.trim()===current) return;
  try{
    const updated=await api("/api/projects/"+state.selected,{
      method:"PATCH",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:name.trim()})
    });
    state.projects=state.projects.map(p=>p.id===updated.id?updated:p);
    renderProjects();
    await refreshSelected();
  }catch(e){alert("Rename failed: "+e.message)}
}

async function uploadMovie(file){
  if(!file) return;
  if(!state.selected){
    try{
      const cleanName = (file.name || "Movie").replace(/\.[^/.]+$/, "").trim() || "Dubbing Project";
      const newProj = await api("/api/projects", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: cleanName, target_language: "Hindi", source_language: "auto"})
      });
      state.selected = newProj.id;
      localStorage.setItem("opendub:selectedProject", newProj.id);
      await loadProjects();
    }catch(err){
      console.warn("[OpenDub upload] Auto-project creation failed, continuing:", err);
    }
  }
  if(!state.selected) return;
  const projectId=state.selected;
  const input=$("movieInput"), pickerLabel=$("moviePickerLabel"), card=document.querySelector(".upload-card");
  if(input) input.disabled=true;
  if(pickerLabel) pickerLabel.textContent="Uploading…";
  if(card) card.classList.add("uploading");
  setUploadProgress(0,"Uploading movie…","Preparing local transfer","Uploading",0,file.size);
  try{
    const res=await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open("POST","/api/projects/"+projectId+"/source");
      xhr.responseType="json";
      xhr.upload.onloadstart=()=>setUploadProgress(0,"Uploading movie…","Starting file transfer","Uploading",0,file.size);
      xhr.upload.onprogress=(event)=>{
        if(!event.lengthComputable) return;
        const percent=(event.loaded/event.total)*100;
        setUploadProgress(percent,"Uploading movie…","Transferring file to the project workspace","Uploading",Math.min(file.size,event.loaded),file.size);
      };
      xhr.upload.onload=()=>setUploadProgress(100,"Finalizing upload…","Server received the movie; saving project metadata","Processing",file.size,file.size);
      xhr.onload=()=>{
        if(xhr.status>=200 && xhr.status<300){
          resolve(xhr.response || JSON.parse(xhr.responseText||"{}"));
          return;
        }
        let message="Upload failed";
        try{ message=xhr.response?.detail || JSON.parse(xhr.responseText||"{}").detail || message; }catch(_){}
        reject(new Error(message));
      };
      xhr.onerror=()=>reject(new Error("Network error while uploading the movie."));
      xhr.onabort=()=>reject(new Error("Movie upload was cancelled."));
      const form=new FormData();
      form.append("file",file);
      form.append("source_language","auto");
      form.append("target_language","hi");
      xhr.send(form);
    });

    setUploadProgress(100,"Finalizing upload…","Refreshing the project and validating the uploaded source","Processing",file.size,file.size);
    state.projects=state.projects.map(p=>p.id===res.id?res:p);
    renderProjects();
    await refreshSelected();
    finishUploadProgress(true,"Movie is stored locally and ready for analysis.");
    beep("done");
    setTimeout(()=>{
      const wrap=$("uploadProgress");
      if(wrap) wrap.classList.add("hidden");
    },1800);

    if($("autoFullPipelineToggle")?.checked){
      runAutoDubPipeline(projectId).catch(err=>{
        console.error("[OpenDub Auto-Dub] Failed to start pipeline after upload:", err);
      });
    }
  }catch(e){
    finishUploadProgress(false,e.message);
    throw e;
  }finally{
    if(input) input.disabled=false;
    if(pickerLabel) pickerLabel.textContent="Choose Movie";
    if(card) card.classList.remove("uploading");
  }
}

function triggerFinalVideoAutoDownload(projectId, filename){
  if(!projectId) return;
  const projectTitle = $("projectTitle")?.textContent?.trim() || "movie";
  const safeTitle = projectTitle.replace(/[^a-zA-Z0-9_-]/g, "_");
  const downloadName = filename || (safeTitle + "_hindi_dubbed.mp4");
  const downloadUrl = "/api/projects/" + projectId + "/final-video?download=1";

  console.info("[OpenDub Auto-Dub] Triggering automatic download of final Hindi dubbed video:", downloadUrl);
  const a = document.createElement("a");
  a.href = downloadUrl;
  a.download = downloadName;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    try { a.remove(); } catch (_) {}
  }, 500);
}

// 3D Circular Progress Dial Update
function measuredDubProgress(data = {}){
  if(data.status === "completed" && data.auto_download_ready === true) return {label:"Ready to review", percent:100};
  if(data.status === "waiting") return {label:"Waiting for Kaggle", percent:null};
  if(data.status === "awaiting_review") return {label:"Your review needed", percent:null};
  if(["failed", "error", "cancelled"].includes(data.status)) return {label:"Stopped · work retained", percent:null};
  const work = data.work;
  if(work && Number.isFinite(work.total) && work.total > 0 && Number.isFinite(work.completed)){
    const completed = Math.max(0, Math.min(work.total, work.completed));
    return {label:`${work.phase || "Current step"} · ${completed}/${work.total}`, percent:100 * completed/work.total};
  }
  return {label:data.status === "running" ? "Processing current step" : "Ready", percent:null};
}

function updateAutoDubDashboard(data = {}, elapsedMs = 0){
  if(data.project_id && data.project_id !== state.selected) return;
  state.autoDubSnapshot = data;
  const done = data.status === "completed" && data.auto_download_ready === true;
  const failed = ["failed", "error", "cancelled"].includes(data.status);
  const active = ["running", "queued", "retrying"].includes(data.status);
  const awaitingReview=data.status === "awaiting_review";
  const providerWaiting=data.status === "waiting";
  const runButton = $("runAutoDubBtn");
  if(runButton){
    runButton.disabled = active || !state.projects.find(project => project.id === state.selected)?.source_path;
    runButton.textContent = active ? "Processing…" : awaitingReview ? "Continue with locked voices" : failed || providerWaiting ? "Resume Auto-Dub" : "Start Auto-Dub";
  }
  const measured = measuredDubProgress(data);
  const pct = measured.percent ?? 0;
  $("autoDubMonitorCard").dataset.status = data.status || "idle";
  $("autoDubPercent").textContent = measured.label;
  $("autoDubProgressBar").style.width = pct + "%";
  const progressTrack = $("autoDubProgressBar").parentElement;
  if(measured.percent === null) progressTrack.removeAttribute("aria-valuenow");
  else progressTrack.setAttribute("aria-valuenow", String(pct));
  progressTrack.setAttribute("aria-valuetext", measured.label);
  $("autoDubStageLabel").textContent = data.error || data.current_stage_label || data.stage_label || "Ready to start";
  $("autoDubElapsed").textContent = "Elapsed: " + formatAutoDubTime(data.elapsed_seconds ?? elapsedMs / 1000);
  $("autoDubEta").textContent = done ? "Render checked" : awaitingReview ? "Awaiting speaker and voice review · completed analysis retained" : providerWaiting ? "Kaggle waiting · completed tasks retained · inspect Processing location or choose local" : failed ? (data.failure_kind === "review" ? (data.current_stage === "vocal_removal_render" ? "Mix review required" : "Dialogue timing review required") : "Stopped · completed files retained") : Number.isFinite(data.eta_seconds) ? "Stage remaining: ≈ " + formatAutoDubTime(data.eta_seconds) : active ? "Stage estimate: calibrating…" : "Stage estimate available during processing";
  const workCount = $("autoDubWorkCount");
  if(workCount){
    const work = data.work;
    const count = value => Number(value).toLocaleString(undefined, {maximumFractionDigits: 1});
    workCount.textContent = work ? `${count(work.completed)}/${count(work.total)} ${work.unit} processed · ${count(work.remaining)} remaining` : "";
  }
  const capacity = $("autoDubCapacity");
  if(capacity){
    const plan = data.processing_plan;
    capacity.textContent = plan ? `${plan.heavy_workers} heavy-worker limit · ${plan.cpu_threads_per_worker} CPU threads each · ASR ${plan.asr_device.toUpperCase()} · ${plan.chunk_seconds}s planned chunks` : "Hardware capacity is checked before processing";
  }
  $("autoDubStageList").querySelectorAll("li").forEach((item, index) => {
    const status = data.stages?.[index]?.status || item.dataset.stageStatus || "pending";
    item.dataset.stageStatus = status;
    item.className = "auto-dub-stage-item is-" + (status === "running" ? "active" : status);
    item.querySelector(".stage-check-status").textContent = status === "failed" && data.failure_kind === "review" ? "Review required" : status.replaceAll("_", " ");
    item.querySelector(".stage-check-icon").textContent = status === "completed" ? "✓" : String(index + 1);
    let retry = item.querySelector(".stage-retry");
    if(["failed", "cancelled"].includes(status) && failed){
      if(!retry){
        retry = document.createElement("button");
        retry.className = "ghost stage-retry";
        retry.textContent = "Resume here";
        retry.onclick = () => runAutoDubPipeline(state.selected).catch(error => alert(error.message));
        item.appendChild(retry);
      }
      retry.disabled = active;
    }else if(retry){ retry.remove(); }
  });
  $("autoDubDownloadBtn").classList.toggle("hidden", !done);
  $("autoDubVideoPreviewWrap").classList.toggle("hidden", !done);
  if(done){
    const baseUrl = "/api/projects/" + data.project_id + "/final-video";
    const revision = String(data.rendered_video_revision || "");
    const url = baseUrl + (revision ? "?v=" + encodeURIComponent(revision) : "");
    $("autoDubDownloadBtn").href = baseUrl + "?download=1";
    if($("finalVideoPreview").dataset.loadedProject !== data.project_id || !$("finalVideoPreview").src || $("finalVideoPreview").dataset.loadedRevision !== revision){
      $("finalVideoPreview").src = url;
      $("finalVideoPreview").dataset.loadedProject = data.project_id;
      $("finalVideoPreview").dataset.loadedRevision = revision;
    }
  }
}

function stopAutoDubPoller(){
  if(state.autoDubPoller){
    clearInterval(state.autoDubPoller);
    state.autoDubPoller = null;
  }
}

async function runAutoDubPipeline(projectId){
  if(!projectId){
    alert("Please select or create a dubbing project first.");
    return;
  }
  if(state.isAutoDubbing){
    console.info("[OpenDub Auto-Dub] Pipeline is already running.");
    return;
  }

  state.isAutoDubbing = true;
  state.autoDubStartTime = Date.now();
  const runKey = projectId + "_" + state.autoDubStartTime;

  const runBtn = $("runAutoDubBtn");
  const oldBtnText = runBtn ? runBtn.innerHTML : "🚀 Start Full Auto-Dub & Render";
  if(runBtn){
    runBtn.disabled = true;
    runBtn.innerHTML = '<span class="upload-spinner"></span> Running Hindi dub…';
  }

  updateAutoDubDashboard({
    ...(state.autoDubSnapshot?.project_id === projectId ? state.autoDubSnapshot : {}),
    status: "queued",
    error: null,
    progress_percent: state.autoDubSnapshot?.project_id === projectId ? state.autoDubSnapshot.progress_percent : 0,
    stage_index: 1,
    current_stage_label: "Queueing request; completed work will be retained",
    project_id: projectId
  }, 0);

  const sourceLang = $("sourceLanguage")?.value || "auto";
  const targetLang = $("targetLanguage")?.value || "hi";
  const payload = {
    source_language: sourceLang === "Auto Detect" ? "auto" : sourceLang,
    target_language: normalizeLanguageCode(targetLang),
    target_language_name: targetLang,
    model_size: $("asrModel")?.value || "small",
    voice_model_path: $("voiceModelPath")?.value?.trim() || null,
    auto_download: Boolean($("autoFullPipelineToggle")?.checked),
    visible_helpers: Boolean($("visibleHelpersToggle")?.checked),
    separation_workers: $("separationWorkers")?.value ? Number($("separationWorkers").value) : null,
    preserve_bgm: true,
    mute_original_vocals: true,
    cleanup_intermediates: $("cleanupAfterRender") ? Boolean($("cleanupAfterRender").checked) : true
  };

  try{
    let autoDubEndpointAvailable = true;
    let initialRes = null;
    try{
      initialRes = await api("/api/projects/" + projectId + "/auto-dub", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
    }catch(apiErr){
      if(apiErr.message && (apiErr.message.includes("404") || apiErr.message.includes("Not Found"))){
        autoDubEndpointAvailable = false;
      } else {
        throw apiErr;
      }
    }

    if(!autoDubEndpointAvailable){
      console.info("[OpenDub Auto-Dub] /auto-dub endpoint not found; executing sequential pipeline fallback.");
      throw new Error("Auto-dub endpoint unavailable. Restart the backend before continuing.");
    }

    stopAutoDubPoller();
    await pollAutoDubStatus(projectId, runKey, initialRes);

  }catch(err){
    console.error("[OpenDub Auto-Dub] Pipeline failed:", err);
    state.isAutoDubbing = false;
    updateAutoDubDashboard({
      status: "failed",
      error: err.message,
      project_id: projectId
    }, Date.now() - (state.autoDubStartTime || Date.now()));
  }finally{
    state.isAutoDubbing = false;
    if(runBtn){
      runBtn.disabled = false;
      runBtn.innerHTML = oldBtnText;
    }
    if(state.selected === projectId){
      await checkProjectAutoDubStatus(projectId);
      await refreshSelected().catch(() => {});
    }
  }
}

async function pollAutoDubStatus(projectId, runKey, initialRes){
  return new Promise((resolve, reject) => {
    let consecutiveErrors = 0;
    const interval = 1500;

    const checkStatus = async () => {
      if(!state.isAutoDubbing){
        stopAutoDubPoller();
        resolve(null);
        return;
      }
      const elapsedMs = Date.now() - (state.autoDubStartTime || Date.now());
      try{
        const data = await api("/api/projects/" + projectId + "/auto-dub-status?ts=" + Date.now());
        consecutiveErrors = 0;
        if(state.selected !== projectId){ stopAutoDubPoller(); resolve(null); return; }
        data.project_id = projectId;
        updateAutoDubDashboard(data, elapsedMs);

        if(data.status === "awaiting_review"){stopAutoDubPoller();state.isAutoDubbing=false;await refreshSelected();await window.SpeakerWorkflow?.refresh();window.SpeakerWorkflow?.open();resolve(data);return;}
        const isComplete = data.status === "completed" && data.auto_download_ready === true;
        const isFailed = ["failed", "error", "cancelled"].includes(data.status);

        if(isComplete){
          stopAutoDubPoller();
          state.isAutoDubbing = false;
          beep("done");

          await refreshSelected().catch(() => {});
          await loadProjects().catch(() => {});
          await loadPipelineState().catch(() => {});
          await loadCharacters().catch(() => {});

          const autoDownloadEnabled = $("autoFullPipelineToggle") ? $("autoFullPipelineToggle").checked : true;
          if(autoDownloadEnabled && !state.autoDownloadedRuns.has(runKey)){
            state.autoDownloadedRuns.add(runKey);
            triggerFinalVideoAutoDownload(projectId, data.filename);
          }
          resolve(data);
          return;
        }

        if(isFailed){
          stopAutoDubPoller();
          state.isAutoDubbing = false;
          reject(new Error(data.error || data.message || "Auto-dubbing failed"));
          return;
        }
      }catch(err){
        consecutiveErrors++;
        console.warn("[OpenDub Auto-Dub] Polling error (" + consecutiveErrors + "):", err.message);
        if(consecutiveErrors > 20){
          stopAutoDubPoller();
          state.isAutoDubbing = false;
          reject(new Error("Lost connection while monitoring auto-dubbing: " + err.message));
        }
      }
    };

    checkStatus();
    state.autoDubPoller = setInterval(checkStatus, interval);
  });
}

async function checkProjectAutoDubStatus(projectId){
  if(!projectId) return;
  try{
    const res = await api("/api/projects/" + projectId + "/auto-dub-status?ts=" + Date.now());
    if(res && state.selected === projectId){
      res.project_id = projectId;
      updateAutoDubDashboard(res, res.elapsed_ms || 0);
      if(res.status === "running" || res.status === "queued"){
        if(!state.isAutoDubbing){
          state.isAutoDubbing = true;
          state.autoDubStartTime = Date.now() - (res.elapsed_ms || (res.elapsed_sec ? res.elapsed_sec * 1000 : 0));
          pollAutoDubStatus(projectId, projectId + "_resumed", res).catch(console.error);
        }
      } else if(res.status === "completed" && res.auto_download_ready){
        updateAutoDubDashboard(res, res.elapsed_ms || 0);
      }
    }
  }catch(e){}
}

async function onRunAutoDubClick(){
  if(state.isAutoDubbing){
    alert("Full auto-dubbing pipeline is already running.");
    return;
  }
  if(!state.selected){
    if(state.projects && state.projects.length > 0){
      await selectProject(state.projects[0].id);
    } else {
      const picker = $("movieInput");
      if(picker) picker.click();
      return;
    }
  }
  const curr = state.projects.find(p => p.id === state.selected);
  if(!curr || !curr.source_path){
    const picker = $("movieInput");
    if(picker) picker.click();
    return;
  }
  await runAutoDubPipeline(state.selected);
}

/* ==========================================================================
   🎛️ Audio Visualizer & 3-Stem Multi-Track Waveform Engine
   ========================================================================== */
$("cancelJobBtn")?.addEventListener("click",async()=>{
  const btn=$("cancelJobBtn"),jobId=btn?.dataset.jobId;
  if(!jobId)return;
  btn.disabled=true;btn.textContent="Cancelling…";
  try{
    const job=await api("/api/jobs/"+jobId+"/cancel",{method:"POST"});
    $("jobMessage").textContent=job.message||job.status;
    await refreshSelected();
  }catch(e){alert(e.message);}
  finally{btn.disabled=false;btn.textContent="Cancel job";}
});

async function runStage(stage){
  if(!state.selected) return;
  const btn=stage==='audio_extract'?$('extractAudioBtn'):stage==='scene_detect'?$('detectScenesBtn'):stage==='diarize'?$('diarizeBtn'):stage==='separate'?$('separateBtn'):$('transcribeBtn');
  const old=btn.textContent; btn.disabled=true; btn.textContent='Working…';
  try {
    const model=$('asrModel')?$('asrModel').value:'small';
    const url='/api/projects/'+state.selected+'/pipeline/'+stage+'?model_size='+encodeURIComponent(model)+'&device=auto';
    const res=await api(url,{method:'POST'});
    $('jobProgress').classList.remove('hidden');
    for(let i=0;i<720;i++){
      await new Promise(resolve=>setTimeout(resolve,1500));
      const j=await api('/api/jobs/'+res.job_id);
      $('jobMessage').textContent=j.message||j.status;
      $('jobPercent').textContent=Math.round((j.progress||0)*100)+'%';
      $('jobBar').style.width=((j.progress||0)*100)+'%';
      if(j.status==='completed'){ $('timelineBadge').textContent=stage.replaceAll('_',' ')+' complete'; await showStageResult(stage); await loadProjects(); beep('done'); break; }
      if(j.status==='failed'){ alert(j.message||'Pipeline stage failed'); break; }
    }
  } catch(e){alert(e.message)} finally{btn.disabled=false;btn.textContent=old}
}

async function showStageResult(stage){
  const view=$('transcriptView'); if(!view)return;
  try {
    const data=await api('/api/projects/'+state.selected+'/'+(stage==='transcribe'||stage==='diarize'?'transcript':stage==='separate'?'separation':'scenes'));
    view.classList.remove('hidden');
    if(stage==='separate'){view.innerHTML='<h3>Separation result · '+escapeHtml(data.status||'unknown')+'</h3><div class="transcript-row"><b>Method</b><span>'+escapeHtml(data.method||'-')+'</span></div><div class="transcript-row"><b>Dialogue candidate</b><span>'+escapeHtml(data.dialogue_candidate||'-')+'</span></div><div class="transcript-row"><b>Background candidate</b><span>'+escapeHtml(data.background_candidate||'Not produced')+'</span></div><p class="hint">'+escapeHtml(data.notice||'')+'</p>'}else if(stage==='transcribe'||stage==='diarize'){view.innerHTML='<h3>Transcript draft · '+escapeHtml(data.language||'detected')+'</h3>'+data.segments.map(x=>'<div class=\"transcript-row\"><time>'+formatDuration(x.start*1000)+' - '+formatDuration(x.end*1000)+'</time><span>'+escapeHtml(x.text)+'</span></div>').join('')}
    else{view.innerHTML='<h3>Visual cut boundaries · '+data.length+'</h3>'+data.slice(0,250).map(x=>'<div class=\"transcript-row\"><time>Cut '+(x.scene_index+1)+'</time><span>'+formatDuration(x.start_sec*1000)+'</span></div>').join('')}
  }catch(e){console.warn(e)}
}

async function loadAdaptationHistory(index,panel,view){
  const data=await api("/api/projects/"+state.selected+"/dialogue/"+index+"/adaptation/history");
  if(!data.events?.length){panel.innerHTML='<div class="history-empty">No review history recorded for this dialogue yet.</div>';return;}
  panel.innerHTML='<strong class="history-heading">Review history · '+data.events.length+' revision(s)</strong>'+
    data.events.map(event=>{
      const decision=String(event.decision||"unknown"),approved=decision==="approved",revision=Number(event.revision||0);
      return '<article class="history-event"><div class="history-event-head"><b>Revision '+revision+'</b><span class="history-decision '+(approved?'approved':'rejected')+'">'+escapeHtml(decision)+'</span>'+
        (event.restored_from_revision?'<span class="history-restored">Restored from #'+Number(event.restored_from_revision)+'</span>':'')+'</div>'+
        '<div class="history-event-text">'+escapeHtml(event.candidate_text||"")+'</div>'+
        '<div class="history-event-meta">'+escapeHtml(event.reviewed_at||"")+' · '+escapeHtml(event.adaptation_mode||"manual")+(event.tone?' · '+escapeHtml(event.tone):"")+'</div>'+
        (approved?'<button type="button" class="ghost small restore-adaptation" data-revision="'+revision+'">Restore this approved revision</button>':"")+'</article>';
    }).join('');
  panel.querySelectorAll(".restore-adaptation").forEach(restore=>{
    restore.onclick=async()=>{
      const revision=Number(restore.dataset.revision);if(!Number.isInteger(revision)||revision<1)return;
      restore.disabled=true;const label=restore.textContent;restore.textContent="Restoring…";
      try{
        const result=await api("/api/projects/"+state.selected+"/dialogue/"+index+"/adaptation/restore/"+revision,{method:"POST"});
        const translation=await api("/api/projects/"+state.selected+"/translation");
        const restored=translation.segments.find(row=>Number(row.segment_index)===index);
        const editor=view.querySelector('[data-translation-index="'+index+'"]');if(editor&&restored)editor.value=restored.translated_text||"";
        const status=view.querySelector('[data-adaptation-status="'+index+'"]');
        if(status)status.textContent="Restored approved revision #"+revision+" as new revision #"+result.revision;
        await loadAdaptationHistory(index,panel,view);
      }catch(e){alert("Restore failed: "+e.message);restore.disabled=false;restore.textContent=label;}
    };
  });
}

async function translateTranscript({readOnly=false}={}){
  const projectId=state.selected;
  if(!state.selected)return;
  const btn=$('translateBtn'), view=$('transcriptView');
  const oldLabel=btn?.textContent||'Translate';
  if(btn){btn.disabled=true;btn.textContent='Translating…';}
  if(view && !readOnly){view.classList.remove('hidden');view.innerHTML='<div class="character-notice info"><span class="diagnostic-spinner"></span><div class="character-notice-title">Translation in progress…</div><div class="character-notice-body">Checking installed Argos language pairs, then translating dialogue segments locally. Keep OpenDub Studio running.</div></div>';}
  try{
    const target=$('targetLanguage').value;
    let data;
    try { data=await api('/api/projects/'+projectId+'/translation'); } catch(error) { if(readOnly) return; }
    if(!readOnly && (!data || normalizeLanguageCode(data.target_language)!==normalizeLanguageCode(target))){
      await api('/api/projects/'+projectId+'/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_language:target})});
      data=await api('/api/projects/'+projectId+'/translation');
    }
    if(!data || state.selected !== projectId) return;
    const view=$('transcriptView');view.classList.remove('hidden');
    view.dataset.projectId=projectId; view.dataset.kind="translation";
    view.innerHTML='<h3>Translated dialogue · '+escapeHtml(data.target_language)+'</h3>'+
      '<p class="hint">Review target-language dialogue without changing source timestamps. Save a line to update the master dialogue unit.</p>'+
      '<label class="dialogue-filter">Find dialogue or character<input type="search" data-dialogue-filter placeholder="Character name or words"></label>'+
      data.segments.map(x=>{
        const identity=x.character_name||x.character_id||"Character review";
        const index=Number(x.segment_index||0);
        return '<div class="translation-review-row">'+
          '<div class="translation-review-meta"><time>'+formatSpeechTime(x.start)+' - '+formatSpeechTime(x.end)+'</time><b>'+escapeHtml(identity)+'</b></div>'+
          '<div class="translation-source">'+escapeHtml(x.source_text||"")+'</div>'+
          '<textarea class="translation-editor" data-translation-index="'+index+'" rows="2">'+escapeHtml(x.translated_text||"")+'</textarea>'+
          '<details class="dialogue-settings"><summary>Dialogue tone & voice delivery</summary><div class="translation-constraints">'+
            '<label>Tone<select data-translation-tone="'+index+'">'+["neutral","calm","warm","serious","angry","sad","excited","fearful","urgent","comedic"].map(v=>'<option value="'+v+'">'+v+'</option>').join("")+'</select></label>'+
            '<label>Intent<input data-translation-intent="'+index+'" value="" placeholder="e.g. warning, reassurance, threat"></label>'+
            '<label>Max words<input type="number" min="1" max="1000" data-translation-max-words="'+index+'" placeholder="Auto"></label>'+
          '</div>'+
          '<div class="prosody-editor">'+
            '<strong>Voice delivery · review before synthesis</strong>'+
            '<label>Emotion<select data-prosody-emotion="'+index+'">'+["unspecified","neutral","calm","warm","serious","angry","sad","excited","fearful","urgent","comedic"].map(v=>'<option value="'+(v==="unspecified"?"":v)+'">'+v+'</option>').join("")+'</select></label>'+
            '<label>Delivery<select data-prosody-delivery="'+index+'">'+["unspecified","conversational","whispering","shouting","soft","firm","crying","laughing","narration"].map(v=>'<option value="'+(v==="unspecified"?"":v)+'">'+v+'</option>').join("")+'</select></label>'+
            '<label>Rate<input type="number" min="0.5" max="2" step="0.05" value="1" data-prosody-rate="'+index+'"></label>'+
            '<label>Pitch (semitones)<input type="number" min="-12" max="12" step="1" placeholder="Default" data-prosody-pitch="'+index+'"></label>'+
            '<label>Volume<input type="number" min="0" max="2" step="0.1" placeholder="Default" data-prosody-volume="'+index+'"></label>'+
            '<button type="button" class="ghost small save-prosody" data-segment-index="'+index+'">Save voice delivery</button>'+
            '<span class="hint" data-prosody-status="'+index+'">Provider support is not yet checked.</span></div></details>'+
          (x.dub_audio ? '<div class="segment-audio-player"><audio controls preload="none" aria-label="Hindi dialogue preview" src="/api/projects/'+projectId+'/segments/'+index+'/audio?t='+Date.now()+'"></audio><span class="hint">'+(x.timing_check?.status==="completed" && !x.timing_check?.duration_fit_limited ? "✓ Timing fit verified" : (x.timing_check?.status==="needs_review" ? "Timing review required" : (x.synthesis_duration_check?.status==="within_tolerance" ? "✓ Duration matched ("+x.synthesis_duration_check.actual_audio_ms+"ms)" : (x.synthesis_duration_check ? "Fit needed ("+x.synthesis_duration_check.actual_audio_ms+"ms vs "+x.synthesis_duration_check.source_window_ms+"ms)" : "Audio ready"))))+'</span></div>' : '')+
          '<div class="translation-review-actions"><span class="hint" data-adaptation-status="'+index+'">'+escapeHtml(x.translation_error||(x.dub_audio ? "Audio synthesized" : "Ready for synthesis"))+'</span><div class="translation-review-buttons"><button class="ghost small synthesize-line" data-segment-index="'+index+'">'+(x.dub_audio ? "Regenerate" : "Synthesize")+'</button><button class="ghost small suggest-adaptation" data-segment-index="'+index+'">Suggest</button><button class="ghost small save-translation" data-segment-index="'+index+'">Save line</button><button class="ghost small adaptation-history-toggle" data-segment-index="'+index+'">Review history</button></div></div>'+
        '<div class="adaptation-history hidden" data-history-panel="'+index+'"></div>'+
        '</div>';
      }).join('');
    const dialogueFilter = view.querySelector?.('[data-dialogue-filter]');
    if(dialogueFilter) dialogueFilter.oninput=()=>{
      const query=dialogueFilter.value.trim().toLocaleLowerCase();
      view.querySelectorAll('.translation-review-row').forEach(row=>{
        const words=row.textContent+' '+(row.querySelector('.translation-editor')?.value||'');
        row.hidden=query.length>0 && !words.toLocaleLowerCase().includes(query);
      });
    };
    view.querySelectorAll(".synthesize-line").forEach(btn=>{
      btn.onclick=async()=>{
        const index=Number(btn.dataset.segmentIndex);
        btn.disabled=true;
        const old=btn.textContent;
        btn.textContent="Synthesizing…";
        const status=view.querySelector('[data-adaptation-status="'+index+'"]');
        if(status)status.textContent="Synthesizing…";
        try{
          const voice=$('voiceModelPath')?.value?.trim()||null;
          const result=await api("/api/projects/"+projectId+"/segments/"+index+"/synthesize",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({voice_model_path:voice})
          });
          if(status)status.textContent="Synthesized ("+(result.duration_check?.status||"ready")+")";
          await translateTranscript({readOnly:true});
          await loadPipelineState();
        }catch(e){
          if(status)status.textContent="Synthesis failed: "+e.message;
          alert("Synthesis failed: "+e.message);
        }finally{
          btn.disabled=false;
          btn.textContent=old;
        }
      };
    });
    view.querySelectorAll(".save-prosody").forEach(btn=>{
      btn.onclick=async()=>{
        const index=Number(btn.dataset.segmentIndex),get=(name)=>view.querySelector('[data-prosody-'+name+'="'+index+'"]')?.value;
        const optionalNumber=(value)=>value===""||value==null?null:Number(value);
        const payload={emotion:get("emotion")||null,delivery:get("delivery")||null,rate:Number(get("rate")||1),pitch:optionalNumber(get("pitch")),volume:optionalNumber(get("volume")),review_required:true};
        const status=view.querySelector('[data-prosody-status="'+index+'"]'),label=btn.textContent;
        btn.disabled=true;btn.textContent="Saving…";
        try{
          const result=await api("/api/projects/"+projectId+"/dialogue/"+index+"/prosody",{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
          if(status)status.textContent="Saved · provider support: "+(result.prosody?.provider_support||"not_checked")+" · review required";
          await loadPipelineState();
        }catch(e){if(status)status.textContent="Save failed: "+e.message;alert(e.message)}
        finally{btn.disabled=false;btn.textContent=label}
      };
    });
    view.querySelectorAll(".adaptation-history-toggle").forEach(btn=>{
      btn.onclick=async()=>{
        const index=Number(btn.dataset.segmentIndex),panel=view.querySelector('[data-history-panel="'+index+'"]');
        if(!panel)return;
        const opening=panel.classList.contains("hidden");panel.classList.toggle("hidden",!opening);if(!opening)return;
        btn.disabled=true;const label=btn.textContent;btn.textContent="Loading…";
        try{await loadAdaptationHistory(index,panel,view);}
        catch(e){panel.innerHTML='<div class="history-empty">Could not load review history: '+escapeHtml(e.message)+'</div>';}
        finally{btn.disabled=false;btn.textContent=label;}
      };
    });
    view.querySelectorAll(".suggest-adaptation").forEach(btn=>{
      btn.onclick=async()=>{
        const index=Number(btn.dataset.segmentIndex);
        const editor=view.querySelector('[data-translation-index="'+index+'"]');
        const text=editor?.value?.trim();
        if(!text){alert("Enter translated dialogue before requesting a suggestion.");return;}
        const old=btn.textContent; btn.disabled=true; btn.textContent="Suggesting…";
        const status=view.querySelector('[data-adaptation-status="'+index+'"]');
        try{
          const result=await api("/api/projects/"+projectId+"/dialogue/"+index+"/adaptation/suggest",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({
              translated_text:text,
              adaptation_mode:"conservative_assist",
              tone:view.querySelector('[data-translation-tone="'+index+'"]')?.value||"neutral",
              delivery_intent:view.querySelector('[data-translation-intent="'+index+'"]')?.value?.trim()||"faithful",
              max_words:Number(view.querySelector('[data-translation-max-words="'+index+'"]')?.value)||null
            })
          });
          const candidate=String(result.suggested_text||"").trim();
          if(!candidate) throw new Error("Provider returned an empty suggestion.");
          let panel=view.querySelector('[data-review-panel="'+index+'"]');
          if(!panel){
            panel=document.createElement("div");
            panel.className="adaptation-review-panel";
            panel.dataset.reviewPanel=String(index);
            const row=btn.closest(".translation-review-row");
            row?.appendChild(panel);
          }
          panel.innerHTML='<strong>AI suggestion · Review required</strong><div class="adaptation-candidate">'+escapeHtml(candidate)+'</div>'+
            '<div class="translation-review-buttons"><button type="button" class="primary small approve-adaptation" data-segment-index="'+index+'">Approve suggestion</button><button type="button" class="ghost small reject-adaptation" data-segment-index="'+index+'">Reject</button></div>';
          panel.dataset.candidate=candidate;
          panel.dataset.adaptationMode=result.adaptation_mode||"conservative_assist";
          panel.dataset.timingBudget=String(Number(view.querySelector('[data-translation-max-words="'+index+'"]')?.value)||"");
          if(status){
            const note=(result.changes||[]).join(" ") || "Review the proposed line before accepting.";
            status.textContent=(result.budget?.status==="over_budget"?"Over budget · ":"")+"Suggestion ready · "+note;
          }
          panel.querySelector(".approve-adaptation").onclick=async()=>{
            const approve=panel.querySelector(".approve-adaptation");
            approve.disabled=true; approve.textContent="Approving…";
            try{
              const approvedText=panel.dataset.candidate||"";
              await api("/api/projects/"+projectId+"/dialogue/"+index+"/adaptation/review",{
                method:"POST",headers:{"Content-Type":"application/json"},
                body:JSON.stringify({
                  decision:"approve",suggested_text:approvedText,adaptation_mode:panel.dataset.adaptationMode||"conservative_assist",
                  tone:view.querySelector('[data-translation-tone="'+index+'"]')?.value||"neutral",
                  delivery_intent:view.querySelector('[data-translation-intent="'+index+'"]')?.value?.trim()||"faithful",
                  max_words:Number(view.querySelector('[data-translation-max-words="'+index+'"]')?.value)||null
                })
              });
              if(editor) editor.value=approvedText;
              panel.innerHTML='<strong>Approved by you</strong><div class="adaptation-candidate">'+escapeHtml(approvedText)+'</div>';
              if(status)status.textContent="Human approval recorded · synthesis input updated";
              await loadPipelineState();
            }catch(e){if(status)status.textContent="Approval failed: "+e.message;alert(e.message);approve.disabled=false;approve.textContent="Approve suggestion"}
          };
          panel.querySelector(".reject-adaptation").onclick=async()=>{
            const reject=panel.querySelector(".reject-adaptation");
            reject.disabled=true;reject.textContent="Rejecting…";
            try{
              await api("/api/projects/"+projectId+"/dialogue/"+index+"/adaptation/review",{
                method:"POST",headers:{"Content-Type":"application/json"},
                body:JSON.stringify({decision:"reject",suggested_text:panel.dataset.candidate||candidate,adaptation_mode:panel.dataset.adaptationMode||"conservative_assist"})
              });
              panel.innerHTML='<strong>Suggestion rejected</strong>';
              if(status)status.textContent="Rejected · saved translation unchanged";
            }catch(e){if(status)status.textContent="Rejection failed: "+e.message;alert(e.message);reject.disabled=false;reject.textContent="Reject"}
          };
        }catch(e){
          if(status) status.textContent="Suggestion failed: "+e.message;
          alert(e.message);
        }finally{
          btn.disabled=false; btn.textContent=old;
        }
      };
    });
    view.querySelectorAll(".save-translation").forEach(btn=>{
      btn.onclick=async()=>{
        const index=Number(btn.dataset.segmentIndex);
        const editor=view.querySelector('[data-translation-index="'+index+'"]');
        const text=editor?.value?.trim();
        if(!text){alert("Translated dialogue cannot be empty.");return;}
        const old=btn.textContent; btn.disabled=true; btn.textContent="Saving…";
        try{
          await api("/api/projects/"+projectId+"/dialogue/"+index+"/translation",{
            method:"PATCH",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({
              translated_text:text,
              adaptation_mode:"manual_naturalization",
              tone:view.querySelector('[data-translation-tone="'+index+'"]')?.value||"neutral",
              delivery_intent:view.querySelector('[data-translation-intent="'+index+'"]')?.value?.trim()||"faithful",
              max_words:Number(view.querySelector('[data-translation-max-words="'+index+'"]')?.value)||null
            })
          });
          btn.textContent="Saved";
          await translateTranscript({readOnly:true});
          await loadPipelineState();
        }catch(e){alert(e.message);btn.textContent=old}
        finally{btn.disabled=false;setTimeout(()=>btn.textContent=old,900)}
      };
    });
    await loadPipelineState();
  }catch(e){
    if(view)view.innerHTML='<div class="character-notice error"><div class="character-notice-title">Translation failed</div><div class="character-notice-body">'+escapeHtml(e.message)+'</div><div class="character-notice-body">Check that the selected source language and target language have installed Argos packages, or that source→English and English→target pivot packages are installed.</div></div>';
    alert('Translation failed: '+e.message);
  }finally{if(btn){btn.disabled=false;btn.textContent=oldLabel}}
}

async function dubAllSegments(){
  if(!state.selected)return;
  const btn=$('dubAllBtn');
  const cancelBtn=$('cancelJobBtn');
  const voice=$('voiceModelPath')?.value?.trim()||null;
  const oldText=btn?btn.textContent:'Synthesize';
  if(btn){btn.disabled=true;btn.textContent='Synthesizing…';}
  try{
    const started=await api('/api/projects/'+state.selected+'/synthesize-all',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({voice_model_path:voice,force:false})
    });
    $('jobProgress').classList.remove('hidden');
    $('jobMessage').textContent='Batch synthesis queued…';
    $('jobPercent').textContent='0%';
    $('jobBar').style.width='0%';
    const activeJobId=started.job_id;
    if(cancelBtn){
      cancelBtn.classList.remove('hidden');
      cancelBtn.onclick=async()=>{
        try{
          await api('/api/jobs/'+activeJobId+'/cancel',{method:'POST'});
          $('jobMessage').textContent='Cancelling batch synthesis…';
        }catch(err){console.error('Cancel request failed:',err);}
      };
    }
    for(let i=0;i<86400;i++){
      await new Promise(r=>setTimeout(r,1500));
      const job=await api('/api/jobs/'+activeJobId);
      $('jobMessage').textContent=job.message||job.status;
      $('jobPercent').textContent=Math.round((job.progress||0)*100)+'%';
      $('jobBar').style.width=((job.progress||0)*100)+'%';
      if(job.status==='completed'){
        const p=job.payload||{};
        $('jobMessage').textContent='Batch synthesis finished ('+(p.synthesized_count||0)+' synthesized, '+(p.skipped_count||0)+' skipped, '+(p.failed_count||0)+' failed)';
        alert('Batch synthesis complete: '+(p.synthesized_count||0)+' synthesized, '+(p.skipped_count||0)+' skipped, '+(p.failed_count||0)+' failed.');
        break;
      }
      if(job.status==='cancelled'){
        $('jobMessage').textContent='Batch synthesis cancelled.';
        alert('Batch synthesis was cancelled.');
        break;
      }
      if(job.status==='failed'){
        $('jobMessage').textContent='Batch synthesis failed.';
        alert('Batch synthesis stopped: '+(job.message||'Unknown error'));
        break;
      }
    }
    await translateTranscript({readOnly:true});
    await loadPipelineState();
  }catch(e){
    alert('Synthesis error: '+e.message);
  }finally{
    if(cancelBtn){cancelBtn.classList.add('hidden');cancelBtn.onclick=null;}
    if(btn){btn.disabled=false;btn.textContent=oldText;}
  }
}

async function fitAllSegments(){
  if(!state.selected)return;
  const btn=$('fitAllBtn');
  const cancelBtn=$('cancelJobBtn');
  const oldText=btn?btn.textContent:'Fit All Dubbed Segments';
  if(btn){btn.disabled=true;btn.textContent='Fitting timing…';}
  try{
    const started=await api('/api/projects/'+state.selected+'/fit-all',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({max_speedup:1.25,max_slowdown:0.82,normalize:true,target_lufs:-16,force:false})
    });
    $('jobProgress').classList.remove('hidden');
    $('jobMessage').textContent='Timing & loudness job queued…';
    $('jobPercent').textContent='0%';
    $('jobBar').style.width='0%';
    const activeJobId=started.job_id;
    if(cancelBtn){
      cancelBtn.classList.remove('hidden');
      cancelBtn.onclick=async()=>{
        try{
          await api('/api/jobs/'+activeJobId+'/cancel',{method:'POST'});
          $('jobMessage').textContent='Cancelling timing fit…';
        }catch(err){console.error('Cancel request failed:',err);}
      };
    }
    for(let i=0;i<86400;i++){
      await new Promise(r=>setTimeout(r,1500));
      const job=await api('/api/jobs/'+activeJobId);
      $('jobMessage').textContent=job.message||job.status;
      $('jobPercent').textContent=Math.round((job.progress||0)*100)+'%';
      $('jobBar').style.width=((job.progress||0)*100)+'%';
      if(job.status==='completed'){
        const p=job.payload||{};
        $('jobMessage').textContent='Timing fit complete ('+(p.fitted_count||0)+' fitted, '+(p.normalized_count||0)+' normalized, '+(p.needs_review_count||0)+' flagged)';
        alert('Timing fit complete: '+(p.fitted_count||0)+' fitted, '+(p.normalized_count||0)+' normalized, '+(p.needs_review_count||0)+' need review, '+(p.skipped_count||0)+' skipped.');
        break;
      }
      if(job.status==='cancelled'){
        $('jobMessage').textContent='Timing fit was cancelled.';
        alert('Timing fit was cancelled.');
        break;
      }
      if(job.status==='failed'){
        $('jobMessage').textContent='Timing fit failed.';
        alert('Timing fit failed: '+(job.message||'Unknown error'));
        break;
      }
    }
    await translateTranscript({readOnly:true});
    await loadPipelineState();
  }catch(e){
    alert('Timing fit error: '+e.message);
  }finally{
    if(cancelBtn){cancelBtn.classList.add('hidden');cancelBtn.onclick=null;}
    if(btn){btn.disabled=false;btn.textContent=oldText;}
  }
}

async function preserveBackground(){
  if(!state.selected)return;
  const btn=$('preserveBgBtn');
  const oldText=btn?btn.textContent:'Preserve Background';
  if(btn){btn.disabled=true;btn.textContent='Preserving background…';}
  try{
    const mode=$('bgPreserveMode')?.value||'separation';
    const bgPath=$('backgroundPath')?.value?.trim()||null;
    const res=await api('/api/projects/'+state.selected+'/background/preserve',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode:mode,user_stem_path:bgPath,duck_db:0.0,attack_ms:50.0,release_ms:150.0})
    });
    const audio=$('bgPreview');
    if(audio){
      audio.src='/api/projects/'+state.selected+'/background/preview?ts='+Date.now();
      audio.classList.remove('hidden');
      audio.load();
    }
    alert('Background audio preserved ('+res.mode+'). '+(res.notice||'Ready for mixing.'));
    await loadPipelineState(); await window.refreshStudioMedia?.();
  }catch(e){
    alert('Background preservation failed: '+e.message);
  }finally{
    if(btn){btn.disabled=false;btn.textContent=oldText;}
  }
}

async function buildMix(){
  if(!state.selected)return;
  const btn=$('mixBtn')||$('mixDubBtn');
  const oldText=btn?btn.textContent:'Mix';
  if(btn){btn.disabled=true;btn.textContent='Mixing…';}
  try{
    const bg=$('backgroundPath')?.value?.trim();
    const res=await api('/api/projects/'+state.selected+'/mix',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({background_path:bg||null,target_lufs:-16,duck_background:false})
    });
    const audio=$('mixPreview');
    if(audio){
      audio.src='/api/projects/'+state.selected+'/mix/preview?ts='+Date.now();
      audio.classList.remove('hidden');
      audio.load();
    }
    alert('Mix created. Segments mixed: '+res.dialogue_segments_mixed+'. '+(res.background_used?'Background included at its original level. Review the mix for clipping.':'Dialogue bus only.'));
    await loadPipelineState(); await window.refreshStudioMedia?.();
  }catch(e){
    alert('Mix failed: '+e.message);
  }finally{
    if(btn){btn.disabled=false;btn.textContent=oldText;}
  }
}

async function renderFinalMovie(){
  if(!state.selected)return;
  const btn=$('renderBtn');btn.disabled=true;const old=btn.textContent;btn.textContent='Rendering…';
  try{
    const started=await api('/api/projects/'+state.selected+'/render',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({cleanup_intermediates:$('cleanupAfterRender').checked})
    });
    $('jobProgress').classList.remove('hidden');
    for(let i=0;i<86400;i++){
      await new Promise(r=>setTimeout(r,2000));
      const job=await api('/api/jobs/'+started.job_id);
      $('jobMessage').textContent=job.message||job.status;
      $('jobPercent').textContent=Math.round((job.progress||0)*100)+'%';
      $('jobBar').style.width=((job.progress||0)*100)+'%';
      if(job.status==='completed'){
        const link=$('downloadRender');
        link.href='/api/projects/'+state.selected+'/render/download';
        link.classList.remove('hidden');
        link.textContent='Download Final Movie ('+formatBytes(job.payload?.size_bytes||0)+')';

        try{
          const qa=await api('/api/projects/'+state.selected+'/render/qa');
          const badge=$('qaReportBadge');
          if(badge&&qa){
            badge.classList.remove('hidden');
            badge.innerHTML='<strong>Automated QA: '+escapeHtml(qa.status)+'</strong> · Video: '+escapeHtml(qa.checks?.find(c=>c.name==='Video stream')?.detail||'OK')+' · Audio: '+escapeHtml(qa.checks?.find(c=>c.name==='Audio stream')?.detail||'OK')+' · Duration: '+qa.render_duration_sec+'s';
            badge.style.background=qa.status==='PASSED'?'rgba(16,185,129,0.18)':qa.status==='WARNING'?'rgba(245,158,11,0.18)':'rgba(239,68,68,0.18)';
            badge.style.color=qa.status==='PASSED'?'#34d399':qa.status==='WARNING'?'#fcd34d':'#fca5a5';
            badge.style.borderColor=qa.status==='PASSED'?'rgba(16,185,129,0.4)':qa.status==='WARNING'?'rgba(245,158,11,0.4)':'rgba(239,68,68,0.4)';
          }
        }catch(qaErr){console.warn('QA report inspect error:',qaErr);}

        alert('Final render complete and verified. Source movie was preserved.');
        await loadProjects();
        await loadPipelineState();
        break;
      }
      if(job.status==='failed'){
        alert('Render failed: '+job.message);
        break;
      }
    }
  }catch(e){
    alert('Render error: '+e.message);
  }finally{
    btn.disabled=false;btn.textContent=old;
  }
}

async function analyze(){
  if(!state.selected) return;
  const projectId=state.selected;
  $("analyzeBtn").disabled=true; $("analyzeBtn").textContent="Queueing analysis…";
  try{
    const model=$("asrModel")?.value||"small";
    const sourceLanguage=$("sourceLanguage")?.value;
    const query=new URLSearchParams({model_size:model,device:"auto"});
    if(sourceLanguage && sourceLanguage!=="Auto Detect" && sourceLanguage!=="auto") query.set("language",sourceLanguage);
    const started=await api("/api/projects/"+projectId+"/analyze/full?"+query.toString(),{method:"POST"});
    $("jobProgress").classList.remove("hidden");
    for(let i=0;i<86400;i++){
      await new Promise(r=>setTimeout(r,2000));
      const job=await api("/api/jobs/"+started.job_id);
      $("jobMessage").textContent=job.message||job.status;
      $("jobPercent").textContent=Math.round((job.progress||0)*100)+"%";
      $("jobBar").style.width=((job.progress||0)*100)+"%";
      if(job.status==="completed"){
        $("jobMessage").textContent="Full movie analysis complete. Timeline and checkpoints saved.";
        await refreshSelected(); await loadProjects(); break;
      }
      if(job.status==="failed"){throw new Error(job.message||"Full movie analysis failed.");}
      if(job.status==="cancelled"){
        $("jobMessage").textContent=job.message||"Analysis paused; completed checkpoints retained.";
        await refreshSelected(); await loadProjects(); break;
      }
    }
  }catch(e){alert(e.message);}
  finally{$("analyzeBtn").disabled=false;$("analyzeBtn").textContent="Run";}
}

async function removeProject(){
  if(!state.selected) return;
  const projectName = state.projects.find(project => project.id === state.selected)?.name || state.selected;
  if(!confirm(`Remove project "${projectName}" from the workspace? Its files will be retained in runtime/deleted_projects for recovery.`)) return;
  await api("/api/projects/"+state.selected,{method:"DELETE"});
  state.selected=null; localStorage.removeItem("opendub:selectedProject"); beep(); await loadProjects();
}

/* ==========================================================================
   DOM Bindings & Initializers
   ========================================================================== */
$("systemStatus").onclick=openDiagnosticsModal;
$("closeDiagnosticsModal").onclick=closeDiagnosticsModal;
$("diagnosticsModal").addEventListener("click",e=>{if(e.target.id==="diagnosticsModal")closeDiagnosticsModal();});
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeDiagnosticsModal();});

$("newProjectBtn").onclick=openModal; $("emptyCreateBtn").onclick=openModal;
$("closeModal").onclick=closeModal; $("cancelModal").onclick=closeModal;
$("createProject").onclick=createProject;
$("movieInput").onchange=e=>{ const file=e.target.files[0]; if(file) uploadMovie(file).catch(err=>alert("Upload failed: "+err.message)); e.target.value=""; };
$("analyzeBtn").onclick=analyze; $("deleteProjectBtn").onclick=removeProject; $("renameProjectBtn").onclick=renameProject;
$("syncCharactersBtn").onclick=syncCharacters; $("syncCharactersRegistryBtn").onclick=syncCharacters; $("translateBtn").onclick=translateTranscript; $("dubAllBtn").onclick=dubAllSegments; $("fitAllBtn").onclick=fitAllSegments; $("mixBtn").onclick=buildMix; if($("mixDubBtn")) $("mixDubBtn").onclick=buildMix; if($("preserveBgBtn")) $("preserveBgBtn").onclick=preserveBackground; $("renderBtn").onclick=renderFinalMovie; $("separateBtn").onclick=()=>runStage("separate"); $("extractAudioBtn").onclick=()=>runStage("audio_extract"); $("detectScenesBtn").onclick=()=>runStage("scene_detect"); $("transcribeBtn").onclick=()=>runStage("transcribe"); $("diarizeBtn").onclick=()=>runStage("diarize");

if($("runAutoDubBtn")) $("runAutoDubBtn").onclick = onRunAutoDubClick;
const autoToggle = $("autoFullPipelineToggle");
if(autoToggle){
  const savedToggle = localStorage.getItem("opendub:autoFullPipeline");
  if(savedToggle !== null){
    autoToggle.checked = savedToggle === "true";
  }
  autoToggle.addEventListener("change", (e) => {
    localStorage.setItem("opendub:autoFullPipeline", String(e.target.checked));
  });
}
const autoDlBtn = $("autoDubDownloadBtn");
if(autoDlBtn){
  autoDlBtn.addEventListener("click", () => {
    if(!state.selected) return;
    if(!autoDlBtn.href || autoDlBtn.href.endsWith("#")){
      autoDlBtn.href = "/api/projects/" + state.selected + "/final-video?download=1";
    }
  });
}

$("diagnosticsRefreshBtn").onclick=()=>loadDiagnostics(true);
$("addCharacterBtn").onclick=()=>addCharacter();
$("refreshBtn").onclick=()=>{loadProjects().catch(console.error);loadDiagnostics();};

api("/api/health").then(()=>loadDiagnostics()).catch((e)=>{
  $("systemStatus").innerHTML='<span class="dot" style="background:#ef4444"></span> Backend unavailable';
  const summary=$("diagnosticsSummary"); if(summary) summary.textContent="Backend health check failed: "+e.message;
  console.error("[OpenDub diagnostics] Health endpoint failed:",e);
});

// ==========================================================================
loadProjects().catch(console.error);
