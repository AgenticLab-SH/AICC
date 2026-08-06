import assert from 'node:assert/strict';
import test from 'node:test';
import { searchCatalog, toolCatalog } from '../src/catalog.mjs';
import { renderMenu } from '../src/tui.mjs';

test('catalog covers every public AICC feature family', () => {
  const catalog = toolCatalog();
  const ids = new Set(catalog.items.map(item => item.id));
  for (const id of ['dashboard', 'status', 'codex', 'claude', 'ocx', 'accounts', 'workspace-mcp', 'workspace-publish', 'codex-agents', 'setup-check', 'cli-status', 'guidance-check']) {
    assert.equal(ids.has(id), true, `missing ${id}`);
  }
  assert.equal(new Set(catalog.items.map(item => item.id)).size, catalog.items.length);
});

test('catalog search works with tasks, descriptions, and Korean keywords', () => {
  assert.equal(searchCatalog('claude')[0].id, 'claude');
  assert.equal(searchCatalog('secure tunnel')[0].id, 'workspace-mcp');
  assert.equal(searchCatalog('하위 에이전트')[0].id, 'codex-agents');
  assert.equal(searchCatalog('no-such-tool').length, 0);
});

test('TUI menu renders a searchable selected command', () => {
  const view = renderMenu({ query: '설치', selected: 0, columns: 80 });
  assert.ok(view.items.length >= 1);
  assert.match(view.text, /설치 상태 점검/);
});

test('TUI menu limits output to the terminal height and keeps selection visible', () => {
  const selected = toolCatalog().items.findIndex(item => item.id === 'setup-check');
  const view = renderMenu({ selected, columns: 80, rows: 18 });
  assert.match(view.text, /설치 상태 점검/);
  assert.match(view.text, /위에 \d+개 더 있음/);
  assert.ok(view.text.split('\n').length <= 20);
});
