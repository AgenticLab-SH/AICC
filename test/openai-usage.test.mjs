import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { checkOpenaiCatalog } from '../src/openai-catalog-check.mjs';
import {
  complimentaryGroupForModel,
  configureOpenaiProvider,
  configureOpenaiProject,
  estimateOpenaiRequest,
  evaluateOpenaiMonitor,
  guardedOpenaiResponse,
  openaiCatalogProbePath,
  openaiMonitorPath,
  openaiProjectPolicyPath,
  openaiProjectStatus,
  openaiProviderPolicyPath,
  openaiProviderStatus,
  openaiUsagePath,
  openaiUsageStatus,
  probeAllOpenaiModels,
  resolveOpenaiProject
} from '../src/openai-usage.mjs';

function temporaryState(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-openai-usage-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const eligibilityFile = path.join(root, 'eligibility.json');
  fs.writeFileSync(eligibilityFile, JSON.stringify({
    schemaVersion: 1,
    source: 'test-fixture',
    declaredFamilies: [
      'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-nano',
      'gpt-4.1', 'gpt-4o', 'o1', 'o3', 'o3-mini', 'o4-mini'
    ],
    observedIncentiveModels: [],
    updatedAt: '2026-08-06T00:00:00Z'
  }), { mode: 0o600 });
  return {
    home: root,
    file: path.join(root, 'usage.json'),
    policyFile: path.join(root, 'projects.json'),
    providerFile: path.join(root, 'provider.json'),
    probeFile: path.join(root, 'model-probes.json'),
    catalogProbeFile: path.join(root, 'catalog-probe.json'),
    monitorFile: path.join(root, 'monitor.json'),
    catalogCheckFile: path.join(root, 'catalog-check.json'),
    eligibilityFile,
    project: { id: 'project-test', label: 'Test Project' },
    apiKey: 'test-only-key',
    now: new Date('2026-08-06T12:00:00Z')
  };
}

test('complimentary model groups match the two official pools', () => {
  assert.equal(complimentaryGroupForModel('gpt-5.4'), 'frontier');
  assert.equal(complimentaryGroupForModel('gpt-5.4-2026-03-05'), 'frontier');
  assert.equal(complimentaryGroupForModel('gpt-5.4-mini'), 'efficient');
  assert.equal(complimentaryGroupForModel('gpt-5.5'), 'frontier');
  assert.equal(complimentaryGroupForModel('gpt-5.6-sol'), 'frontier');
  assert.equal(complimentaryGroupForModel('gpt-5.6-terra'), 'efficient');
  assert.equal(complimentaryGroupForModel('gpt-5.6-luna'), 'efficient');
  assert.equal(complimentaryGroupForModel('gpt-image-2'), null);
});

test('usage status starts empty with a 95 percent hard guard', t => {
  const options = temporaryState(t);
  const status = openaiUsageStatus(options);
  assert.equal(status.keyConfigured, true);
  assert.equal(status.guard.hardStopPercent, 95);
  assert.equal(status.groups.find(group => group.id === 'frontier').freeLimit, 250_000);
  assert.equal(status.groups.find(group => group.id === 'efficient').hardLimit, 2_375_000);
});

test('guard records exact API usage per model without persisting prompts or keys', async t => {
  const options = temporaryState(t);
  options.fetchImpl = async (_url, request) => {
    assert.match(request.headers.authorization, /^Bearer /);
    return new Response(JSON.stringify({
      id: 'resp_test',
      model: 'gpt-5.4-mini-2026-03-17',
      output: [{ type: 'message', content: [{ type: 'output_text', text: '테스트 응답' }] }],
      usage: { input_tokens: 37, input_tokens_details: { cached_tokens: 8 }, output_tokens: 11 }
    }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  const result = await guardedOpenaiResponse({ model: 'gpt-5.4-mini', input: '짧은 테스트', maxOutputTokens: 64 }, options);
  assert.equal(result.text, '테스트 응답');
  assert.equal(result.usage.totalTokens, 48);
  const status = openaiUsageStatus(options);
  const row = status.groups.find(group => group.id === 'efficient').models[0];
  assert.equal(row.model, 'gpt-5.4-mini-2026-03-17');
  assert.equal(row.cachedInputTokens, 8);
  assert.equal(status.projects[0].label, 'Test Project');
  assert.equal(status.projects[0].tokens, 48);
  const persisted = fs.readFileSync(openaiUsagePath(options), 'utf8');
  assert.doesNotMatch(persisted, /짧은 테스트|test-only-key|테스트 응답/);
  if (process.platform !== 'win32') assert.equal(fs.statSync(openaiUsagePath(options)).mode & 0o077, 0);
});

test('project identity uses an opaque stable id and never exposes the supplied alias as a path', () => {
  const first = resolveOpenaiProject({ project: 'music-score-studio' });
  const second = resolveOpenaiProject({ project: 'music-score-studio' });
  assert.equal(first.id, second.id);
  assert.match(first.id, /^project-[0-9a-f]{12}$/);
  assert.equal(first.label, 'music-score-studio');
  assert.throws(() => resolveOpenaiProject({ project: '../escape' }), /프로젝트 이름/);
});

test('request estimate applies the default ten percent project budget without network use', t => {
  const options = temporaryState(t);
  const estimate = estimateOpenaiRequest({ model: 'gpt-5.4-mini', input: 'estimate only', maxOutputTokens: 64 }, options);
  assert.equal(estimate.groupId, 'efficient');
  assert.equal(estimate.project.limit, 237_500);
  assert.equal(estimate.project.customized, false);
  assert.equal(estimate.reservation, Buffer.byteLength(JSON.stringify('estimate only')) + 64);
});

test('provider catalog exposes all official models while defaulting agents to current efficient models', t => {
  const options = temporaryState(t);
  const status = openaiProviderStatus(options);
  assert.equal(status.enabled, true);
  assert.equal(status.defaultModel, 'gpt-5.6-luna');
  assert.ok(status.models.length >= 30);
  assert.equal(status.models.find(model => model.id === 'gpt-5.6-luna').agentSelectable, true);
  assert.equal(status.models.find(model => model.id === 'gpt-5.6-sol').agentSelectable, false);
  assert.equal(status.models.find(model => model.id === 'gpt-4.5-preview-2025-02-27').lifecycle, 'retired');
});

test('provider and model policy can stop all calls or restrict autonomous model selection', async t => {
  const options = temporaryState(t);
  let called = false;
  options.fetchImpl = async () => { called = true; return new Response('{}'); };
  await assert.rejects(
    guardedOpenaiResponse({ model: 'gpt-5.6-sol', input: 'agent choice', maxOutputTokens: 8 }, options),
    /에이전트가 선택할 수 없도록/
  );
  assert.equal(called, false);
  configureOpenaiProvider({ model: 'gpt-5.6-sol', callEnabled: true, agentSelectable: true }, options);
  configureOpenaiProvider({ defaultModel: 'gpt-5.6-sol' }, options);
  assert.equal(openaiProviderStatus(options).defaultModel, 'gpt-5.6-sol');
  configureOpenaiProvider({ enabled: false }, options);
  await assert.rejects(
    guardedOpenaiResponse({ input: 'disabled', maxOutputTokens: 8 }, options),
    /provider가 꺼져/
  );
  assert.equal(called, false);
  if (process.platform !== 'win32') assert.equal(fs.statSync(openaiProviderPolicyPath(options)).mode & 0o077, 0);
});

test('custom project budgets persist privately and block before network use', async t => {
  const options = temporaryState(t);
  const configured = configureOpenaiProject(options.project, { frontier: 20, efficient: 10 }, options);
  assert.equal(configured.customized, true);
  assert.equal(openaiProjectStatus(options).groups.find(group => group.id === 'efficient').limit, 10);
  if (process.platform !== 'win32') assert.equal(fs.statSync(openaiProjectPolicyPath(options)).mode & 0o077, 0);
  let called = false;
  options.fetchImpl = async () => { called = true; return new Response('{}'); };
  await assert.rejects(
    guardedOpenaiResponse({ model: 'gpt-5.4-mini', input: 'budget', maxOutputTokens: 8 }, options),
    /프로젝트의 경량 모델 풀 일일 한도/
  );
  assert.equal(called, false);
});

test('guard rejects non-complimentary models before network use', async t => {
  const options = temporaryState(t);
  let called = false;
  options.fetchImpl = async () => { called = true; return new Response('{}'); };
  await assert.rejects(
    guardedOpenaiResponse({ model: 'gpt-image-2', input: 'test', maxOutputTokens: 64 }, options),
    /공식 무료 대상 모델 목록에 없는 모델/
  );
  assert.equal(called, false);
});

test('guard blocks a request whose conservative reservation crosses the hard limit', async t => {
  const options = temporaryState(t);
  fs.mkdirSync(path.dirname(options.file), { recursive: true });
  fs.writeFileSync(options.file, JSON.stringify({
    schemaVersion: 1,
    dayUtc: '2026-08-06',
    updatedAt: '2026-08-06T11:00:00Z',
    models: { 'gpt-5.6-sol': { requests: 1, inputTokens: 237_400, cachedInputTokens: 0, outputTokens: 0 } }
  }), { mode: 0o600 });
  await assert.rejects(
    guardedOpenaiResponse({ model: 'gpt-5.6-sol', input: 'will not run', maxOutputTokens: 512, selectionSource: 'user' }, options),
    /95% 하드 한도/
  );
});

test('guard recovers an abandoned lock without weakening active-request exclusion', async t => {
  const options = temporaryState(t);
  options.lockStaleMs = 10;
  const lock = `${openaiUsagePath(options)}.lock`;
  fs.mkdirSync(path.dirname(lock), { recursive: true });
  fs.writeFileSync(lock, 'abandoned', { mode: 0o600 });
  const old = new Date(Date.now() - 60_000);
  fs.utimesSync(lock, old, old);
  options.fetchImpl = async () => new Response(JSON.stringify({
    id: 'resp_recovered', model: 'gpt-5.4-mini', output: [],
    usage: { input_tokens: 1, output_tokens: 1 }
  }), { status: 200, headers: { 'content-type': 'application/json' } });
  const result = await guardedOpenaiResponse({ model: 'gpt-5.4-mini', input: 'ok', maxOutputTokens: 1 }, options);
  assert.equal(result.ok, true);
  assert.equal(fs.existsSync(lock), false);
});

test('monitor warns at 80 percent and disables the provider at 90 percent', t => {
  const options = temporaryState(t);
  fs.mkdirSync(path.dirname(options.file), { recursive: true });
  fs.writeFileSync(options.file, JSON.stringify({
    schemaVersion: 2,
    dayUtc: '2026-08-06',
    updatedAt: '2026-08-06T11:00:00Z',
    models: { 'gpt-5.6-sol': { requests: 1, inputTokens: 225_000, cachedInputTokens: 0, outputTokens: 0, projects: {} } }
  }), { mode: 0o600 });
  const result = evaluateOpenaiMonitor(options);
  assert.equal(result.state, 'paused');
  assert.equal(result.groups.find(group => group.id === 'frontier').percent, 90);
  assert.equal(openaiProviderStatus(options).enabled, false);
  assert.ok(fs.existsSync(openaiMonitorPath(options)));
});

test('catalog probe attempts every account-verified model family and records comparable usage', async t => {
  const options = temporaryState(t);
  options.pacingMs = 0;
  options.fetchImpl = async (_url, request) => {
    const payload = JSON.parse(request.body);
    return new Response(JSON.stringify({
      id: `resp_${payload.model}`,
      model: payload.model,
      output: [{ type: 'message', content: [{ type: 'output_text', text: 'OK' }] }],
      usage: { input_tokens: 1, output_tokens: 1 }
    }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  const result = await probeAllOpenaiModels(options);
  assert.equal(result.total, 12);
  assert.equal(result.attempted, 12);
  assert.equal(result.available, 12);
  assert.equal(result.totalTokens, 24);
  assert.equal(JSON.parse(fs.readFileSync(openaiCatalogProbePath(options), 'utf8')).latest.status, 'completed');
});

test('OPENAI_API_KEY environment values are not accepted as an AICC credential source', t => {
  const options = temporaryState(t);
  delete options.apiKey;
  options.platform = 'linux';
  options.env = { OPENAI_API_KEY: 'must-not-be-used' };
  assert.equal(openaiProviderStatus(options).keyConfigured, false);
});

test('catalog checker detects exact complimentary additions without editing source', async t => {
  const options = temporaryState(t);
  const known = openaiProviderStatus(options).models.map(model => model.id);
  options.fetchImpl = async url => new Response(
    String(url).endsWith('.json')
      ? `${known.join(' ')} gpt-5.7-luna`
      : known.map(model => `- [${model}](/api/docs/models/${model.replace(/-\d{4}-\d{2}-\d{2}$/, '')}.md)`).join('\n'),
    { status: 200 }
  );
  const result = await checkOpenaiCatalog(options);
  assert.equal(result.status, 'drift_detected');
  assert.deepEqual(result.added, ['gpt-5.7-luna']);
  assert.deepEqual(result.removed, []);
});
