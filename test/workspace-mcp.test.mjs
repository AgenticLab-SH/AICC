import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  buildWorkspaceMcpConfig, configureWorkspaceMcp, discoverGitWorkspaces,
  readWorkspaceMcpConfig, workspaceMcpCommand, workspaceMcpStatus
} from '../src/workspace-mcp.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-workspace-mcp-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test('discovers exact git workspaces without treating the parent as one workspace', t => {
  const root = fixture(t);
  const one = path.join(root, 'one');
  const two = path.join(root, 'group', 'two');
  fs.mkdirSync(path.join(one, '.git'), { recursive: true });
  fs.mkdirSync(path.join(two, '.git'), { recursive: true });
  fs.mkdirSync(path.join(root, 'node_modules', 'ignored', '.git'), { recursive: true });
  assert.deepEqual(discoverGitWorkspaces(root), [one, two].map(item => fs.realpathSync(item)).sort());
});

test('configures owner-local state and preserves all exact workspace roots without a listener port', t => {
  const projectsRoot = fixture(t);
  const stateRoot = fixture(t);
  const root = path.join(projectsRoot, 'aicc');
  fs.mkdirSync(path.join(root, '.git'), { recursive: true });
  const result = configureWorkspaceMcp({ projectsRoot, stateRoot });
  const stored = readWorkspaceMcpConfig({ stateRoot });
  assert.equal(result.workspaceCount, 1);
  assert.equal(stored.schemaVersion, 2);
  assert.equal(stored.transport.mode, 'secure-mcp-tunnel');
  assert.equal(stored.nativeGateways.codex.transport, 'codex-exec-and-app-server-stdio');
  assert.equal(stored.nativeGateways.codex.sandbox, 'workspace-write');
  assert.deepEqual(stored.workspaces.map(item => item.root), [fs.realpathSync(root)]);
  assert.equal('endpoint' in stored, false);
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(path.join(stateRoot, 'workspace-mcp', 'config.json')).mode & 0o777, 0o600);
  }
});

test('builds a direct AICC STDIO server command without a network listener', t => {
  const projectsRoot = fixture(t);
  const root = path.join(projectsRoot, 'repo');
  fs.mkdirSync(path.join(root, '.git'), { recursive: true });
  const config = buildWorkspaceMcpConfig({ projectsRoot });
  const command = workspaceMcpCommand(config, { nodeExecutable: '/fixture/node', configPath: '/fixture/config.json' });
  assert.equal(command.executable, '/fixture/node');
  assert.match(command.args[0].replaceAll('\\', '/'), /components\/workspace-mcp\/server\.mjs$/);
  assert.deepEqual(command.args.slice(1), ['--config', '/fixture/config.json']);
  assert.equal('endpoint' in command, false);
});

test('status distinguishes a configured STDIO runtime from missing configuration', async t => {
  const stateRoot = fixture(t);
  const missing = await workspaceMcpStatus({ stateRoot, timeoutMs: 10 });
  assert.equal(missing.state, 'unavailable');
  const projectsRoot = fixture(t);
  fs.mkdirSync(path.join(projectsRoot, 'repo', '.git'), { recursive: true });
  configureWorkspaceMcp({ projectsRoot, stateRoot });
  const ready = await workspaceMcpStatus({ stateRoot, tunnelProbe: async () => ({ running: true, healthy: true, ready: true }) });
  assert.equal(ready.state, 'ready');
  assert.equal(ready.serverReady, true);
  assert.equal(ready.workspaceCount, 1);
});
