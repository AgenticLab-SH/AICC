import assert from 'node:assert/strict';
import test from 'node:test';
import { cliToolStatus, pinnedCliPackages, setupCliTools } from '../src/cli-tools.mjs';

function result(ok, stdout = '') {
  return { ok, stdout, stderr: '', exitCode: ok ? 0 : 1 };
}

function fixtureRunner(options = {}) {
  const calls = [];
  let installed = options.installed ?? true;
  const runner = async (executable, args) => {
    calls.push([executable, args]);
    const wrapped = executable === 'cmd.exe' && args.slice(0, 3).join(' ') === '/d /s /c';
    const command = wrapped ? args[3] : executable;
    const commandArgs = wrapped ? args.slice(4) : args;
    if (command === 'npm') {
      installed = true;
      return result(true);
    }
    if (commandArgs[0] === '--version') return result(installed, `${command} 1.0\n`);
    if (commandArgs[0] === 'health') return result(true, '{"ok":true,"port":10100}');
    if (commandArgs[0] === 'system' && commandArgs[1] === 'status') {
      return result(true, JSON.stringify({ startup: { routingInjected: options.routingInjected ?? true } }));
    }
    if (commandArgs[0] === 'claude' && commandArgs[1] === 'config' && commandArgs[2] === 'status') {
      return result(true, JSON.stringify({ enabled: true, systemEnv: options.systemEnv ?? false }));
    }
    if (commandArgs[0] === 'claude' && commandArgs[1] === 'config' && commandArgs[2] === 'set') {
      options.systemEnv = true;
      return result(true, '{}');
    }
    if (commandArgs[0] === 'ensure') return result(true);
    return result(false);
  };
  return { calls, runner };
}

test('CLI status distinguishes OCX wrapper from direct macOS Claude routing', async () => {
  const fixture = fixtureRunner({ installed: true, systemEnv: false });
  const status = await cliToolStatus({ runCommand: fixture.runner, env: {}, platform: 'darwin' });
  assert.equal(status.ok, true);
  assert.equal(status.routing.codex, 'ocx');
  assert.equal(status.routing.claude, 'ocx-wrapper');
});

test('CLI setup installs exact packages and enables direct Claude routing on macOS', async () => {
  const fixture = fixtureRunner({ installed: false, systemEnv: false });
  const status = await setupCliTools({
    runCommand: fixture.runner,
    env: {},
    platform: 'darwin',
    nodeMajor: 22,
    installMissing: true
  });
  assert.deepEqual(status.installed, [pinnedCliPackages.ocx, pinnedCliPackages.codex, pinnedCliPackages.claude]);
  assert.equal(status.routing.codex, 'ocx');
  assert.equal(status.routing.claude, 'ocx-direct');
  assert.ok(fixture.calls.some(([, args]) => args.join(' ') === 'ensure'));
  assert.ok(fixture.calls.some(([, args]) => args.join(' ') === 'claude config set --enabled on --system-env on --json'));
});

test('CLI status fails closed when Codex routing is not injected', async () => {
  const fixture = fixtureRunner({ installed: true, routingInjected: false });
  const status = await cliToolStatus({ runCommand: fixture.runner, env: {}, platform: 'darwin' });
  assert.equal(status.ok, false);
  assert.equal(status.codexConnected, false);
  assert.equal(status.routing.codex, 'unavailable');
});

test('CLI setup reports missing commands without changing the host', async () => {
  const fixture = fixtureRunner({ installed: false });
  const status = await setupCliTools({ runCommand: fixture.runner, env: {}, platform: 'linux' });
  assert.equal(status.ok, false);
  assert.deepEqual(status.missing, ['ocx', 'codex', 'claude']);
  assert.equal(fixture.calls.some(([executable]) => executable === 'npm'), false);
});

test('Node 20 fails before partially installing CLI packages', async () => {
  const fixture = fixtureRunner({ installed: false });
  await assert.rejects(
    setupCliTools({ runCommand: fixture.runner, env: {}, platform: 'linux', nodeMajor: 20, installMissing: true }),
    /아무 CLI도 설치하지 않았습니다/
  );
  assert.equal(fixture.calls.some(([executable]) => executable === 'npm'), false);
});

test('Windows CLI checks use cmd.exe for npm command shims', async () => {
  const fixture = fixtureRunner({ installed: true });
  const status = await cliToolStatus({ runCommand: fixture.runner, env: {}, platform: 'win32' });
  assert.equal(status.ok, true);
  assert.ok(fixture.calls.every(([executable]) => executable === 'cmd.exe'));
});
