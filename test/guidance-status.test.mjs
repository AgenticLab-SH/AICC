import assert from 'node:assert/strict';
import test from 'node:test';
import { guidanceStatus } from '../src/adapters/guidance-status.mjs';

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
