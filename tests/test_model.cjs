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
  assert.equal(v.metrics.find(m => m.key === 'disk').tone, 'red');
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
