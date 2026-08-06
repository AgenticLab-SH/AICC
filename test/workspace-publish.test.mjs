import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { recordWorkspacePublication, workspacePublicationStatus } from '../src/workspace-publish.mjs';

test('publication snapshot changes only after an explicit verified record', t => {
  const stateRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-workspace-publish-'));
  t.after(() => fs.rmSync(stateRoot, { recursive: true, force: true }));
  const before = workspacePublicationStatus({ stateRoot });
  assert.equal(before.manifest.toolCount, 13);
  assert.equal(before.manifest.readToolCount, 9);
  assert.equal(before.manifest.writeToolCount, 4);
  assert.equal(before.needsPublish, true);
  const recorded = recordWorkspacePublication({ stateRoot, appName: 'AICC Workspace' });
  assert.equal(recorded.needsPublish, false);
  assert.equal(recorded.published.appName, 'AICC Workspace');
  if (process.platform !== 'win32') assert.equal(fs.statSync(recorded.stateFile).mode & 0o777, 0o600);
});
