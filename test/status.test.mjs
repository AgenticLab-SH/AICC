import assert from 'node:assert/strict';
import test from 'node:test';
import { collectStatus } from '../src/status.mjs';

test('collectStatus merges adapters into one stable schema', async () => {
  const status = await collectStatus({
    accountStatus: async () => ({ id: 'accounts', label: 'Accounts', state: 'ready', detail: 'ok' }),
    ocxAccountStatus: async () => ({ id: 'ocx-accounts', label: 'OCX accounts', state: 'ready', detail: 'ok' }),
    ocxStatus: async () => ({ id: 'ocx', label: 'OCX', state: 'offline', detail: 'off' }),
    webGptStatus: async () => ({ id: 'web-gpt', state: 'unavailable', optional: true }),
    codexRouteStatus: async () => ({ id: 'codex-routes', state: 'ready' }),
    authPortalStatus: async () => ({ id: 'auth-portal', state: 'unavailable', optional: true }),
    guidanceStatus: () => ({ id: 'guidance', label: 'Guidance', state: 'ready', detail: 'ok' }),
    agentsStatus: () => ({ state: 'ready', message: 'ok', summary: {}, issues: [] }),
    workspaceMcpStatus: async () => ({ id: 'workspace-mcp', state: 'ready', detail: 'ok' }),
    localToolStatus: async () => [{ id: 'gpt-desktop', label: 'GPT Desktop', state: 'ready', detail: 'ok' }]
  });
  assert.equal(status.ok, true);
  assert.equal(status.schemaVersion, 1);
  assert.deepEqual(status.summary, { ready: 7, total: 8, attention: 1 });
  assert.equal(status.mode, 'local-control');
  assert.equal(status.stateRoots.length, 6);
});

test('unavailable optional integrations do not participate in the health summary', async () => {
  const status = await collectStatus({
    accountStatus: async () => ({ id: 'accounts', state: 'ready' }),
    ocxAccountStatus: async () => ({ id: 'ocx-accounts', state: 'ready' }),
    ocxStatus: async () => ({ id: 'ocx', state: 'ready' }),
    webGptStatus: async () => ({ id: 'web-gpt', state: 'unavailable', optional: true }),
    codexRouteStatus: async () => ({ id: 'codex-routes', state: 'ready' }),
    authPortalStatus: async () => ({ id: 'auth-portal', state: 'unavailable', optional: true }),
    guidanceStatus: () => ({ id: 'guidance', state: 'ready' }),
    agentsStatus: () => ({ state: 'ready', message: 'ok', summary: {}, issues: [] }),
    workspaceMcpStatus: async () => ({ id: 'workspace-mcp', state: 'ready' }),
    localToolStatus: async () => []
  });
  assert.deepEqual(status.summary, { ready: 7, total: 7, attention: 0 });
});

test('guidance drift participates in the health summary', async () => {
  const status = await collectStatus({
    accountStatus: async () => ({ id: 'accounts', state: 'ready' }),
    ocxAccountStatus: async () => ({ id: 'ocx-accounts', state: 'ready' }),
    ocxStatus: async () => ({ id: 'ocx', state: 'ready' }),
    webGptStatus: async () => ({ id: 'web-gpt', state: 'unavailable', optional: true }),
    codexRouteStatus: async () => ({ id: 'codex-routes', state: 'ready' }),
    authPortalStatus: async () => ({ id: 'auth-portal', state: 'unavailable', optional: true }),
    guidanceStatus: () => ({ id: 'guidance', state: 'attention', failed: 1 }),
    agentsStatus: () => ({ state: 'ready', message: 'ok', summary: {}, issues: [] }),
    workspaceMcpStatus: async () => ({ id: 'workspace-mcp', state: 'ready' }),
    localToolStatus: async () => []
  });
  assert.deepEqual(status.summary, { ready: 6, total: 7, attention: 1 });
});

test('one failed adapter is isolated from the remaining dashboard', async () => {
  const status = await collectStatus({
    accountStatus: async () => { throw new Error('fixture failure'); },
    ocxAccountStatus: async () => ({ id: 'ocx-accounts', state: 'ready' }),
    ocxStatus: async () => ({ id: 'ocx', state: 'ready' }),
    webGptStatus: async () => ({ id: 'web-gpt', state: 'ready' }),
    codexRouteStatus: async () => ({ id: 'codex-routes', state: 'ready' }),
    authPortalStatus: async () => ({ id: 'auth-portal', state: 'unavailable', optional: true }),
    guidanceStatus: () => ({ id: 'guidance', state: 'ready' }),
    agentsStatus: () => ({ state: 'ready', message: 'ok', summary: {}, issues: [] }),
    workspaceMcpStatus: async () => ({ id: 'workspace-mcp', state: 'ready' }),
    localToolStatus: async () => []
  });
  const accounts = status.components.find(component => component.id === 'accounts');
  assert.equal(status.ok, true);
  assert.equal(accounts.state, 'attention');
  assert.equal(accounts.isolatedFailure, true);
  assert.equal(status.components.find(component => component.id === 'ocx').state, 'ready');
});
