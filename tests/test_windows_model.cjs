const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../MachinesModel.js');
function view(health) {
  return M.machineView({id:'store', readonly:true, kind:'local', online:true, probedAt:Date.now()/1000,
    data:{platform:'windows', system:{uptime:3600, bootBrasilia:'12/11/2026 10:06'}, cpu:{percent:10,cores:16,load:[]},
      memory:{total:100,used:40}, net:null, containers:null, processes:null, health}}, Date.now());
}
test('Windows read-only snapshot exposes boot and cumulative health without fake traffic', () => {
  const v=view({smartAvailable:true,smart199:[{raw:3581}],eventsAvailable:true,eventWindowDays:30,
    unexpectedShutdowns:[{id:41,atBrasilia:'12/11/2026 09:12'},{id:6008}]});
  assert.equal(v.readonly,true);
  assert.match(v.summary,/boot 12\/11\/2026 10:06 BRT/);
  assert.match(v.facts,/3581 \(acumulado\)/);
  assert.match(v.facts,/eventos 41\/6008: 2 em 30 dias/);
  assert.match(v.facts,/09:12 BRT/);
  assert.doesNotMatch(v.facts,/B\/s/);
  assert.equal(v.metrics[0].detail,'16 processadores lógicos');
  assert.equal(v.state,'ok'); // historical counters do not prove a current fault
});
test('Windows unsupported health stays unknown rather than zero', () => {
  const v=view({smartAvailable:false,eventsAvailable:false});
  assert.match(v.facts,/SMART 199 indisponível/);
  assert.match(v.facts,/eventos de desligamento indisponíveis/);
  assert.doesNotMatch(v.facts,/: 0/);
});
