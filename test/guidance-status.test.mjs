import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { guidanceStatus, guidanceStatusQuick } from '../src/adapters/guidance-status.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

test('guidance status reports a clean deployment', () => {
  const status = guidanceStatus({
    root: '/fixture/aicc',
    spawnSync: () => ({
      status: 0,
      stdout: JSON.stringify({
        ok: true, failed_count: 0, check_count: 4,
        checks: [
          { name: 'skills', result: { central_skill_count: 16, deployment_issue_count: 0, manifest_issue_count: 0 } },
          { name: 'agents', result: { agent_count: 1, deployment_issue_count: 0, manifest_issue_count: 0 } }
        ]
      })
    })
  });
  assert.equal(status.state, 'ready');
  assert.equal(status.skillCount, 16);
  assert.equal(status.agentCount, 1);
});

test('guidance status reports deployment drift without throwing', () => {
  const status = guidanceStatus({
    root: '/fixture/aicc',
    spawnSync: () => ({
      status: 1,
      stdout: JSON.stringify({
        ok: false, failed_count: 1, check_count: 4,
        checks: [
          { name: 'skills', result: { central_skill_count: 16, deployment_issue_count: 2, manifest_issue_count: 0 } },
          { name: 'agents', result: { agent_count: 1, deployment_issue_count: 0, manifest_issue_count: 0 } }
        ]
      })
    })
  });
  assert.equal(status.state, 'attention');
  assert.match(status.detail, /불일치/);
  assert.equal(status.deploymentIssues, 2);
});

test('quick guidance status verifies source and deployed hashes without PowerShell', t => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-guidance-quick-'));
  t.after(() => fs.rmSync(fixture, { recursive: true, force: true }));
  const root = path.join(fixture, 'AICC');
  const home = path.join(fixture, 'home');
  const content = 'fixture\n';
  const digest = createHash('sha256').update(content).digest('hex').toUpperCase();
  for (const group of ['codex', 'claude']) {
    const source = path.join(root, 'guidance', 'skills', 'fixture-skill', 'SKILL.md');
    const target = path.join(home, `.${group}`, 'skills', 'fixture-skill', 'SKILL.md');
    fs.mkdirSync(path.dirname(source), { recursive: true });
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(source, content);
    fs.writeFileSync(target, content);
    fs.writeFileSync(path.join(home, `.${group}`, 'skills', '.aicc-guidance-deployment.json'), JSON.stringify({
      schema_version: 1, target_group: group, aicc_root: root,
      managed_skills: [{ name: 'fixture-skill', files: [{ path: 'SKILL.md', sha256: digest }] }]
    }));
  }
  for (const [source, target] of [
    ['guidance/directives/generated/codex/AGENTS.md', '.codex/AGENTS.md'],
    ['guidance/directives/generated/claude/AGENTS.md', '.claude/AGENTS.md'],
    ['guidance/directives/generated/claude/CLAUDE.md', '.claude/CLAUDE.md']
  ]) {
    fs.mkdirSync(path.dirname(path.join(root, source)), { recursive: true });
    fs.mkdirSync(path.dirname(path.join(home, target)), { recursive: true });
    fs.writeFileSync(path.join(root, source), content);
    fs.writeFileSync(path.join(home, target), content);
  }
  assert.equal(guidanceStatusQuick({ root, home }).state, 'ready');
  fs.writeFileSync(path.join(home, '.codex', 'skills', 'fixture-skill', 'SKILL.md'), 'drift\n');
  assert.equal(guidanceStatusQuick({ root, home }).state, 'attention');
});
