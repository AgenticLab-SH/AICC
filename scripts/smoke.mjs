import assert from 'node:assert/strict';
import { startServer } from '../src/server.mjs';

const fixture = {
  ok: true,
  schemaVersion: 1,
  mode: 'local-control',
  generatedAt: new Date().toISOString(),
  summary: { ready: 2, total: 2, attention: 0 },
  components: [
    { id: 'accounts', label: 'GPT 계정', state: 'ready', detail: '2개 계정 조회' },
    { id: 'ocx', label: 'OCX 모델 연결', state: 'ready', detail: 'OCX가 실행 중입니다.' }
  ],
  stateRoots: []
};

const server = startServer({ host: '127.0.0.1', port: 0, collectStatus: async () => fixture });
await new Promise(resolve => server.once('listening', resolve));
const { port } = server.address();

try {
  const statusResponse = await fetch(`http://127.0.0.1:${port}/api/status`);
  assert.equal(statusResponse.status, 200);
  assert.deepEqual(await statusResponse.json(), fixture);

  const pageResponse = await fetch(`http://127.0.0.1:${port}/`);
  const page = await pageResponse.text();
  assert.equal(pageResponse.status, 200);
  assert.match(page, /AI Control Center/);
  assert.match(page, /무엇을 할까요/);
  assert.match(pageResponse.headers.get('content-security-policy'), /default-src/);

  const catalogResponse = await fetch(`http://127.0.0.1:${port}/api/catalog`);
  const catalog = await catalogResponse.json();
  assert.equal(catalogResponse.status, 200);
  assert.ok(catalog.items.some(item => item.id === 'guidance-check'));
  console.log(`Smoke passed on 127.0.0.1:${port}: status API and dashboard are reachable.`);
} finally {
  await new Promise(resolve => server.close(resolve));
}
