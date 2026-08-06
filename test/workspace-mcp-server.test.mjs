import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import {
  confinedPath,
  createWorkspaceMcpServer,
  loadConfig,
  sandboxProfile,
  __testing
} from '../components/workspace-mcp/server.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-mcp-server-'));
  const workspace = path.join(root, 'workspace');
  const runtime = path.join(root, 'runtime');
  fs.mkdirSync(path.join(workspace, '.git'), { recursive: true });
  fs.mkdirSync(runtime, { recursive: true });
  fs.writeFileSync(path.join(workspace, 'README.md'), '# fixture\n');
  fs.writeFileSync(path.join(workspace, '.env'), 'SECRET=nope\n');
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { root, workspace, runtime };
}

function config(workspace, skillRoots = []) {
  return {
    schemaVersion: 2,
    defaultWorkspace: 'fixture',
    workspaces: [{ alias: 'fixture', label: 'Fixture', root: workspace }],
    permissions: { commands: true, network: false, maxReadBytes: 1_048_576, maxOutputBytes: 262_144 },
    skillRoots
  };
}

async function clientFor(t, source, runtimeRoot) {
  const server = createWorkspaceMcpServer(source, { runtimeRoot });
  const client = new Client({ name: 'aicc-test', version: '1.0.0' });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  t.after(async () => { await client.close(); await server.close(); });
  return client;
}

function payload(result) {
  return result.structuredContent ?? JSON.parse(result.content.find(item => item.type === 'text').text);
}

test('configuration and path guard reject symlinks, traversal, and sensitive files', t => {
  const paths = fixture(t);
  const configFile = path.join(paths.root, 'config.json');
  fs.writeFileSync(configFile, JSON.stringify(config(paths.workspace)));
  const loaded = loadConfig(configFile);
  assert.equal(loaded.workspaces[0].root, fs.realpathSync(paths.workspace));
  assert.equal(confinedPath(paths.workspace, 'README.md'), fs.realpathSync(path.join(paths.workspace, 'README.md')));
  assert.throws(() => confinedPath(paths.workspace, '../outside'), /벗어납니다/);
  assert.throws(() => confinedPath(paths.workspace, '.env'), /민감 파일/);
  fs.symlinkSync(paths.root, path.join(paths.workspace, 'escape'));
  assert.throws(() => confinedPath(paths.workspace, 'escape/file.txt', { allowMissing: true }), /심볼릭 링크/);
});

test('fixed MCP surface opens only aliases and can read and inspect changes', async t => {
  const paths = fixture(t);
  const client = await clientFor(t, config(paths.workspace), paths.runtime);
  const listed = await client.listTools();
  const names = listed.tools.map(tool => tool.name).sort();
  assert.deepEqual(names, [
    'aicc_codex_task_archive', 'aicc_codex_task_create',
    'aicc_codex_task_list', 'aicc_codex_task_message', 'aicc_codex_task_read',
    'aicc_skill_inventory', 'aicc_skill_read', 'aicc_workspace_apply_patch',
    'aicc_workspace_changes', 'aicc_workspace_exec', 'aicc_workspace_list',
    'aicc_workspace_open', 'aicc_workspace_read', 'aicc_workspace_search',
    'aicc_workspace_write_stdin'
  ].sort());
  const rejected = await client.callTool({ name: 'aicc_workspace_open', arguments: { alias: '/tmp' } });
  assert.equal(rejected.isError, true);
  const opened = await client.callTool({ name: 'aicc_workspace_open', arguments: { alias: 'fixture' } });
  const binding = payload(opened);
  assert.match(binding.workspace_id, /^ws_/);
  assert.match(binding.lease, /^lease_/);
  const read = await client.callTool({ name: 'aicc_workspace_read', arguments: { workspace_id: binding.workspace_id, lease: binding.lease, path: 'README.md' } });
  assert.equal(payload(read).text, '# fixture\n');
  const secret = await client.callTool({ name: 'aicc_workspace_read', arguments: { workspace_id: binding.workspace_id, lease: binding.lease, path: '.env' } });
  assert.equal(secret.isError, true);

  if (process.platform === 'darwin') {
    const executed = await client.callTool({
      name: 'aicc_workspace_exec',
      arguments: { workspace_id: binding.workspace_id, lease: binding.lease, command: "printf 'sandbox-ok' > command-output.txt", yield_time_ms: 500 }
    });
    assert.equal(payload(executed).exit_code, 0, JSON.stringify(payload(executed)));
    assert.equal(fs.readFileSync(path.join(paths.workspace, 'command-output.txt'), 'utf8'), 'sandbox-ok');

    const patched = await client.callTool({
      name: 'aicc_workspace_apply_patch',
      arguments: {
        workspace_id: binding.workspace_id,
        lease: binding.lease,
        patch: '--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-# fixture\n+# patched\n'
      }
    });
    assert.equal(payload(patched).ok, true);
    assert.equal(fs.readFileSync(path.join(paths.workspace, 'README.md'), 'utf8'), '# patched\n');
  }
});

test('sandbox profile confines file access and patch headers are workspace-relative', t => {
  const paths = fixture(t);
  const profile = sandboxProfile(paths.workspace, paths.runtime, false);
  assert.match(profile, /deny file-read/);
  assert.match(profile, /deny file-write/);
  assert.match(profile, /deny network/);
  assert.deepEqual(__testing.validatePatchPaths(paths.workspace, '--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n'), ['README.md']);
  assert.throws(() => __testing.validatePatchPaths(paths.workspace, '--- a/README.md\n+++ b/../outside\n'), /벗어납니다/);
});
