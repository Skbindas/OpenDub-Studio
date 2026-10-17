/* User actions import references; no model download, clone approval or upload consent is automatic. */
(() => {
  const el=id=>document.getElementById(id);
  const form=el('ownVoiceForm'),file=el('ownVoiceFile'),preview=el('ownVoicePreview');
  let previewUrl;
  file.addEventListener('change',()=>{
    if(previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl=file.files?.[0] ? URL.createObjectURL(file.files[0]) : null;
    preview.hidden=!previewUrl;
    if(previewUrl)preview.src=previewUrl;else preview.removeAttribute('src');
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!form.reportValidity())return;
    const button=el('importOwnVoiceBtn'),message=el('ownVoiceStatus');
    button.disabled=true;message.textContent='Checking and saving your private reference…';
    try{
      const result=await api('/api/voices/import',{method:'POST',body:new FormData(form)});
      message.textContent=`${result.display_name} saved privately. A dubbed audition has not been generated or approved. Choose this reference in speaker review, lock your choice, and listen to a short dub.`;
      el('loadVoiceLibraryBtn').click();
      window.dispatchEvent(new Event('opendub:voice-library-changed'));
      refreshSetup(false);
    }catch(error){message.textContent=error.message;}
    finally{button.disabled=false;}
  });
  async function refreshSetup(fresh){
    const button=el('refreshSetupBtn'),summary=el('setupSummary'),list=el('setupChecks');
    button.disabled=true;summary.textContent='Checking setup…';
    try{
      const status=await api('/api/setup/status'+(fresh?'?fresh=true':''));
      summary.textContent=`${status.checks.filter(c=>c.status==='available').length}/${status.checks.length} local prerequisites available · a real preview is still required.`;
      list.replaceChildren();
      for(const item of status.checks){
        const row=document.createElement('li'),title=document.createElement('strong'),detail=document.createElement('span');
        title.textContent=(item.status==='available'?'✓ ':'• ')+item.title;
        detail.textContent=item.status==='available'?'Configured / installed in this setup snapshot. Preview required.':item.action;
        row.className=item.status;row.append(title,detail);list.append(row);
      }
      el('setupNote').textContent=status.notice;
    }catch(error){summary.textContent='Setup check unavailable: '+error.message;}
    finally{button.disabled=false;}
  }
  el('refreshSetupBtn').addEventListener('click',()=>refreshSetup(true));
  el('setupDiagnosticsBtn').addEventListener('click',()=>el('systemStatus').click());
  refreshSetup(false);
})();
