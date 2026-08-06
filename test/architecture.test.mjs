import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const html = fs.readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');
const canvas = JSON.parse(fs.readFileSync(new URL('../public/aicc-architecture.canvas', import.meta.url), 'utf8'));
const cutover = fs.readFileSync(new URL('../tools/platform/chatgpt/Complete-WebGptFullSetup.mjs', import.meta.url), 'utf8');

test('dashboard architecture map separates the two MCP tunnel roles', () => {
  assert.match(html, /Codex Native MCP Tunnel/);
  assert.match(html, /AICC Workspace Tunnel/);
  assert.match(html, /두 Tunnel은 운영 화면에서 함께 관리하되 전송 경로는 분리/);
});

test('source lineage distinguishes runtime dependencies from reference-only sources', () => {
  assert.match(html, /FORK · 업데이트 추적/);
  assert.match(html, /PINNED SUBMODULE · 업데이트 추적/);
  assert.match(html, /Waishnav\/devspace/);
  assert.match(html, /아이디어만 참고 · 자동 추적 안 함/);
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
