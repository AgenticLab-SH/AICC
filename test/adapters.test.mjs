import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { accountStatus } from '../src/adapters/accounts.mjs';
import { authPortalStatus } from '../src/adapters/auth-portal.mjs';
import { ocxStatus } from '../src/adapters/ocx.mjs';
import { ocxAccountStatus } from '../src/adapters/ocx-accounts.mjs';
import { localToolStatus } from '../src/adapters/local-tools.mjs';
import { webGptStatus } from '../src/adapters/web-gpt.mjs';

test('account adapter accepts the masked cm JSON contract', async () => {
  const status = await accountStatus({
    command: { executable: 'cm-fixture', args: ['status', '--json'] },
    runCommand: async () => ({
      ok: true,
      stdout: JSON.stringify({
        ok: true,
        schema_version: 1,
        account_count: 1,
        active_account: 'account-one',
        accounts: [{ account: 'account-one', access_token: 'must-not-leak' }]
      })
    })
  });
  assert.equal(status.state, 'ready');
  assert.equal(status.accountCount, 1);
  assert.equal(status.accounts[0].access_token, '<redacted>');
});

test('account adapter fails closed on non-JSON output', async () => {
  const status = await accountStatus({
    command: { executable: 'cm-fixture', args: [] },
    runCommand: async () => ({ ok: true, stdout: 'not json' })
  });
  assert.equal(status.state, 'degraded');
  assert.equal(status.error, 'invalid JSON response');
});

test('OCX adapter combines installed version and health', async () => {
  const responses = new Map([
    ['--version', { ok: true, stdout: 'opencodex 2.7.42\n' }],
    ['health --json', { ok: true, stdout: JSON.stringify({ ok: true, pid: 42, port: 10100 }) }]
  ]);
  const status = await ocxStatus({
    executable: 'ocx-fixture',
    runCommand: async (_executable, args) => responses.get(args.join(' '))
  });
  assert.equal(status.state, 'ready');
  assert.equal(status.version, '2.7.42');
  assert.equal(status.runtime.port, 10100);
});

test('Web GPT adapter distinguishes a healthy bridge from an inactive Codex route', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-web-gpt-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const configPath = path.join(root, 'config.json');
  const codexConfigPath = path.join(root, 'codex.toml');
  fs.writeFileSync(configPath, JSON.stringify({ port: 17841, releaseVersion: '2.0.0', mode: 'full', browserHost: 'launcher' }));
  fs.writeFileSync(codexConfigPath, 'openai_base_url = "http://127.0.0.1:10100/v1"\n');
  const status = await webGptStatus({
    configPath, codexConfigPath, appPath: path.join(root, 'missing.app'),
    fetch: async () => ({ ok: true, json: async () => ({ status: 'ok', version: '2.0.0', active_browser_turns: 0 }) })
  });
  assert.equal(status.healthy, true);
  assert.equal(status.routeActive, false);
  assert.equal(status.state, 'attention');
  assert.equal(status.modelCount, 8);
  assert.ok(status.modelLabels.includes('Web / 임시 / 매우 높음'));
  assert.equal(status.modelLabels.some(label => label.endsWith('/ Pro')), false);
  assert.equal(status.localHarnessConsumesModelTokens, false);
});

test('OCX account adapter exposes only safe account metadata', async () => {
  const status = await ocxAccountStatus({
    executable: 'ocx-fixture',
    runCommand: async () => ({
      ok: true,
      stdout: JSON.stringify({ accounts: [{
        id: 'pool-one', label: 'Plus', email: 'f***t@example.test', plan: 'plus',
        active: true, needsReauth: false, accessToken: 'must-not-leak'
      }] })
    })
  });
  assert.equal(status.state, 'ready');
  assert.equal(status.activeId, 'pool-one');
  assert.equal('accessToken' in status.accounts[0], false);
});

test('auth portal adapter reads only the configured public URL', async () => {
  const status = await authPortalStatus({
    configPath: '/fixture/auth-portal.env',
    readFile: () => 'CM_AUTH_PORTAL_URL="https://login.example.test/path"\nCM_AUTH_MACHINE_TOKEN=secret\n'
  });
  assert.equal(status.state, 'ready');
  assert.equal(status.url, 'https://login.example.test/path');
  assert.equal(JSON.stringify(status).includes('secret'), false);
});

test('local tool defaults resolve only maintained embedded project locations', async () => {
  const tools = await localToolStatus();
  const manager = tools.find(item => item.id === 'account-manager');
  assert.equal(manager.path, path.resolve('components/account-manager'));
  assert.equal(manager.exists, true);
  assert.deepEqual(tools.map(item => item.id).sort(), ['account-manager', 'gpt-desktop']);
});
