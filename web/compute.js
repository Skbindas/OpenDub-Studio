/* Credentials are write-only and never persisted in browser storage. */
(() => {
  const node = id => document.getElementById(id);
  const panel = node('computePanel');
  if (!panel) return;
  let loadedProject = null, busy = false;
  const message = text => { node('computeStatus').textContent = text; };
  const projectUrl = () => {
    if (!state.selected) throw new Error('Select a project first.');
    return `/api/projects/${encodeURIComponent(state.selected)}/compute`;
  };
  async function request(url, method='GET', body) {
    return api(url, {method, ...(body ? {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {})});
  }
  function providerVisibility() {
    node('kaggleSettings').hidden = node('computeProvider').value !== 'kaggle';
  }
  function renderJobs(jobs) {
    const holder = node('kaggleJobs'); holder.replaceChildren();
    for (const job of jobs) {
      const row = document.createElement('article'); row.className='analysis-stage-item';
      const label=document.createElement('p'); label.textContent=`${job.operation} · ${job.state} · ${job.message || 'Local intent retained'}`; row.append(label);
      const actions=job.schema_version===2 ? (['completed','cancelled'].includes(job.state)?[]:['reconcile']) : job.state==='prepared' ? ['prepare','submit'] : job.state==='review_required' && job.message.startsWith('Remote attempt is terminal.') ? ['reconcile','retry'] : ['completed','failed','cancelled'].includes(job.state) ? [] : ['reconcile'];
      for (const action of actions) {
        const button=document.createElement('button'); button.type='button';button.className='ghost';button.textContent=action==='prepare'?'Prepare locally':action==='submit'?'Submit private job':action==='retry'?'Retry unfinished unit in a new session':'Reconcile existing run';
        button.onclick=async()=>{
          button.disabled=true;
          try { await request(`${projectUrl()}/jobs/${encodeURIComponent(job.id)}/${action}`,'POST'); message(`${action} accepted; refresh to see the actual result.`); }
          catch(error) { message(error.message); }
          finally { button.disabled=false; }
        };
        row.append(button);
      }
      holder.append(row);
    }
  }
  async function load(force=false) {
    if (!state.selected || busy) return;
    busy=true;
    const project=state.selected;
    try {
      const data=await request(projectUrl());
      if (state.selected!==project) return;
      if (loadedProject!==project || force) {
        node('computeProvider').value=data.settings.provider;
        node('kaggleUsername').value=data.settings.username || data.account.username || '';
        node('kaggleAccelerator').value=data.settings.accelerator;
        node('kaggleUploadAllowed').checked=data.settings.allow_media_upload;
        node('kaggleModelUploadAllowed').checked=data.settings.allow_model_upload;
        loadedProject=project;providerVisibility();
      }
      message(`${data.settings.provider==='local'?'Local selected':'Kaggle selected · pipeline code connected; live validation pending'}. SDK: ${data.account.cli_installed?'installed':'run scripts/setup_kaggle.py'}. Credentials: ${data.account.configured?'configured, authentication unverified':'not configured'}. GPU availability / remaining quota: unverified. Completed tasks are retained locally.`);
      renderJobs(data.jobs);
    } catch(error) { message(error.message); }
    finally { busy=false; }
  }
  node('computeProvider').onchange=providerVisibility;
  node('saveComputeSettings').onclick=async()=>{
    try {
      await request(projectUrl(),'PUT',{provider:node('computeProvider').value,username:node('kaggleUsername').value.trim(),accelerator:node('kaggleAccelerator').value,allow_media_upload:node('kaggleUploadAllowed').checked,allow_model_upload:node('kaggleModelUploadAllowed').checked});
      await load(true);
    } catch(error) { message(error.message); }
  };
  node('saveKaggleCredentials').onclick=async()=>{
    const token=node('kaggleApiToken'),key=node('kaggleLegacyKey'),button=node('saveKaggleCredentials');
    button.disabled=true;
    try { await request('/api/compute/kaggle/credentials','POST',{username:node('kaggleUsername').value.trim(),token:token.value,legacy_key:key.value}); message('Saved to the OS credential vault; authentication/GPU testing remains pending.'); }
    catch(error) { message(error.message); }
    finally { token.value='';key.value='';button.disabled=false; }
  };
  node('createKaggleJob').onclick=async()=>{
    try { await request(`${projectUrl()}/jobs`,'POST',{operation:node('kaggleOperation').value,start:Number(node('kaggleCropStart').value),end:Number(node('kaggleCropEnd').value)}); await load(); }
    catch(error) { message(error.message); }
  };
  node('refreshComputeStatus').onclick=()=>load(true);
  panel.addEventListener('toggle',()=>{if(panel.open) load();});
  setInterval(()=>{if(panel.open) load();},15000);
  providerVisibility();
})();
