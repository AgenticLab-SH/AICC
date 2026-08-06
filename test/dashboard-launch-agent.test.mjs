import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { installDashboardLaunchAgent } from '../tools/platform/dashboard/install-launch-agent.mjs';

function fixture(t) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-dashboard-launchd-'));
  const root = path.join(home, 'AICC');
  const node = path.join(home, 'node');
  fs.mkdirSync(path.join(root, 'src'), { recursive: true });
  fs.writeFileSync(node, '#!/bin/sh\n');
  fs.writeFileSync(path.join(root, 'src', 'server.mjs'), '');
  fs.writeFileSync(path.join(root, 'package.json'), '{}');
  fs.chmodSync(node, 0o700);
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  return { home, root, node };
}

test('dashboard installer retries transient launchd bootstrap error 5', t => {
  const paths = fixture(t);
  let bootstrapCalls = 0;
  const pauses = [];
  const spawnSync = (command, args) => {
    if (command === 'plutil') return { status: 0, stdout: '', stderr: '' };
    if (args[0] === 'bootout') return { status: 0, stdout: '', stderr: '' };
    if (args[0] === 'print') return { status: 113, stdout: '', stderr: '' };
    bootstrapCalls += 1;
    return bootstrapCalls === 1
      ? { status: 5, stdout: '', stderr: 'Bootstrap failed: 5: Input/output error' }
      : { status: 0, stdout: '', stderr: '' };
  };
  const result = installDashboardLaunchAgent({
    ...paths,
    platform: 'darwin',
    uid: 501,
    spawnSync,
    pause: milliseconds => pauses.push(milliseconds)
  });
  assert.equal(result.ok, true);
  assert.equal(result.bootstrapAttempts, 2);
  assert.equal(bootstrapCalls, 2);
  assert.deepEqual(pauses, [150]);
});

test('dashboard installer does not hide a non-transient bootstrap failure', t => {
  const paths = fixture(t);
  const spawnSync = (command, args) => {
    if (command === 'plutil') return { status: 0, stdout: '', stderr: '' };
    if (args[0] === 'bootout') return { status: 0, stdout: '', stderr: '' };
    if (args[0] === 'print') return { status: 113, stdout: '', stderr: '' };
    return { status: 77, stdout: '', stderr: 'permission denied' };
  };
  assert.throws(
    () => installDashboardLaunchAgent({ ...paths, platform: 'darwin', uid: 501, spawnSync, pause: () => {} }),
    /permission denied/
  );
});
