const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const speechTime = source.slice(source.indexOf('function formatSpeechTime('),source.indexOf('\nfunction ',source.indexOf('function formatSpeechTime(')+1));
const fn = speechTime + '\n' + source.slice(source.indexOf('async function translateTranscript('), source.indexOf('async function dubAllSegments('));

test('cancelled analysis stops polling and unlocks Run for checkpoint resume', async () => {
  const nodes = {};
  const node = id => nodes[id] ??= {value: '', textContent:'', style:{}, classList:{remove(){}}};
  let polls=0; const alerts=[];
  const context={state:{selected:'sample'}, $:node, URLSearchParams,
    setTimeout:fn=>fn(), alert:message=>alerts.push(message),
    refreshSelected:async()=>{},loadProjects:async()=>{},
    api:async(url)=>{
      if(url.includes('/analyze/full'))return {job_id:'paused'};
      if(++polls>1)throw Error('Cancelled job polled again');
      return {status:'cancelled',message:'Paused; cloud work retained',progress:.3};
    }};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function analyze(){'),source.indexOf('\nasync function removeProject',source.indexOf('async function analyze(){'))),context);
  await context.analyze();
  assert.equal(polls,1);assert.deepEqual(alerts,[]);
  assert.equal(node('analyzeBtn').disabled,false);
  assert.ok(node('jobMessage').textContent.includes('retained'));
});

test('both drop surfaces pass the original File to the upload workflow', async () => {
  const workflow=fs.readFileSync('web/speaker-workflow.js','utf8');
  const start=workflow.indexOf(' const card=document.querySelector');
  const end=workflow.indexOf('\n const hint=',start);
  const targets=[0,1].map(()=>({listeners:{},classList:{add(){},remove(){}},addEventListener(name,fn){this.listeners[name]=fn;}}));
  const uploads=[];const context={document:{querySelector:()=>targets[0],getElementById:()=>targets[1]},
    uploadMovie:async file=>uploads.push(file),status:{textContent:''}};
  vm.createContext(context);vm.runInContext(workflow.slice(start,end),context);
  const originalFile={name:'actual-source.mp4',size:10000000000};let prevented=0;
  for(const target of targets){target.listeners.dragover({preventDefault(){prevented++;}});
    target.listeners.drop({preventDefault(){prevented++;},dataTransfer:{files:[originalFile]}});}
  await Promise.resolve();
  assert.equal(prevented,4);assert.equal(uploads.length,2);
  assert.ok(uploads.every(file=>file===originalFile));
  targets[0].listeners.drop({preventDefault(){},dataTransfer:{files:[]}});
  assert.equal(uploads.length,2);
});

test('short speech windows show milliseconds instead of equal whole-second labels', () => {
  const context = {};
  vm.createContext(context); vm.runInContext(speechTime,context);
  assert.equal(context.formatSpeechTime(0),'00:00.000');
  assert.equal(context.formatSpeechTime(.321),'00:00.321');
});

test('diagnostics reuse reports and only explicit refresh probes again', async () => {
  const diagnostics = fs.readFileSync('web/diagnostics.js','utf8');
  const start = diagnostics.indexOf('  let cachedReport');
  const end = diagnostics.indexOf('\n  const boot',start);
  let calls=0; const rendered=[];
  const context={el:()=>null, render:r=>rendered.push(r),showError:e=>{throw Error(e)},
    performance:{now:()=>0},Date,console:{info(){}},
    fetch:async url=>{calls++;return {ok:true,json:async()=>({url})};}};
  vm.createContext(context);
  vm.runInContext(diagnostics.slice(start,end)+'\nthis.check=check;',context);
  await Promise.all([context.check(false),context.check(false)]);
  assert.equal(calls,1);
  await context.check(false);
  assert.equal(calls,1);
  await context.check(true);
  assert.equal(calls,2);
  assert.ok(rendered.at(-1).url.includes('fresh=1'));
});

test('completed fit replaces the old synthesis fit warning', async () => {
  const view = {innerHTML:'',dataset:{},classList:{remove(){}},querySelectorAll:()=>[]};
  const context = {state:{selected:'sample'},$:id=>id==='transcriptView'?view:{value:'hi',textContent:''},
    api:async()=>({segments:[{segment_index:0,dub_audio:'dub.wav',timing_check:{status:'completed'},
                  synthesis_duration_check:{status:'fit_required',actual_audio_ms:1800,source_window_ms:1600}}]}),
    normalizeLanguageCode:v=>v,escapeHtml:v=>String(v??''),formatDuration:()=>'',loadPipelineState:async()=>{},alert:()=>{}};
  vm.createContext(context);vm.runInContext(fn,context);
  await context.translateTranscript({readOnly:true});
  assert.ok(view.innerHTML.includes('Timing fit verified'));
  assert.ok(!view.innerHTML.includes('Fit needed'));
});

test('reviewing existing Hindi dialogue never starts translation or discards edits', async () => {
  const calls = [];
  const view = {innerHTML: '', dataset: {}, classList: {remove() {}}, querySelectorAll: () => []};
  const context = {state: {selected: 'sample'}, $: id => id === 'transcriptView' ? view : id === 'targetLanguage' ? {value: 'hi'} : {textContent: 'Translate'},
    api: async (url, options) => {calls.push({url, method: options?.method || 'GET'}); return {target_language:'hi', segments: [{segment_index:0, translated_text:'पहले से समीक्षा किया हुआ संवाद', source_text:'source'}]};},
    normalizeLanguageCode: v => v, escapeHtml: v => String(v ?? ''), formatDuration: () => '00:01', loadPipelineState: async () => {}, alert: () => {}};
  vm.createContext(context); vm.runInContext(fn, context);
  await context.translateTranscript({readOnly: true});
  assert.deepEqual(calls.map(c=>c.method), ['GET']);
  assert.ok(view.innerHTML.includes('पहले से समीक्षा किया हुआ संवाद'));
});

test('opening completed analysis never rewrites character or transcript files', async () => {
  const start = source.indexOf('async function loadFullAnalysis(');
  const end = source.indexOf('\nasync function ', start + 1);
  const calls = [];
  const view = {dataset: {}, classList: {remove() {}}, innerHTML: ''};
  const context = {state: {selected: 'sample'}, $: id => id === 'transcriptView' ? view : {textContent: '',className: ''},
    api: async (url, options) => {calls.push(options?.method || 'GET'); return {summary:{},stage_status:{speaker_diarization:'completed'},segments:[]};},
    loadCharacters: async () => {}, escapeHtml: v => String(v ?? ''),formatDuration: () => '00:00',console};
  vm.createContext(context); vm.runInContext(source.slice(start,end),context);
  await context.loadFullAnalysis();
  assert.deepEqual(calls,['GET']);
});

test('dashboard displays measured stage ETA and retained work on failure', () => {
  const start = source.indexOf('function measuredDubProgress(');
  const end = source.indexOf('\nfunction stopAutoDubPoller', start);
  const nodes = {};
  const node = id => nodes[id] ||= {dataset:{}, textContent:'', style:{}, disabled:false, classList:{toggle(){}},
    parentElement:{setAttribute(){},removeAttribute(){}}, querySelectorAll:()=>[]};
  const context = {state:{selected:'sample',projects:[{id:'sample',source_path:'movie.mp4'}]}, $:node,
    formatAutoDubTime: sec => `${sec}s`, Number};
  vm.createContext(context); vm.runInContext(source.slice(start,end), context);
  context.updateAutoDubDashboard({project_id:'sample',status:'running',progress_percent:65,
    eta_seconds:12, work:{completed:23,total:46,remaining:23,unit:'lines'}});
  assert.equal(node('autoDubEta').textContent, 'Stage remaining: ≈ 12s');
  assert.equal(node('autoDubWorkCount').textContent, '23/46 lines processed · 23 remaining');
  assert.equal(node('runAutoDubBtn').disabled,true);
  context.updateAutoDubDashboard({project_id:'sample',status:'failed',failure_kind:'review',eta_seconds:null});
  assert.equal(node('autoDubEta').textContent, 'Dialogue timing review required');
  assert.equal(node('runAutoDubBtn').textContent, 'Resume Auto-Dub');
});

test('voice review submits JSON that the backend can validate', async () => {
  const handlers = {}, feedback = {textContent:''};
  const card = {querySelectorAll:()=>[{dataset:{review:'identity_confirmed'},type:'checkbox',checked:false}]};
  const save = {dataset:{voiceId:'voice'},closest:()=>card,nextElementSibling:feedback,
    addEventListener:(event,handler)=>{handlers.save=handler;}};
  const nodes = {
    voiceLibraryList:{innerHTML:'',querySelectorAll:selector=>selector==='.save-voice-review' ? [save] : []},
    voiceLibrarySummary:{textContent:''},
    loadVoiceLibraryBtn:{addEventListener:(event,handler)=>{handlers.load=handler;}},
    voiceLibrarySearch:{value:'',addEventListener(){}},
    voiceLibraryFilter:{value:'all',addEventListener(){}}
  };
  let submitted;
  const context = {window:{addEventListener(){}},document:{getElementById:id=>nodes[id]},escapeHtml:value=>String(value??''),
    api:async(url,options)=>{
      if(options){submitted=options;return {};}
      return {voices:[{character_id:'voice',character_name:'Voice'}],total:1,verified:0,clone_runtime:{}};
    }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/voice-library.js'),'utf8'),context);
  await handlers.load();
  await handlers.save();
  assert.equal(submitted.headers['Content-Type'],'application/json');
  assert.equal(JSON.parse(submitted.body).identity_confirmed,false);
  assert.equal(feedback.textContent,'Review saved. Refresh library for current readiness.');
});

test('reselecting a completed project restores a cleared final video source', () => {
  const start=source.indexOf('function measuredDubProgress(');
  const end=source.indexOf('\nfunction stopAutoDubPoller',start);
  const nodes={};const node=id=>nodes[id]??=( {textContent:'',disabled:false,dataset:{},style:{},parentElement:{setAttribute(){},removeAttribute(){}},classList:{toggle(){}},querySelectorAll:()=>[]} );
  node('finalVideoPreview').dataset.loadedProject='sample';node('finalVideoPreview').src='';
  const context={$:node,state:{selected:'sample',projects:[{id:'sample',source_path:'movie.mp4'}]},formatAutoDubTime:()=>''};
  vm.createContext(context);vm.runInContext(source.slice(start,end),context);
  context.updateAutoDubDashboard({project_id:'sample',status:'completed',auto_download_ready:true,rendered_video_revision:'new'});
  assert.ok(node('finalVideoPreview').src.includes('/sample/final-video'));
  const first=node('finalVideoPreview').src;
  context.updateAutoDubDashboard({project_id:'sample',status:'completed',auto_download_ready:true,rendered_video_revision:'newer'});
  assert.notEqual(node('finalVideoPreview').src,first);
});
