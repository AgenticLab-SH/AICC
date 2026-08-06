import assert from 'node:assert/strict';
import test from 'node:test';
import { guidanceCommands, runGuidance } from '../src/guidance.mjs';

test('guidance deploy generates directives before pruning managed skills', () => {
  const commands = guidanceCommands('deploy', '/fixture/aicc');
  assert.equal(commands.length, 2);
  assert.match(commands[0].args.join(' '), /deploy_directives\.ps1/);
  assert.match(commands[1].args.join(' '), /deploy_active_skills\.ps1/);
  assert.ok(commands[1].args.includes('-PruneManaged'));
});

test('guidance runner stops after the first failed gate', () => {
  let calls = 0;
  assert.throws(() => runGuidance('deploy', {
    root: '/fixture/aicc',
    stdio: 'pipe',
    spawnSync: () => {
      calls += 1;
      return { status: 7 };
    }
  }), /exit 7/);
  assert.equal(calls, 1);
});

test('unknown guidance action fails closed', () => {
  assert.throws(() => guidanceCommands('remove', '/fixture/aicc'), /알 수 없는 guidance 명령/);
});
