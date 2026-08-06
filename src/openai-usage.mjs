import fs from 'node:fs';
import crypto from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const COMPLIMENTARY_SOURCE = 'https://help.openai.com/en/articles/10306912-sharing-feedback-evals-and-api-data-with-openai';
const PRICING_SOURCE = 'https://developers.openai.com/api/docs/models';
const CATALOG_AS_OF = '2026-08-06';

const GROUPS = {
  frontier: { label: '고성능 모델 풀', freeLimit: 250_000, publishedLimit: 1_000_000, hardLimit: 237_500 },
  efficient: { label: '경량 모델 풀', freeLimit: 2_500_000, publishedLimit: 10_000_000, hardLimit: 2_375_000 }
};

const price = (input, cachedInput, output) => ({ input, cachedInput, output });
const model = (id, label, group, pricing, options = {}) => ({ id, label, group, pricing, aliases: [], lifecycle: 'legacy', defaultCallEnabled: false, defaultAgentSelectable: false, ...options });

// Exact request IDs from the official complimentary-token article. Aliases are accepted only
// as local conveniences and are always rewritten to the exact eligible request ID before use.
const MODELS = [
  model('gpt-5.6-sol', 'GPT-5.6 Sol', 'frontier', price(5, 0.5, 30), { aliases: ['gpt-5.6'], lifecycle: 'current', role: '최고 품질·복잡한 전문 작업', defaultCallEnabled: true }),
  model('gpt-5.5-2026-04-23', 'GPT-5.5', 'frontier', price(5, 0.5, 30), { aliases: ['gpt-5.5'], role: '이전 세대 고성능 작업' }),
  model('gpt-5.4-2026-03-05', 'GPT-5.4', 'frontier', price(2.5, 0.25, 15), { aliases: ['gpt-5.4'], role: '이전 세대 코딩·전문 작업' }),
  model('gpt-5.2-2025-12-11', 'GPT-5.2', 'frontier', price(1.75, 0.175, 14), { aliases: ['gpt-5.2'], role: '이전 세대 전문 작업' }),
  model('gpt-5.1-2025-11-13', 'GPT-5.1', 'frontier', price(1.25, 0.125, 10), { aliases: ['gpt-5.1'], role: '이전 세대 에이전트 작업' }),
  model('gpt-5.1-codex', 'GPT-5.1 Codex', 'frontier', price(1.25, 0.125, 10), { role: '레거시 Codex 작업' }),
  model('gpt-5-codex', 'GPT-5 Codex', 'frontier', price(1.25, 0.125, 10), { role: '레거시 Codex 작업' }),
  model('gpt-5-2025-08-07', 'GPT-5', 'frontier', price(1.25, 0.125, 10), { aliases: ['gpt-5'], role: '레거시 추론·코딩' }),
  model('gpt-5-chat-latest', 'GPT-5 Chat', 'frontier', price(1.25, 0.125, 10), { role: '레거시 대화 모델' }),
  model('gpt-4.5-preview-2025-02-27', 'GPT-4.5 Preview', 'frontier', null, { lifecycle: 'retired', role: '종료된 모델' }),
  model('gpt-4.1-2025-04-14', 'GPT-4.1', 'frontier', price(2, 0.5, 8), { aliases: ['gpt-4.1'], role: '비추론 지시 수행' }),
  model('gpt-4o-2024-05-13', 'GPT-4o · 2024-05-13', 'frontier', price(2.5, 1.25, 10), { role: '레거시 멀티모달' }),
  model('gpt-4o-2024-08-06', 'GPT-4o · 2024-08-06', 'frontier', price(2.5, 1.25, 10), { aliases: ['gpt-4o'], role: '레거시 멀티모달' }),
  model('gpt-4o-2024-11-20', 'GPT-4o · 2024-11-20', 'frontier', price(2.5, 1.25, 10), { role: '레거시 멀티모달' }),
  model('o3-2025-04-16', 'o3', 'frontier', price(2, 0.5, 8), { aliases: ['o3'], role: '레거시 복합 추론' }),
  model('o1-preview-2024-09-12', 'o1 Preview', 'frontier', price(15, 7.5, 60), { lifecycle: 'retired', role: '종료된 미리보기' }),
  model('o1-2024-12-17', 'o1', 'frontier', price(15, 7.5, 60), { aliases: ['o1'], role: '레거시 고비용 추론' }),

  model('gpt-5.6-terra', 'GPT-5.6 Terra', 'efficient', price(2.5, 0.25, 15), { lifecycle: 'current', role: '품질·비용 균형', defaultCallEnabled: true, defaultAgentSelectable: true }),
  model('gpt-5.6-luna', 'GPT-5.6 Luna', 'efficient', price(1, 0.1, 6), { lifecycle: 'current', role: '빠른 일상·대량 작업', defaultCallEnabled: true, defaultAgentSelectable: true }),
  model('gpt-5.4-mini-2026-03-17', 'GPT-5.4 mini', 'efficient', price(0.75, 0.075, 4.5), { aliases: ['gpt-5.4-mini'], role: '코딩·컴퓨터 사용·하위 작업', defaultCallEnabled: true, defaultAgentSelectable: true }),
  model('gpt-5.4-nano-2026-03-17', 'GPT-5.4 nano', 'efficient', price(0.2, 0.02, 1.25), { aliases: ['gpt-5.4-nano'], role: '분류·추출·랭킹', defaultCallEnabled: true, defaultAgentSelectable: true }),
  model('gpt-5.1-codex-mini', 'GPT-5.1 Codex mini', 'efficient', price(0.25, 0.025, 2), { role: '레거시 Codex 경량 작업' }),
  model('gpt-5-mini-2025-08-07', 'GPT-5 mini', 'efficient', price(0.25, 0.025, 2), { aliases: ['gpt-5-mini'], role: '정형화된 저지연 작업' }),
  model('gpt-5-nano-2025-08-07', 'GPT-5 nano', 'efficient', price(0.05, 0.005, 0.4), { aliases: ['gpt-5-nano'], role: '초저가 단순 작업' }),
  model('gpt-4.1-mini-2025-04-14', 'GPT-4.1 mini', 'efficient', price(0.4, 0.1, 1.6), { aliases: ['gpt-4.1-mini'], role: '레거시 경량 지시 수행' }),
  model('gpt-4.1-nano-2025-04-14', 'GPT-4.1 nano', 'efficient', price(0.1, 0.025, 0.4), { aliases: ['gpt-4.1-nano'], role: '레거시 초경량 작업' }),
  model('gpt-4o-mini-2024-07-18', 'GPT-4o mini', 'efficient', price(0.15, 0.075, 0.6), { aliases: ['gpt-4o-mini'], role: '레거시 소형 멀티모달' }),
  model('o4-mini-2025-04-16', 'o4-mini', 'efficient', price(1.1, 0.275, 4.4), { aliases: ['o4-mini'], role: '레거시 경량 추론' }),
  model('o1-mini-2024-09-12', 'o1-mini', 'efficient', price(1.1, 0.55, 4.4), { aliases: ['o1-mini'], role: '레거시 소형 추론' }),
  model('codex-mini-latest', 'Codex mini', 'efficient', price(1.5, 0.375, 6), { role: '레거시 Codex CLI 특화' })
];

const MODEL_BY_ID = new Map(MODELS.map(item => [item.id, item]));
const MODEL_BY_INPUT = new Map(MODELS.flatMap(item => [item.id, ...item.aliases].map(candidate => [candidate, item])));
const DEFAULT_MODEL = 'gpt-5.6-luna';

const DEFAULT_PROJECT_LIMIT_PERCENT = 10;

function utcDay(date = new Date()) {
  return date.toISOString().slice(0, 10);
}

function stateRoot(env = process.env, home = os.homedir()) {
  return env.AICC_STATE_ROOT?.trim() || path.join(home, '.ai-control-center');
}

export function openaiUsagePath(options = {}) {
  return options.file || path.join(stateRoot(options.env, options.home), 'openai-usage', 'usage.json');
}

export function openaiProjectPolicyPath(options = {}) {
  return options.policyFile || path.join(stateRoot(options.env, options.home), 'openai-usage', 'projects.json');
}

export function openaiProviderPolicyPath(options = {}) {
  return options.providerFile || path.join(stateRoot(options.env, options.home), 'openai-usage', 'provider.json');
}

export function openaiModelProbePath(options = {}) {
  return options.probeFile || path.join(stateRoot(options.env, options.home), 'openai-usage', 'model-probes.json');
}

function atomicJsonWrite(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, file);
  if (process.platform !== 'win32') fs.chmodSync(file, 0o600);
}

function booleanValue(value, label) {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === '1') return true;
  if (value === 'false' || value === '0') return false;
  throw new Error(`${label} 값은 true 또는 false여야 합니다.`);
}

function modelDefinition(input) {
  const definition = MODEL_BY_INPUT.get(String(input || '').trim());
  if (!definition) throw new Error(`공식 무료 대상 모델 목록에 없는 모델입니다: ${input}`);
  if (definition.lifecycle === 'retired') throw new Error(`공식 무료 목록에는 남아 있지만 현재 종료된 모델입니다: ${definition.id}`);
  return definition;
}

function emptyProviderPolicy() {
  return { schemaVersion: 1, enabled: true, defaultModel: DEFAULT_MODEL, updatedAt: null, models: {} };
}

function readProviderPolicy(options = {}) {
  try {
    const parsed = JSON.parse(fs.readFileSync(openaiProviderPolicyPath(options), 'utf8'));
    if (parsed.schemaVersion !== 1 || !parsed.models || typeof parsed.models !== 'object') return emptyProviderPolicy();
    return { ...emptyProviderPolicy(), ...parsed, models: parsed.models };
  } catch (error) {
    if (error.code === 'ENOENT') return emptyProviderPolicy();
    throw new Error(`OpenAI provider 정책을 읽을 수 없습니다: ${error.message}`);
  }
}

function effectiveModelPolicy(definition, policy) {
  const stored = policy.models[definition.id] || {};
  const callEnabled = stored.callEnabled ?? definition.defaultCallEnabled;
  return {
    callEnabled,
    agentSelectable: callEnabled && (stored.agentSelectable ?? definition.defaultAgentSelectable)
  };
}

function writeProviderPolicy(policy, options = {}) {
  policy.updatedAt = new Date(options.now || Date.now()).toISOString();
  atomicJsonWrite(openaiProviderPolicyPath(options), policy);
}

export function configureOpenaiProvider(change, options = {}) {
  const policy = readProviderPolicy(options);
  if (Object.hasOwn(change, 'enabled')) policy.enabled = booleanValue(change.enabled, 'API 활성화');
  if (Object.hasOwn(change, 'defaultModel')) {
    const definition = modelDefinition(change.defaultModel);
    const effective = effectiveModelPolicy(definition, policy);
    if (!effective.callEnabled) throw new Error('기본 모델은 먼저 API 호출을 허용해야 합니다.');
    if (!effective.agentSelectable) throw new Error('기본 모델은 에이전트 선택도 허용해야 합니다.');
    policy.defaultModel = definition.id;
  }
  if (change.model) {
    const definition = modelDefinition(change.model);
    const current = effectiveModelPolicy(definition, policy);
    const callEnabled = Object.hasOwn(change, 'callEnabled') ? booleanValue(change.callEnabled, '모델 API 허용') : current.callEnabled;
    const agentSelectable = callEnabled && (Object.hasOwn(change, 'agentSelectable') ? booleanValue(change.agentSelectable, '에이전트 선택 허용') : current.agentSelectable);
    policy.models[definition.id] = { callEnabled, agentSelectable };
    if (!callEnabled && policy.defaultModel === definition.id) {
      const fallback = MODELS.find(candidate => candidate.id !== definition.id && effectiveModelPolicy(candidate, policy).agentSelectable);
      if (!fallback) throw new Error('마지막 에이전트 선택 가능 모델은 끌 수 없습니다. 다른 기본 모델을 먼저 허용하세요.');
      policy.defaultModel = fallback.id;
    }
  }
  writeProviderPolicy(policy, options);
  return openaiProviderStatus(options);
}

function emptyProbes() {
  return { schemaVersion: 1, updatedAt: null, models: {} };
}

function readModelProbes(options = {}) {
  try {
    const parsed = JSON.parse(fs.readFileSync(openaiModelProbePath(options), 'utf8'));
    return parsed.schemaVersion === 1 && parsed.models && typeof parsed.models === 'object' ? parsed : emptyProbes();
  } catch (error) {
    if (error.code === 'ENOENT') return emptyProbes();
    throw new Error(`OpenAI 모델 확인 기록을 읽을 수 없습니다: ${error.message}`);
  }
}

function recordModelProbe(modelId, result, options = {}) {
  const probes = readModelProbes(options);
  const checkedAt = new Date(options.now || Date.now()).toISOString();
  probes.models[modelId] = { ...result, checkedAt };
  probes.updatedAt = checkedAt;
  atomicJsonWrite(openaiModelProbePath(options), probes);
}

function safeProjectName(value) {
  const normalized = String(value || '').trim().normalize('NFKC');
  if (!normalized || normalized.length > 80 || !/^[\p{L}\p{N}._ -]+$/u.test(normalized)) {
    throw new Error('프로젝트 이름은 글자·숫자·점·밑줄·하이픈·공백으로 1~80자여야 합니다.');
  }
  return normalized;
}

function projectIdFromSource(source) {
  return `project-${crypto.createHash('sha256').update(source).digest('hex').slice(0, 12)}`;
}

function normalizedRemote(remote) {
  const value = String(remote || '').trim();
  if (!value) return null;
  try {
    const parsed = new URL(value);
    parsed.username = '';
    parsed.password = '';
    return parsed.toString().replace(/\/$/, '').replace(/\.git$/, '');
  } catch {
    return value.replace(/^[^@]+@/, '').replace(/\.git$/, '');
  }
}

export function resolveOpenaiProject(options = {}) {
  if (options.project && typeof options.project === 'object') {
    return { id: safeProjectName(options.project.id), label: safeProjectName(options.project.label || options.project.id), identity: 'provided' };
  }
  if (typeof options.project === 'string' && options.project.trim()) {
    const label = safeProjectName(options.project);
    return { id: projectIdFromSource(`alias:${label.toLocaleLowerCase('en-US')}`), label, identity: 'alias' };
  }
  const cwd = path.resolve(options.cwd || process.cwd());
  const runner = options.spawnSync || spawnSync;
  const gitRootResult = runner('git', ['rev-parse', '--show-toplevel'], { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 2_000 });
  const root = gitRootResult.status === 0 ? gitRootResult.stdout.trim() : cwd;
  const remoteResult = runner('git', ['config', '--get', 'remote.origin.url'], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 2_000 });
  const remote = remoteResult.status === 0 ? normalizedRemote(remoteResult.stdout) : null;
  const label = safeProjectName(path.basename(root) || 'local-project');
  return { id: projectIdFromSource(remote ? `remote:${remote}` : `path:${fs.realpathSync(root)}`), label, identity: remote ? 'git-remote-hash' : 'local-path-hash' };
}

function emptyPolicies() {
  return { schemaVersion: 1, updatedAt: null, projects: {} };
}

function readPolicies(options = {}) {
  try {
    const parsed = JSON.parse(fs.readFileSync(openaiProjectPolicyPath(options), 'utf8'));
    return parsed.schemaVersion === 1 && parsed.projects && typeof parsed.projects === 'object' ? parsed : emptyPolicies();
  } catch (error) {
    if (error.code === 'ENOENT') return emptyPolicies();
    throw new Error(`OpenAI 프로젝트 정책을 읽을 수 없습니다: ${error.message}`);
  }
}

function defaultProjectLimits() {
  return Object.fromEntries(Object.entries(GROUPS).map(([id, group]) => [id, Math.floor(group.hardLimit * DEFAULT_PROJECT_LIMIT_PERCENT / 100)]));
}

function projectPolicy(project, options = {}) {
  const stored = readPolicies(options).projects[project.id];
  return { project, limits: { ...defaultProjectLimits(), ...(stored?.limits || {}) }, customized: Boolean(stored) };
}

export function configureOpenaiProject(projectInput, limits, options = {}) {
  const project = resolveOpenaiProject({ ...options, project: projectInput });
  const normalized = {};
  for (const [groupId, group] of Object.entries(GROUPS)) {
    const value = Number(limits[groupId]);
    if (!Number.isInteger(value) || value < 1 || value > group.hardLimit) {
      throw new Error(`${group.label} 프로젝트 한도는 1~${group.hardLimit.toLocaleString()} 정수여야 합니다.`);
    }
    normalized[groupId] = value;
  }
  const policies = readPolicies(options);
  policies.projects[project.id] = { label: project.label, limits: normalized, updatedAt: new Date(options.now || Date.now()).toISOString() };
  policies.updatedAt = policies.projects[project.id].updatedAt;
  atomicJsonWrite(openaiProjectPolicyPath(options), policies);
  return openaiProjectStatus({ ...options, project });
}

function emptyLedger(day = utcDay()) {
  return { schemaVersion: 2, dayUtc: day, updatedAt: null, models: {} };
}

function readLedger(options = {}) {
  const file = openaiUsagePath(options);
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (![1, 2].includes(parsed.schemaVersion) || parsed.dayUtc !== utcDay(options.now)) return emptyLedger(utcDay(options.now));
    if (parsed.schemaVersion === 1) {
      parsed.schemaVersion = 2;
      for (const usage of Object.values(parsed.models || {})) {
        usage.projects = {
          'legacy-unattributed': {
            label: '기존 미분류 호출', requests: usage.requests || 0, inputTokens: usage.inputTokens || 0,
            cachedInputTokens: usage.cachedInputTokens || 0, outputTokens: usage.outputTokens || 0
          }
        };
      }
    }
    return parsed;
  } catch (error) {
    if (error.code === 'ENOENT') return emptyLedger(utcDay(options.now));
    throw new Error(`OpenAI 사용량 원장을 읽을 수 없습니다: ${error.message}`);
  }
}

function writeLedger(ledger, options = {}) {
  atomicJsonWrite(openaiUsagePath(options), ledger);
}

export function complimentaryGroupForModel(model) {
  return MODEL_BY_INPUT.get(String(model || '').trim())?.group || null;
}

function keyFromKeychain(options = {}) {
  if (options.apiKey) return options.apiKey;
  if (options.env?.OPENAI_API_KEY || process.env.OPENAI_API_KEY) return options.env?.OPENAI_API_KEY || process.env.OPENAI_API_KEY;
  if (process.platform !== 'darwin') return null;
  const result = spawnSync('security', ['find-generic-password', '-s', 'OpenAI API', '-a', 'personal-default', '-w'], {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 3_000
  });
  return result.status === 0 ? result.stdout.trim() : null;
}

function modelCost(model, usage) {
  const pricing = MODEL_BY_INPUT.get(String(model || '').trim())?.pricing;
  if (!pricing) return null;
  const uncachedInput = Math.max(0, usage.inputTokens - usage.cachedInputTokens);
  return ((uncachedInput * pricing.input) + (usage.cachedInputTokens * pricing.cachedInput) + (usage.outputTokens * pricing.output)) / 1_000_000;
}

function usageTotal(usage = {}) {
  return (usage.inputTokens || 0) + (usage.outputTokens || 0);
}

function projectUsageForGroup(ledger, projectId, groupId) {
  return Object.entries(ledger.models || {})
    .filter(([model]) => complimentaryGroupForModel(model) === groupId)
    .reduce((sum, [, usage]) => sum + usageTotal(usage.projects?.[projectId]), 0);
}

function projectSummaries(ledger, options = {}) {
  const projects = new Map();
  for (const [model, usage] of Object.entries(ledger.models || {})) {
    for (const [projectId, projectUsage] of Object.entries(usage.projects || {})) {
      const summary = projects.get(projectId) || { id: projectId, label: projectUsage.label || projectId, requests: 0, tokens: 0, models: new Map() };
      summary.requests += projectUsage.requests || 0;
      summary.tokens += usageTotal(projectUsage);
      summary.models.set(model, {
        model,
        requests: projectUsage.requests || 0,
        inputTokens: projectUsage.inputTokens || 0,
        cachedInputTokens: projectUsage.cachedInputTokens || 0,
        outputTokens: projectUsage.outputTokens || 0,
        totalTokens: usageTotal(projectUsage)
      });
      projects.set(projectId, summary);
    }
  }
  return Array.from(projects.values()).map(summary => {
    const policy = projectPolicy({ id: summary.id, label: summary.label }, options);
    return {
      ...summary,
      models: Array.from(summary.models.values()).sort((left, right) => right.totalTokens - left.totalTokens),
      groups: Object.entries(GROUPS).map(([id, group]) => {
        const tokens = projectUsageForGroup(ledger, summary.id, id);
        const limit = policy.limits[id];
        return { id, label: group.label, tokens, limit, percent: Number((tokens / limit * 100).toFixed(2)), remaining: Math.max(0, limit - tokens) };
      }),
      customized: policy.customized
    };
  }).sort((left, right) => right.tokens - left.tokens);
}

export function openaiProjectStatus(options = {}) {
  const project = resolveOpenaiProject(options);
  const ledger = readLedger(options);
  const policy = projectPolicy(project, options);
  return {
    ok: true,
    source: 'local-project-guard',
    dayUtc: ledger.dayUtc,
    project,
    customized: policy.customized,
    defaultLimitPercent: DEFAULT_PROJECT_LIMIT_PERCENT,
    groups: Object.entries(GROUPS).map(([id, group]) => {
      const tokens = projectUsageForGroup(ledger, project.id, id);
      const limit = policy.limits[id];
      return { id, label: group.label, tokens, limit, percent: Number((tokens / limit * 100).toFixed(2)), remaining: Math.max(0, limit - tokens) };
    })
  };
}

function usageForDefinition(ledger, definition) {
  const totals = { requests: 0, inputTokens: 0, cachedInputTokens: 0, outputTokens: 0 };
  for (const [storedModel, usage] of Object.entries(ledger.models || {})) {
    if (MODEL_BY_INPUT.get(storedModel)?.id !== definition.id) continue;
    totals.requests += usage.requests || 0;
    totals.inputTokens += usage.inputTokens || 0;
    totals.cachedInputTokens += usage.cachedInputTokens || 0;
    totals.outputTokens += usage.outputTokens || 0;
  }
  return { ...totals, totalTokens: usageTotal(totals) };
}

export function openaiProviderSnapshot(status) {
  const provider = status?.provider || status;
  return {
    enabled: Boolean(provider?.enabled),
    defaultModel: provider?.defaultModel || null,
    models: Object.fromEntries((provider?.models || []).map(item => [item.id, {
      callEnabled: Boolean(item.callEnabled),
      agentSelectable: Boolean(item.agentSelectable)
    }]))
  };
}

export function openaiProviderStatus(options = {}) {
  const ledger = readLedger(options);
  const policy = readProviderPolicy(options);
  const probes = readModelProbes(options);
  const groupUsed = Object.fromEntries(Object.keys(GROUPS).map(groupId => [groupId,
    Object.entries(ledger.models || {})
      .filter(([storedModel]) => complimentaryGroupForModel(storedModel) === groupId)
      .reduce((sum, [, usage]) => sum + usageTotal(usage), 0)
  ]));
  const models = MODELS.map(definition => {
    const usage = usageForDefinition(ledger, definition);
    const effective = definition.lifecycle === 'retired'
      ? { callEnabled: false, agentSelectable: false }
      : effectiveModelPolicy(definition, policy);
    const probe = probes.models[definition.id] || null;
    const pool = GROUPS[definition.group];
    return {
      id: definition.id,
      label: definition.label,
      aliases: definition.aliases,
      groupId: definition.group,
      groupLabel: pool.label,
      lifecycle: definition.lifecycle,
      role: definition.role,
      pricing: definition.pricing,
      callEnabled: effective.callEnabled,
      agentSelectable: effective.agentSelectable,
      isDefault: policy.defaultModel === definition.id,
      usage: {
        ...usage,
        sharedPoolPercent: Number((usage.totalTokens / pool.freeLimit * 100).toFixed(4)),
        shareOfUsedPool: groupUsed[definition.group] ? Number((usage.totalTokens / groupUsed[definition.group] * 100).toFixed(2)) : 0,
        estimatedStandardCostUsd: modelCost(definition.id, usage)
      },
      availability: definition.lifecycle === 'retired'
        ? { status: 'retired', checkedAt: null }
        : probe || { status: 'untested', checkedAt: null }
    };
  });
  return {
    ok: true,
    source: 'official-complimentary-catalog-plus-local-probes',
    enabled: policy.enabled,
    defaultModel: policy.defaultModel,
    updatedAt: policy.updatedAt,
    keyConfigured: Boolean(keyFromKeychain(options)),
    catalog: {
      asOf: CATALOG_AS_OF,
      complimentarySource: COMPLIMENTARY_SOURCE,
      pricingSource: PRICING_SOURCE,
      discovery: '공식 무료 목록을 정본으로 사용하고 실제 계정 접근은 모델별 최소 호출로 확인합니다.',
      modelListScopeRequired: false
    },
    models
  };
}

export function openaiUsageStatus(options = {}) {
  const ledger = readLedger(options);
  const groups = Object.entries(GROUPS).map(([id, definition]) => {
    const rows = Object.entries(ledger.models)
      .filter(([model]) => complimentaryGroupForModel(model) === id)
      .map(([model, usage]) => ({
        model: MODEL_BY_INPUT.get(model)?.id || model,
        label: MODEL_BY_INPUT.get(model)?.label || model,
        requests: usage.requests || 0,
        inputTokens: usage.inputTokens || 0,
        cachedInputTokens: usage.cachedInputTokens || 0,
        outputTokens: usage.outputTokens || 0,
        totalTokens: (usage.inputTokens || 0) + (usage.outputTokens || 0),
        estimatedStandardCostUsd: modelCost(model, usage)
      }))
      .sort((left, right) => right.totalTokens - left.totalTokens);
    const tokens = rows.reduce((sum, row) => sum + row.totalTokens, 0);
    return {
      id,
      label: definition.label,
      freeLimit: definition.freeLimit,
      hardLimit: definition.hardLimit,
      tokens,
      percent: definition.freeLimit ? Number((tokens / definition.freeLimit * 100).toFixed(2)) : 0,
      hardRemaining: Math.max(0, definition.hardLimit - tokens),
      models: rows
    };
  });
  return {
    ok: true,
    source: 'local-guard-ledger',
    dayUtc: ledger.dayUtc,
    resetAtUtc: new Date(new Date(`${ledger.dayUtc}T00:00:00Z`).getTime() + 86_400_000).toISOString(),
    updatedAt: ledger.updatedAt,
    keyConfigured: Boolean(keyFromKeychain(options)),
    guard: { enabled: readProviderPolicy(options).enabled, paidModelsBlocked: true, hardStopPercent: 95 },
    pricing: { asOf: CATALOG_AS_OF, currency: 'USD', source: PRICING_SOURCE },
    groups,
    provider: openaiProviderStatus(options),
    projects: projectSummaries(ledger, options),
    note: '즉시 집계는 AICC guard를 통과한 요청만 포함합니다. OpenAI 조직 Usage API는 Admin API key가 있어야 하며 지연될 수 있습니다.'
  };
}

async function withLedgerLock(callback, options = {}) {
  const file = openaiUsagePath(options);
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const lock = `${file}.lock`;
  let descriptor;
  try {
    descriptor = fs.openSync(lock, 'wx', 0o600);
  } catch (error) {
    if (error.code === 'EEXIST') {
      let stale = false;
      try {
        const ageMs = Date.now() - fs.statSync(lock).mtimeMs;
        stale = ageMs > (options.lockStaleMs || 5 * 60_000);
      } catch (statError) {
        if (statError.code !== 'ENOENT') throw statError;
      }
      if (!stale) throw new Error('다른 OpenAI guard 요청이 진행 중입니다. 잠시 뒤 다시 시도하세요.');
      try { fs.unlinkSync(lock); } catch (unlinkError) {
        if (unlinkError.code !== 'ENOENT') throw unlinkError;
      }
      try {
        descriptor = fs.openSync(lock, 'wx', 0o600);
      } catch (retryError) {
        if (retryError.code === 'EEXIST') throw new Error('다른 OpenAI guard 요청이 진행 중입니다. 잠시 뒤 다시 시도하세요.');
        throw retryError;
      }
    } else {
      throw error;
    }
  }
  try { return await callback(); }
  finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
    try { fs.unlinkSync(lock); } catch {}
  }
}

function reserveCheck(definition, input, maxOutputTokens, project, selectionSource, options = {}) {
  const providerPolicy = readProviderPolicy(options);
  if (!providerPolicy.enabled) throw new Error('AICC OpenAI API provider가 꺼져 있습니다.');
  const effective = effectiveModelPolicy(definition, providerPolicy);
  if (!options.probe && !effective.callEnabled) throw new Error(`AICC에서 API 호출이 꺼진 모델입니다: ${definition.id}`);
  if (!options.probe && selectionSource === 'agent' && !effective.agentSelectable) throw new Error(`에이전트가 선택할 수 없도록 설정된 모델입니다: ${definition.id}`);
  const groupId = definition.group;
  const group = GROUPS[groupId];
  const ledger = readLedger(options);
  const used = Object.entries(ledger.models)
    .filter(([candidate]) => complimentaryGroupForModel(candidate) === groupId)
    .reduce((sum, [, usage]) => sum + (usage.inputTokens || 0) + (usage.outputTokens || 0), 0);
  const conservativeInputUpperBound = Buffer.byteLength(JSON.stringify(input), 'utf8');
  const reservation = conservativeInputUpperBound + maxOutputTokens;
  if (used + reservation > group.hardLimit) {
    throw new Error(`${group.label}의 로컬 95% 하드 한도에 도달할 수 있어 요청을 차단했습니다. 현재 ${used.toLocaleString()} token, 예약 ${reservation.toLocaleString()} token.`);
  }
  const policy = projectPolicy(project, options);
  const projectUsed = projectUsageForGroup(ledger, project.id, groupId);
  const projectLimit = policy.limits[groupId];
  if (projectUsed + reservation > projectLimit) {
    throw new Error(`${project.label} 프로젝트의 ${group.label} 일일 한도에 도달할 수 있어 요청을 차단했습니다. 현재 ${projectUsed.toLocaleString()} token, 예약 ${reservation.toLocaleString()} token, 한도 ${projectLimit.toLocaleString()} token.`);
  }
  return {
    groupId,
    reservation,
    global: { used, limit: group.hardLimit, remainingAfterReservation: group.hardLimit - used - reservation },
    project: { ...project, used: projectUsed, limit: projectLimit, remainingAfterReservation: projectLimit - projectUsed - reservation, customized: policy.customized }
  };
}

function responseText(response) {
  return (response.output || []).flatMap(item => item.content || []).filter(item => item.type === 'output_text').map(item => item.text).join('\n');
}

export function estimateOpenaiRequest(request, options = {}) {
  const policy = readProviderPolicy(options);
  const requestedModel = String(request.model || policy.defaultModel).trim();
  const definition = modelDefinition(requestedModel);
  const maxOutputTokens = Number(request.maxOutputTokens || 512);
  const input = request.input;
  if (!Number.isInteger(maxOutputTokens) || maxOutputTokens < 1 || maxOutputTokens > 16_384) throw new Error('maxOutputTokens는 1~16384 정수여야 합니다.');
  if (typeof input !== 'string' || !input.trim()) throw new Error('빈 입력은 보낼 수 없습니다.');
  const project = resolveOpenaiProject({ ...options, project: request.project ?? options.project });
  const selectionSource = request.selectionSource === 'user' ? 'user' : 'agent';
  return { ok: true, requestedModel, model: definition.id, selectionSource, maxOutputTokens, ...reserveCheck(definition, input, maxOutputTokens, project, selectionSource, options) };
}

export async function guardedOpenaiResponse(request, options = {}) {
  const policy = readProviderPolicy(options);
  const requestedModel = String(request.model || policy.defaultModel).trim();
  const definition = modelDefinition(requestedModel);
  const effectiveModel = definition.id;
  const maxOutputTokens = Number(request.maxOutputTokens || 512);
  if (!Number.isInteger(maxOutputTokens) || maxOutputTokens < 1 || maxOutputTokens > 16_384) throw new Error('maxOutputTokens는 1~16384 정수여야 합니다.');
  const input = request.input;
  if (typeof input !== 'string' || !input.trim()) throw new Error('빈 입력은 보낼 수 없습니다.');
  const apiKey = keyFromKeychain(options);
  if (!apiKey) throw new Error('macOS Keychain의 OpenAI API / personal-default 키를 찾을 수 없습니다.');
  const project = resolveOpenaiProject({ ...options, project: request.project ?? options.project });
  const selectionSource = request.selectionSource === 'user' ? 'user' : 'agent';

  return withLedgerLock(async () => {
    reserveCheck(definition, input, maxOutputTokens, project, selectionSource, options);
    const fetchImpl = options.fetchImpl || fetch;
    const apiResponse = await fetchImpl('https://api.openai.com/v1/responses', {
      method: 'POST',
      headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
      body: JSON.stringify({ model: effectiveModel, input, max_output_tokens: maxOutputTokens, store: false })
    });
    const payload = await apiResponse.json();
    if (!apiResponse.ok) throw new Error(payload.error?.message || payload.error || `OpenAI API HTTP ${apiResponse.status}`);
    const usage = payload.usage || {};
    const inputTokens = Number(usage.input_tokens || 0);
    const outputTokens = Number(usage.output_tokens || 0);
    const cachedInputTokens = Number(usage.input_tokens_details?.cached_tokens || 0);
    const ledger = readLedger(options);
    const row = ledger.models[effectiveModel] || { requests: 0, inputTokens: 0, cachedInputTokens: 0, outputTokens: 0, projects: {} };
    row.requests += 1;
    row.inputTokens += inputTokens;
    row.cachedInputTokens += cachedInputTokens;
    row.outputTokens += outputTokens;
    row.projects ||= {};
    const projectRow = row.projects[project.id] || { label: project.label, requests: 0, inputTokens: 0, cachedInputTokens: 0, outputTokens: 0 };
    projectRow.label = project.label;
    projectRow.requests += 1;
    projectRow.inputTokens += inputTokens;
    projectRow.cachedInputTokens += cachedInputTokens;
    projectRow.outputTokens += outputTokens;
    row.projects[project.id] = projectRow;
    ledger.models[effectiveModel] = row;
    ledger.updatedAt = new Date(options.now || Date.now()).toISOString();
    writeLedger(ledger, options);
    return { ok: true, id: payload.id, requestedModel, model: payload.model || effectiveModel, effectiveModel, selectionSource, serviceTier: payload.service_tier || null, project, text: responseText(payload), usage: { inputTokens, cachedInputTokens, outputTokens, totalTokens: inputTokens + outputTokens }, guard: openaiUsageStatus(options) };
  }, options);
}

export async function probeOpenaiModel(modelInput, options = {}) {
  const definition = modelDefinition(modelInput);
  try {
    const result = await guardedOpenaiResponse({
      model: definition.id,
      input: 'Reply with only: OK',
      maxOutputTokens: 16,
      project: { id: 'aicc-model-probe', label: 'AICC 모델 확인' },
      selectionSource: 'user'
    }, { ...options, probe: true });
    recordModelProbe(definition.id, { status: 'available', responseModel: result.model, serviceTier: result.serviceTier }, options);
    return { ok: true, model: definition.id, status: 'available', usage: result.usage, responseModel: result.model, serviceTier: result.serviceTier };
  } catch (error) {
    const message = String(error.message || error).replace(/sk-[A-Za-z0-9_-]+/g, '<redacted>').slice(0, 500);
    recordModelProbe(definition.id, { status: 'unavailable', reason: message }, options);
    return { ok: false, model: definition.id, status: 'unavailable', reason: message };
  }
}

export const openaiComplimentaryConfig = { groups: GROUPS, models: MODELS, defaultModel: DEFAULT_MODEL, defaultProjectLimitPercent: DEFAULT_PROJECT_LIMIT_PERCENT, catalogAsOf: CATALOG_AS_OF };
