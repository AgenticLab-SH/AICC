import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { openLocalApp } from '../src/apps.mjs';

test('local app opener rejects arbitrary apps', async () => {
  await assert.rejects(() => openLocalApp('shell'), /허용되지 않은/);
});

test('auth portal opener returns only the configured public URL', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-auth-portal-'));
  const configPath = path.join(directory, 'auth-portal.env');
  fs.writeFileSync(configPath, 'CM_AUTH_PORTAL_URL=https://login.example.test/\nCM_AUTH_MACHINE_TOKEN=secret\n');
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const result = await openLocalApp('auth-portal', { env: { ...process.env, CM_AUTH_LOCAL_CONFIG: configPath } });
  assert.equal(result.url, 'https://login.example.test/');
  assert.equal(JSON.stringify(result).includes('secret'), false);
});
