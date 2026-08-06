import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  agentManifestName,
  agentsStatus,
  checkAgents,
  deployAgents,
  planAgents,
  resolveAgentRoots
} from '../src/agents.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-agents-'));
  const sourceRoot = path.join(root, 'source');
  const targetRoot = path.join(root, 'target');
  const backupRoot = path.join(root, 'backups');
  fs.mkdirSync(sourceRoot, { recursive: true });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { root, sourceRoot, targetRoot, backupRoot };
}

function write(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
}

function allFiles(root) {
  if (!fs.existsSync(root)) return [];
  return fs.readdirSync(root, { recursive: true, withFileTypes: true })
    .filter(entry => entry.isFile())
    .map(entry => path.join(entry.parentPath ?? entry.path, entry.name));
}

test('injected roots deploy and compare every canonical file while preserving unowned agents', t => {
  const roots = fixture(t);
  write(path.join(roots.sourceRoot, 'luna_worker.toml'), 'name = "luna_worker"\n');
  write(path.join(roots.sourceRoot, 'team', 'reviewer.toml'), 'name = "reviewer"\n');
  write(path.join(roots.targetRoot, 'personal.toml'), 'name = "personal"\n');

  const plan = planAgents(roots);
  assert.equal(plan.summary.comparedFiles, 2);
  assert.equal(plan.summary.create, 2);
  assert.deepEqual(plan.unownedFiles, ['personal.toml']);
  assert.match(plan.message, /Codex 에이전트/);

  const deployed = deployAgents(roots);
  assert.equal(deployed.changed, true);
  assert.equal(deployed.backupPath, null);
  assert.equal(fs.readFileSync(path.join(roots.targetRoot, 'personal.toml'), 'utf8'), 'name = "personal"\n');
  assert.equal(fs.readFileSync(path.join(roots.targetRoot, 'team', 'reviewer.toml'), 'utf8'), 'name = "reviewer"\n');

  const manifest = JSON.parse(fs.readFileSync(path.join(roots.targetRoot, agentManifestName), 'utf8'));
  assert.deepEqual(manifest.files, ['luna_worker.toml', 'team/reviewer.toml']);
  const checked = checkAgents(roots);
  assert.equal(checked.ok, true);
  assert.equal(checked.summary.comparedFiles, 2);
  assert.equal(agentsStatus(roots).state, 'ready');
});

test('deploy backs up overwrites and manifest-owned removals privately, then writes atomically', t => {
  const roots = fixture(t);
  write(path.join(roots.sourceRoot, 'worker.toml'), 'name = "worker"\nversion = 1\n');
  write(path.join(roots.sourceRoot, 'retired.toml'), 'name = "retired"\n');
  deployAgents(roots);

  write(path.join(roots.targetRoot, 'worker.toml'), 'name = "user-edited-worker"\n');
  write(path.join(roots.targetRoot, 'personal.toml'), 'name = "personal"\n');
  fs.unlinkSync(path.join(roots.sourceRoot, 'retired.toml'));
  write(path.join(roots.sourceRoot, 'worker.toml'), 'name = "worker"\nversion = 2\n');

  const deployed = deployAgents({ ...roots, now: () => new Date('2026-08-06T01:02:03Z') });
  assert.equal(deployed.summary.update, 1);
  assert.equal(deployed.summary.remove, 1);
  assert.ok(deployed.backupPath);
  assert.equal(fs.readFileSync(path.join(deployed.backupPath, 'worker.toml'), 'utf8'), 'name = "user-edited-worker"\n');
  assert.equal(fs.readFileSync(path.join(deployed.backupPath, 'retired.toml'), 'utf8'), 'name = "retired"\n');
  assert.equal(fs.existsSync(path.join(deployed.backupPath, agentManifestName)), true);
  assert.equal(fs.existsSync(path.join(roots.targetRoot, 'retired.toml')), false);
  assert.equal(fs.readFileSync(path.join(roots.targetRoot, 'worker.toml'), 'utf8'), 'name = "worker"\nversion = 2\n');
  assert.equal(fs.readFileSync(path.join(roots.targetRoot, 'personal.toml'), 'utf8'), 'name = "personal"\n');
  assert.equal(allFiles(roots.root).some(file => file.endsWith('.tmp')), false);

  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(deployed.backupPath).mode & 0o077, 0);
    assert.equal(fs.statSync(path.join(deployed.backupPath, 'worker.toml')).mode & 0o077, 0);
    assert.equal(fs.statSync(path.join(roots.targetRoot, 'worker.toml')).mode & 0o077, 0);
  }
  assert.equal(checkAgents(roots).ok, true);
});

test('an unowned colliding file is backed up before becoming managed', t => {
  const roots = fixture(t);
  write(path.join(roots.sourceRoot, 'worker.toml'), 'name = "canonical"\n');
  write(path.join(roots.targetRoot, 'worker.toml'), 'name = "unowned-existing"\n');

  const deployed = deployAgents({ ...roots, now: new Date('2026-08-06T02:00:00Z') });
  assert.ok(deployed.backupPath);
  assert.equal(fs.readFileSync(path.join(deployed.backupPath, 'worker.toml'), 'utf8'), 'name = "unowned-existing"\n');
  assert.equal(fs.readFileSync(path.join(roots.targetRoot, 'worker.toml'), 'utf8'), 'name = "canonical"\n');
});

test('only files owned by the previous manifest are pruned', t => {
  const roots = fixture(t);
  write(path.join(roots.targetRoot, 'unowned.toml'), 'name = "unowned"\n');
  write(path.join(roots.targetRoot, 'owned.toml'), 'name = "owned"\n');
  write(path.join(roots.targetRoot, agentManifestName), `${JSON.stringify({
    schemaVersion: 1,
    owner: 'ai-control-center',
    target: 'codex-agents',
    files: ['owned.toml']
  }, null, 2)}\n`);

  const deployed = deployAgents(roots);
  assert.equal(fs.existsSync(path.join(roots.targetRoot, 'owned.toml')), false);
  assert.equal(fs.existsSync(path.join(roots.targetRoot, 'unowned.toml')), true);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(roots.targetRoot, agentManifestName), 'utf8')).files, []);
  assert.equal(deployed.summary.unownedPreserved, 1);
});

test('check reports drift across files and the manifest without mutating the target', t => {
  const roots = fixture(t);
  write(path.join(roots.sourceRoot, 'a.toml'), 'name = "a"\n');
  write(path.join(roots.sourceRoot, 'b.toml'), 'name = "b"\n');
  deployAgents(roots);
  write(path.join(roots.targetRoot, 'a.toml'), 'name = "changed"\n');
  fs.unlinkSync(path.join(roots.targetRoot, 'b.toml'));

  const before = fs.readFileSync(path.join(roots.targetRoot, 'a.toml'));
  const checked = checkAgents(roots);
  assert.equal(checked.ok, false);
  assert.equal(checked.summary.comparedFiles, 2);
  assert.equal(checked.summary.update, 1);
  assert.equal(checked.summary.create, 1);
  assert.match(checked.message, /불일치/);
  assert.deepEqual(fs.readFileSync(path.join(roots.targetRoot, 'a.toml')), before);
  assert.equal(agentsStatus(roots).state, 'drift');
});

test('secret-like source assignments and untrusted manifests fail closed in Korean', t => {
  const roots = fixture(t);
  write(path.join(roots.sourceRoot, 'unsafe.toml'), 'name = "unsafe"\napi_key = "do-not-store-here"\n');
  assert.throws(() => planAgents(roots), /비밀/);

  write(path.join(roots.sourceRoot, 'unsafe.toml'), 'name = "safe"\n');
  write(path.join(roots.targetRoot, agentManifestName), '{not-json\n');
  assert.throws(() => deployAgents(roots), /소유권을 확인할 수 없어 중단/);
  const status = agentsStatus(roots);
  assert.equal(status.state, 'error');
  assert.match(status.message, /확인할 수 없습니다/);
});

test('default roots keep AICC as source and Codex home as target', () => {
  const roots = resolveAgentRoots({ aiccRoot: '/fixture/aicc', home: '/fixture/home' });
  assert.equal(roots.sourceRoot, path.resolve('/fixture/aicc/guidance/agents/codex'));
  assert.equal(roots.targetRoot, path.resolve('/fixture/home/.codex/agents'));
  assert.equal(roots.backupRoot, path.resolve('/fixture/home/.ai-control-center/backups/codex-agents'));
});
