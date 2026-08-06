import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const html = fs.readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');
const canvas = JSON.parse(fs.readFileSync(new URL('../public/aicc-architecture.canvas', import.meta.url), 'utf8'));
const cutover = fs.readFileSync(new URL('../tools/platform/chatgpt/Complete-WebGptFullSetup.mjs', import.meta.url), 'utf8');

test('dashboard architecture map separates the two MCP tunnel roles', () => {
  assert.match(html, /Web GPT 작업 하네스 Tunnel/);
  assert.match(html, /AICC 원격 작업공간 Tunnel/);
  assert.match(html, /두 MCP는 AICC에서 함께 관리하지만/);
  assert.match(html, /이전 이름: Codex Native MCP · 네이티브 모델과 무관/);
});

test('source lineage distinguishes runtime dependencies from reference-only sources', () => {
  assert.match(html, /<span class="source-tag fork">Fork<\/span>/);
  assert.match(html, /<span class="source-tag pinned">Pinned submodule<\/span>/);
  assert.match(html, /Waishnav\/devspace/);
  assert.match(html, /자동 추적 안 함 · 새 아이디어 조사 때만 재검토/);
  assert.match(html, /AICC에 융합된 결과/);
  assert.match(html, /원본 릴리스 비교 후 AICC fork에 선택 반영/);
});

test('dashboard exposes the OCX operation modules without copying credentials', () => {
  for (const route of ['dashboard', 'startup', 'providers', 'models', 'combos', 'subagents', 'logs', 'usage']) {
    assert.match(html, new RegExp(`http://127\\.0\\.0\\.1:10100/#${route}`));
  }
  assert.match(html, /AICC는 OCX 자격증명을 복제하지 않습니다/);
});

test('downloadable JSON Canvas has valid node and edge references', () => {
  assert.ok(canvas.nodes.length >= 20);
  assert.ok(canvas.edges.length >= 10);
  const nodeIds = new Set(canvas.nodes.map(node => node.id));
  assert.equal(nodeIds.size, canvas.nodes.length);
  for (const edge of canvas.edges) {
    assert.ok(nodeIds.has(edge.fromNode), `missing fromNode: ${edge.fromNode}`);
    assert.ok(nodeIds.has(edge.toNode), `missing toNode: ${edge.toNode}`);
  }
});

test('Web GPT full cutover stages away from the active Codex route before returning to it', () => {
  assert.match(cutover, /stagingPortFor/);
  assert.match(cutover, /'--port', String\(stagingPort\)/);
  assert.match(cutover, /atomicJson\(configFile, \{ \.\.\.fullConfig, port \}\)/);
  assert.ok(cutover.indexOf("'--port', String(stagingPort)") < cutover.indexOf('terminate(originalPid)'));
});
