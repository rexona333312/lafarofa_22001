const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(__dirname + '/templates/index.html', 'utf8');
const code = html.slice(html.indexOf('  function sseRead('), html.indexOf('  function onMsg('));
const statusCode = html.slice(html.indexOf('  function projectStatus('), html.indexOf('  function pollProject('));
const status = {}; vm.createContext(status); vm.runInContext(statusCode, status);
assert.match(status.projectStatus({chunks: [], busy: true}), /Распознавание/);
assert.equal(status.projectStatus({chunks: [], busy: true, progress: 'WhisperX: 51%'}), 'WhisperX: 51%');
assert.match(status.projectStatus({chunks: [], busy: false, has_input: true}), /JSON для Codex готов/);
(async () => {
  for (const fail of [false, true]) {
    for (const phase of ['dl', 'asm', 'ready']) {
      let errors = 0, ended = 0;
      const context = {TextDecoder, S: {phase}, rdr: null, aborter: null,
        showErr: () => errors++, endRun: () => ended++, endAsm: () => ended++};
      vm.createContext(context); vm.runInContext(code, context);
      context.sseRead({body: {getReader: () => ({read: () => fail
        ? Promise.reject(new Error('offline')) : Promise.resolve({done: true})})}});
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(errors, phase === 'ready' ? 0 : 1);
      assert.equal(ended, phase === 'ready' ? 0 : 1);
    }
  }
  console.log('OK: disconnected stream stops the spinner; completed stream stays quiet');
})();
