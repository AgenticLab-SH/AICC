import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from '../src/server.mjs';

test('server exposes local-control health, status, and allowlisted actions', async t => {
  const calls = [];
  const server = createServer({
    collectStatus: async () => ({ ok: true, schemaVersion: 1, components: [] }),
    actionController: {
      list: () => [{ name: 'ocx.start', title: 'OCX 시작', kind: 'provider' }],
      preview: async (action, args) => { calls.push(['preview', action, args]); return { ok: true, confirmationToken: 'token' }; },
      execute: async token => { calls.push(['execute', token]); return { ok: true }; }
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const { port } = server.address();

  const health = await fetch(`http://127.0.0.1:${port}/healthz`).then(response => response.json());
  assert.deepEqual(health, { ok: true, mode: 'local-control' });

  const status = await fetch(`http://127.0.0.1:${port}/api/status`).then(response => response.json());
  assert.equal(status.schemaVersion, 1);

  const actions = await fetch(`http://127.0.0.1:${port}/api/actions`).then(response => response.json());
  assert.equal(actions.actions[0].name, 'ocx.start');

  const catalog = await fetch(`http://127.0.0.1:${port}/api/catalog`).then(response => response.json());
  assert.ok(catalog.items.some(item => item.id === 'workspace-mcp'));

  const preview = await fetch(`http://127.0.0.1:${port}/api/actions/preview`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ action: 'ocx.start', args: {} })
  });
  assert.equal(preview.status, 200);
  assert.deepEqual(calls[0], ['preview', 'ocx.start', {}]);

  const execute = await fetch(`http://127.0.0.1:${port}/api/actions/execute`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ confirmationToken: 'token' })
  });
  assert.equal(execute.status, 200);
  assert.deepEqual(calls[1], ['execute', 'token']);
});

test('server runs only allowlisted local diagnostic tasks', async t => {
  const calls = [];
  const server = createServer({
    collectStatus: async () => ({ ok: true }),
    actionController: { list: () => [], preview: async () => ({}), execute: async () => ({}) },
    runTask: async taskId => { calls.push(taskId); return { ok: true, id: taskId, result: {} }; }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/tasks/run`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ taskId: 'workspace.status' })
  });
  assert.equal(response.status, 200);
  assert.deepEqual(calls, ['workspace.status']);
});

test('server returns completed diagnostic findings without treating them as a request failure', async t => {
  const server = createServer({
    collectStatus: async () => ({ ok: true }),
    actionController: { list: () => [], preview: async () => ({}), execute: async () => ({}) },
    runTask: async taskId => ({ ok: false, id: taskId, result: { attention: ['OCX 연결 확인 필요'] } })
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/tasks/run`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ taskId: 'workspace.status' })
  });
  const result = await response.json();
  assert.equal(response.status, 200);
  assert.equal(result.ok, false);
  assert.deepEqual(result.result.attention, ['OCX 연결 확인 필요']);
});

test('dashboard preserves completed diagnostic findings for display', async () => {
  const source = await import('node:fs/promises').then(fs => fs.readFile(new URL('../public/app.js', import.meta.url), 'utf8'));
  assert.match(source, /postJson\('\/api\/tasks\/run', \{ taskId: item\.taskId \}, \{ acceptFindings: true \}\)/);
  assert.match(source, /!data\.ok && !options\.acceptFindings/);
});

test('server opens only the named auth portal through the guarded endpoint', async t => {
  const calls = [];
  const server = createServer({
    collectStatus: async () => ({ ok: true }),
    actionController: { list: () => [], preview: async () => ({}), execute: async () => ({}) },
    openLocalApp: async appId => { calls.push(appId); return { ok: true, id: appId, url: 'https://login.example.test/' }; }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/apps/open`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ appId: 'auth-portal' })
  });
  assert.equal(response.status, 200);
  assert.deepEqual(calls, ['auth-portal']);
});

test('action endpoints reject form and cross-origin requests', async t => {
  const server = createServer({
    collectStatus: async () => ({ ok: true }),
    actionController: { list: () => [], preview: async () => ({ ok: true }), execute: async () => ({ ok: true }) }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const { port } = server.address();
  const endpoint = `http://127.0.0.1:${port}/api/actions/preview`;

  const form = await fetch(endpoint, { method: 'POST', body: 'action=ocx.start' });
  assert.equal(form.status, 415);
  const crossOrigin = await fetch(endpoint, {
    method: 'POST',
    headers: { 'content-type': 'application/json', origin: 'https://example.invalid' },
    body: JSON.stringify({ action: 'ocx.start' })
  });
  assert.equal(crossOrigin.status, 403);
});
