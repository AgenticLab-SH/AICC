import assert from 'node:assert/strict';
import test from 'node:test';
import { runCommand } from '../src/lib/command.mjs';

test('runCommand captures successful JSON output', async () => {
  const result = await runCommand(process.execPath, ['-e', 'console.log(JSON.stringify({ok:true}))']);
  assert.equal(result.ok, true);
  assert.deepEqual(JSON.parse(result.stdout), { ok: true });
});

test('runCommand reports failure without throwing', async () => {
  const result = await runCommand(process.execPath, ['-e', 'process.exit(7)']);
  assert.equal(result.ok, false);
  assert.equal(result.exitCode, 7);
});

test('runCommand bounds slow commands', async () => {
  const result = await runCommand(process.execPath, ['-e', 'setTimeout(()=>{}, 10000)'], { timeoutMs: 30 });
  assert.equal(result.ok, false);
  assert.equal(result.timedOut, true);
});
