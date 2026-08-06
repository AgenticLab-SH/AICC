import assert from 'node:assert/strict';
import test from 'node:test';
import { componentPresentation, diagnosticPresentation } from '../public/presentation.js';

test('status diagnostics are summarized in plain language', () => {
  const view = diagnosticPresentation('status', {
    ok: true,
    durationMs: 230,
    result: { summary: { ready: 6, total: 6, attention: 0 } }
  });
  assert.equal(view.headline, '모든 핵심 연결이 정상입니다.');
  assert.deepEqual(view.highlights.map(item => item.value), ['6/6', '0개']);
});

test('guidance diagnostics total nested checks and name deployment targets', () => {
  const view = diagnosticPresentation('guidance.check', {
    ok: true,
    result: {
      failed_count: 0,
      checks: [
        { result: { check_count: 22, selected_target_groups: ['codex', 'claude'] } },
        { result: { check_count: 34, selected_target_groups: ['claude', 'codex'] } }
      ]
    }
  });
  assert.equal(view.headline, '지침과 스킬이 모두 일치합니다.');
  assert.match(view.detail, /56개/);
  assert.equal(view.highlights[1].value, 'Codex · Claude');
});

test('optional unavailable components are not presented as failures', () => {
  assert.deepEqual(componentPresentation({ optional: true, state: 'unavailable' }), {
    stateClass: 'optional',
    label: '선택 기능',
    hint: '설치하지 않아도 핵심 기능은 정상 동작합니다.'
  });
  assert.equal(componentPresentation({ state: 'degraded' }).label, '확인 필요');
});
