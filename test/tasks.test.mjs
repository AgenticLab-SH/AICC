import assert from 'node:assert/strict';
import test from 'node:test';
import { listTasks, runTask } from '../src/tasks.mjs';

test('diagnostic task allowlist is explicit', () => {
  const ids = listTasks().map(task => task.id);
  assert.ok(ids.includes('workspace.status'));
  assert.ok(ids.includes('workspace.publish-preflight'));
  assert.ok(ids.includes('agents.status'));
  assert.ok(ids.includes('guidance.check'));
  assert.equal(ids.includes('shell'), false);
});

test('command task captures structured output without a shell', async () => {
  const result = await runTask('guidance.check', {
    runCommand: async (executable, args) => ({
      ok: true, exitCode: 0, durationMs: 4,
      stdout: JSON.stringify({ executable, args: args.slice(-1) }), stderr: ''
    })
  });
  assert.equal(result.ok, true);
  assert.equal(result.result.args.at(-1), '-AsJson');
});

test('unknown diagnostic task fails closed', async () => {
  await assert.rejects(() => runTask('shell.anything'), /허용되지 않은/);
});
