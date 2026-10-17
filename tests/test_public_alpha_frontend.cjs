const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
function display(data) {
  const start = source.indexOf('function measuredDubProgress(');
  assert.ok(start >= 0, 'Measured progress function is missing');
  const end = source.indexOf('\nfunction ', start + 1);
  const context = {};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  return context.measuredDubProgress(data);
}
test('Kaggle waiting does not report stale 99 percent completion', () => {
  const result = display({status:'waiting', progress_percent:99});
  assert.equal(result.label, 'Waiting for Kaggle');
  assert.equal(result.percent, null);
});
test('in progress counts describe the actual phase rather than whole movie', () => {
  const result = display({status:'running', progress_percent:99, work:{phase:'fit', completed:4, total:23}});
  assert.equal(result.label, 'fit · 4/23');
  assert.ok(result.percent > 17 && result.percent < 18);
});
test('completion requires actual download readiness', () => {
  assert.equal(display({status:'completed', auto_download_ready:true}).percent, 100);
  assert.notEqual(display({status:'completed', auto_download_ready:false}).percent, 100);
});

test('a previously accepted low-register voice does not outrank a matching high-register voice', () => {
  const workflow=fs.readFileSync('web/speaker-workflow.js','utf8');
  const start=workflow.indexOf('function rankCastingVoices(');
  assert.ok(start>=0,'Register-aware ranking is missing');
  const end=workflow.indexOf('\n(() =>',start);
  const context={};vm.createContext(context);vm.runInContext(workflow.slice(start,end),context);
  const ranked=context.rankCastingVoices([{voice_id:'lower',audition_accepted:true,vocal_type:'lower',pitch_median_hz:110},
    {voice_id:'higher',audition_accepted:false,vocal_type:'higher',pitch_median_hz:240}],{vocal_type:'higher',pitch_median_hz:248});
  assert.equal(ranked[0].voice_id,'higher');
});
