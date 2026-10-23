const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../MachinesModel.js');
const now = Date.now();
const GB = 1024 ** 3;
function data(changes = {}) {
  return {cpu: {percent: 20, iowait: 0, steal: 0, load: [0.5, 0.5, 0.5], cores: 4}, net: {rx: 0, tx: 0}, io: {read: 0, write: 0},
    processes: {total: 100, running: 1, topCpu: [], topMem: []}, agents: {}, system: {hostname: 'h', os: 'Ubuntu', cores: 4, uptime: 3600},
    memory: {total: 16 * GB, used: 4 * GB, available: 12 * GB, swapTotal: 0, swapUsed: 0},
    disks: [{mount: '/', fs: 'ext4', total: 100 * GB, used: 40 * GB, free: 60 * GB, percent: 40}], temperature: null, gpus: [], containers: [], failed: [], ...changes};
}
function machine(changes = {}) { return {id: 'm', name: 'M', kind: 'vps', online: true, probedAt: now / 1000, data: data(), history: [], ...changes}; }
test('healthy machine is ok with cpu, ram and disk meters', () => {
  const v = M.machineView(machine(), now);
  assert.equal(v.state, 'ok');
  assert.deepEqual(v.metrics.map(m => m.key), ['cpu', 'memory', 'disk']);
  assert.equal(v.metrics[1].percent, 25);
});
test('full disk, failed unit and unhealthy container raise alerts', () => {
  const v = M.machineView(machine({data: data({
    disks: [{mount: '/', fs: 'ext4', total: 100 * GB, used: 90 * GB, free: 10 * GB, percent: 90}],
    failed: ['x.service'], containers: [{name: 'api', state: 'running', status: 'Up 2h (unhealthy)'}]})}), now);
  assert.equal(v.state, 'red');
  assert.equal(v.alerts.length, 3);
  assert.equal(v.metrics.find(m => m.key === 'disk').tone, 'yellow');
});
test('a nearly full disk alone is yellow, never red', () => {
  const v = M.machineView(machine({data: data({
    disks: [{mount: '/', fs: 'ext4', total: 100 * GB, used: 99 * GB, free: 1 * GB, percent: 99}]})}), now);
  assert.equal(v.state, 'yellow');
  assert.deepEqual(v.alerts.map(a => a.tone), ['yellow']);
  assert.equal(v.metrics.find(m => m.key === 'disk').tone, 'yellow');
});
test('the fullest disk is the one shown on the card', () => {
  const v = M.machineView(machine({data: data({disks: [
    {mount: '/', fs: 'ext4', total: 100 * GB, used: 10 * GB, free: 90 * GB, percent: 10},
    {mount: '/data', fs: 'ext4', total: 100 * GB, used: 80 * GB, free: 20 * GB, percent: 80}]})}), now);
  assert.match(v.metrics.find(m => m.key === 'disk').detail, /^\/data/);
});
test('offline vps is down, offline local machine is just off', () => {
  assert.equal(M.machineView(machine({online: false, error: 'timeout'}), now).state, 'down');
  assert.equal(M.machineView(machine({online: false, kind: 'local'}), now).state, 'off');
});
test('summary counts online machines and the ones needing attention', () => {
  const s = M.buildMachines({machines: [machine(), machine({id: 'b', online: false})]}, now);
  assert.equal(s.online, 1);
  assert.equal(s.attention, 1);
});
test('peer link text says direct, relay or last seen', () => {
  assert.equal(M.peerView({name: 'a', online: true, direct: true}, now).link, 'direto');
  assert.equal(M.peerView({name: 'a', online: true, direct: false, relay: 'sao'}, now).link, 'relay sao');
  assert.equal(M.peerView({name: 'a', online: false, lastSeen: new Date(now - 2 * 3600e3).toISOString()}, now).link, 'visto há 2h 0min');
});
test('loop images on a shared disk count as reserved, not used', () => {
  // Contabo: 871 GB root holding two preallocated 330 GB user disks.
  const v = M.machineView(machine({data: data({disks: [
    {mount: '/', fs: 'ext4', total: 871 * GB, used: 801 * GB, free: 71 * GB, percent: 92, reserved: 660 * GB, holds: ['/home/lucas', '/home/alonso']},
    {mount: '/home/lucas', fs: 'ext4', total: 324 * GB, used: 2 * GB, free: 319 * GB, percent: 1, image: '/srv/devs/lucas.ext4'}]})}), now);
  const disk = v.metrics.find(m => m.key === 'disk');
  assert.equal(Math.round(disk.percent), 67);
  assert.equal(disk.tone, 'green');
  assert.match(disk.detail, /660 GB reservados pra lucas e alonso/);
  assert.ok(!v.alerts.some(a => /Disco/.test(a.text)));
});
test('terminals show what runs in the foreground and how long they sit idle', () => {
  const v = M.machineView(machine({data: data({terminals: [
    {tty: 'pts/3', pid: 10, user: 'lol', shell: 'bash', fg: 'claude', fgPid: 11, procs: 4, idle: 5, age: 3700, agent: true},
    {tty: 'pts/4', pid: 20, user: 'lol', shell: 'bash', fg: 'bash', fgPid: 20, procs: 1, idle: 7200, age: 7300, agent: false}]})}), now);
  assert.equal(v.terminals[0].running, 'claude');
  assert.equal(v.terminals[0].idleText, 'ativo');
  assert.equal(v.terminals[1].running, '');
  assert.equal(v.terminals[1].idleText, 'parado há 2h 0min');
});
test('process list puts CPU first, then memory', () => {
  const v = M.machineView(machine({data: data({procs: [
    {pid: 1, name: 'a', user: 'x', cpu: 0, mem: 9 * GB}, {pid: 2, name: 'b', user: 'x', cpu: 50, mem: GB}]})}), now);
  assert.deepEqual(v.procs.map(p => p.name), ['b', 'a']);
});
test('a phone is off when unreachable and warns on low battery out of the plug', () => {
  assert.equal(M.machineView(machine({online: false, kind: 'local', adb: 'x:5555'}), now).state, 'off');
  const v = M.machineView(machine({adb: 'x:5555', data: data({platform: 'android', battery: {level: 9, plugged: false, temp: 30}})}), now);
  assert.equal(v.phone, true);
  assert.equal(v.state, 'yellow');
  assert.match(v.facts, /bateria 9%/);
});
test('actions go to act.py as plain arguments, never as a shell string', () => {
  assert.deepEqual(M.actCommand('/x/act.py', 'kill', 'lol', [42, 'bash; rm -rf /']),
    ['/usr/bin/python3', '/x/act.py', 'kill', 'lol', '42', 'bash; rm -rf /']);
});
test('android load average does not raise a load alert', () => {
  const v = M.machineView(machine({data: data({platform: 'android', cpu: {percent: 7, iowait: 0, steal: 0, load: [17, 17, 17], cores: 8}})}), now);
  assert.equal(v.alerts.length, 0);
});

test('a full but quiet swap stays green; pressure or no RAM left warn', () => {
  const mem = (changes) => ({total: 16 * GB, used: 10 * GB, available: 6 * GB, swapTotal: 4 * GB, swapUsed: 4 * GB, pressure: 0, ...changes});
  const view = (memory, swap = {in: 0, out: 0}) => M.machineView(machine({data: data({memory, swap})}), now);
  let v = view(mem());
  assert.equal(v.metrics.find(m => m.key === 'swap').tone, 'green');
  assert.equal(v.state, 'ok');
  assert.equal(v.alerts.length, 0);
  v = view(mem({pressure: 4}));
  assert.equal(v.metrics.find(m => m.key === 'swap').tone, 'yellow');
  assert.match(v.alerts[0].text, /pressão/);
  assert.equal(view(mem({pressure: 25})).alerts[0].tone, 'red');
  assert.ok(view(mem({available: 1 * GB, used: 15 * GB})).alerts.some(a => /OOM/.test(a.text)));
  assert.equal(view(mem(), {in: 5 * 1048576, out: 0}).alerts.length, 0);
});
test('probes without PSI keep the old swap percentage rule', () => {
  const v = M.machineView(machine({data: data({memory: {total: 16 * GB, used: 4 * GB, available: 12 * GB, swapTotal: 4 * GB, swapUsed: 4 * GB}})}), now);
  assert.equal(v.metrics.find(m => m.key === 'swap').tone, 'red');
  assert.match(v.alerts[0].text, /Swap em 100%/);
});
test('api machines carry their kind and group, and Railway shows vCPU instead of load', () => {
  const v = M.machineView(machine({api: 'railway', data: data({platform: 'railway', cpu: {percent: 1, iowait: 0, steal: 0, load: [0, 0, 0], cores: 24, used: 0.02},
    containers: [{name: 'a', state: 'running'}, {name: 'b', state: 'exited'}]})}), now);
  assert.equal(v.api, 'railway');
  assert.match(v.metrics[0].detail, /0\.02 de 24 vCPU/);
  assert.match(v.facts, /1\/2 serviços no ar/);
  assert.doesNotMatch(v.summary, /núcleos/);
  assert.equal(v.state, 'ok');
});
test('cluster nodes share one group row with the worst state', () => {
  const s = M.buildMachines({machines: [machine({id: 'a', group: 'NexUnio'}), machine({id: 'x'}),
    machine({id: 'b', group: 'NexUnio', online: false, data: null})]}, now);
  assert.deepEqual(s.groups, [{id: 'group:NexUnio', name: 'NexUnio', count: 2, state: 'down'}]);
});
test('capacity sums cores, RAM and disk of the machines that answered, leaving out Railway, phone and offline', () => {
  const big = data({cpu: {percent: 50, iowait: 0, steal: 0, load: [1, 1, 1], cores: 16},
    memory: {total: 64 * GB, used: 32 * GB, available: 32 * GB, swapTotal: 0, swapUsed: 0},
    // A shared disk holding a 300 GB image counts only what the system uses, and the image counts on its own.
    disks: [{mount: '/', fs: 'ext4', total: 400 * GB, used: 350 * GB, free: 50 * GB, percent: 88, reserved: 300 * GB, holds: ['/home/a']},
            {mount: '/home/a', fs: 'ext4', total: 300 * GB, used: 100 * GB, free: 200 * GB, percent: 33}]});
  const s = M.buildMachines({machines: [
    machine({id: 'pc', name: 'PC', kind: 'local', data: big, history: [[0, 40, 50], [1, 60, 50]]}),
    machine({id: 'vps', name: 'VPS', readonly: true, history: [[0, 10, 25], [1, 20, 25]]}),
    machine({id: 'rw', name: 'Railway', api: 'railway', data: data({platform: 'railway', cpu: {percent: 1, cores: 24, load: [0, 0, 0]}})}),
    machine({id: 'cel', name: 'Celular', adb: 'x', data: data({platform: 'android'})}),
    machine({id: 'nb', name: 'Notebook', kind: 'local', online: false, data: null})]}, now);
  const c = s.capacity;
  assert.equal(c.count, 2);
  assert.deepEqual(c.metrics.map(m => m.percent), [44, 45, 38]);
  assert.match(c.metrics[0].detail, /^8\.8 de 20 núcleos em uso · 11 livres$/);
  assert.match(c.metrics[2].detail, /^190 GB de 500 GB em uso · 310 GB livres$/);
  assert.deepEqual(c.left.map(x => x.name), ['Railway', 'Celular', 'Notebook']);
  assert.deepEqual(c.rows.map(r => r.id), ['pc', 'vps']);
  // Free capacity on our own machines excludes the watch-only host.
  assert.equal(c.free.cores, 8);
  assert.match(c.freeText, /1 máquinas nossas.*8 núcleos, 32\.0 GB de RAM/);
  // History is weighted by size: 16 cores at 60% and 4 at 20% make 52%.
  assert.deepEqual(c.cpuHistory, [34, 52]);
});
