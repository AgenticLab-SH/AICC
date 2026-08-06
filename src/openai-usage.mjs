import fs from 'node:fs';
import crypto from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const GROUPS = {
  frontier: {
    label: '고성능 모델 풀',
    freeLimit: 250_000,
    hardLimit: 237_500,
    models: ['gpt-5.4', 'gpt-5.2', 'gpt-5.1', 'gpt-5.1-codex', 'gpt-5', 'gpt-5-codex', 'gpt-5-chat-latest', 'gpt-4.1', 'gpt-4o', 'o1', 'o3']
  },
  efficient: {
    label: '경량 모델 풀',
    freeLimit: 2_500_000,
    hardLimit: 2_375_000,
    models: ['gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-5.1-codex-mini', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1-mini', 'gpt-4.1-nano', 'gpt-4o-mini', 'o1-mini', 'o3-mini', 'o4-mini', 'codex-mini-latest']
  }
};

// Standard text pricing per 1M tokens. This is a dated display snapshot, not a billing authority.
const PRICING = {
  'gpt-5.4': { input: 2.50, cachedInput: 0.25, output: 15.00 },
  'gpt-5.4-mini': { input: 0.75, cachedInput: 0.075, output: 4.50 },
  'gpt-5.4-nano': { input: 0.20, cachedInput: 0.02, output: 1.25 },
  'gpt-5-mini': { input: 0.25, cachedInput: 0.025, output: 2.00 },
  'gpt-5-nano': { input: 0.05, cachedInput: 0.005, output: 0.40 },
  'gpt-5-chat-latest': { input: 1.25, cachedInput: 0.125, output: 10.00 },
  'gpt-4.1': { input: 2.00, cachedInput: 0.50, output: 8.00 },
  'gpt-4.1-mini': { input: 0.40, cachedInput: 0.10, output: 1.60 },
  'gpt-4.1-nano': { input: 0.10, cachedInput: 0.025, output: 0.40 },
  'gpt-4o': { input: 2.50, cachedInput: 1.25, output: 10.00 },
  'gpt-4o-mini': { input: 0.15, cachedInput: 0.075, output: 0.60 }
};

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

function atomicJsonWrite(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, file);
  if (process.platform !== 'win32') fs.chmodSync(file, 0o600);
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

function normalizedBaseModel(model) {
  const exact = String(model || '').trim();
  const candidates = Object.values(GROUPS).flatMap(group => group.models).sort((a, b) => b.length - a.length);
  return candidates.find(candidate => exact === candidate || exact.startsWith(`${candidate}-20`)) || exact;
}

export function complimentaryGroupForModel(model) {
  const base = normalizedBaseModel(model);
  for (const [id, group] of Object.entries(GROUPS)) {
    if (group.models.includes(base)) return id;
  }
  return null;
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
  const price = PRICING[normalizedBaseModel(model)];
  if (!price) return null;
  const uncachedInput = Math.max(0, usage.inputTokens - usage.cachedInputTokens);
  return ((uncachedInput * price.input) + (usage.cachedInputTokens * price.cachedInput) + (usage.outputTokens * price.output)) / 1_000_000;
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

export function openaiUsageStatus(options = {}) {
  const ledger = readLedger(options);
  const groups = Object.entries(GROUPS).map(([id, definition]) => {
    const rows = Object.entries(ledger.models)
      .filter(([model]) => complimentaryGroupForModel(model) === id)
      .map(([model, usage]) => ({
        model,
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
    guard: { enabled: true, paidModelsBlocked: true, hardStopPercent: 95 },
    pricing: { asOf: '2026-08-06', currency: 'USD', source: 'https://openai.com/api/pricing/' },
    groups,
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

function reserveCheck(model, input, maxOutputTokens, project, options = {}) {
  const groupId = complimentaryGroupForModel(model);
  if (!groupId) throw new Error(`무료 토큰 대상이 아닌 모델은 AICC guard가 차단합니다: ${model}`);
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
  const model = String(request.model || '').trim();
  const maxOutputTokens = Number(request.maxOutputTokens || 512);
  const input = request.input;
  if (!model) throw new Error('OpenAI model이 필요합니다.');
  if (!Number.isInteger(maxOutputTokens) || maxOutputTokens < 1 || maxOutputTokens > 16_384) throw new Error('maxOutputTokens는 1~16384 정수여야 합니다.');
  if (typeof input !== 'string' || !input.trim()) throw new Error('빈 입력은 보낼 수 없습니다.');
  const project = resolveOpenaiProject({ ...options, project: request.project ?? options.project });
  return { ok: true, model, maxOutputTokens, ...reserveCheck(model, input, maxOutputTokens, project, options) };
}

export async function guardedOpenaiResponse(request, options = {}) {
  const model = String(request.model || '').trim();
  const maxOutputTokens = Number(request.maxOutputTokens || 512);
  if (!model) throw new Error('OpenAI model이 필요합니다.');
  if (!Number.isInteger(maxOutputTokens) || maxOutputTokens < 1 || maxOutputTokens > 16_384) throw new Error('maxOutputTokens는 1~16384 정수여야 합니다.');
  const input = request.input;
  if (typeof input !== 'string' || !input.trim()) throw new Error('빈 입력은 보낼 수 없습니다.');
  const apiKey = keyFromKeychain(options);
  if (!apiKey) throw new Error('macOS Keychain의 OpenAI API / personal-default 키를 찾을 수 없습니다.');
  const project = resolveOpenaiProject({ ...options, project: request.project ?? options.project });

  return withLedgerLock(async () => {
    reserveCheck(model, input, maxOutputTokens, project, options);
    const fetchImpl = options.fetchImpl || fetch;
    const apiResponse = await fetchImpl('https://api.openai.com/v1/responses', {
      method: 'POST',
      headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
      body: JSON.stringify({ model, input, max_output_tokens: maxOutputTokens, store: false })
    });
    const payload = await apiResponse.json();
    if (!apiResponse.ok) throw new Error(payload.error?.message || `OpenAI API HTTP ${apiResponse.status}`);
    const usage = payload.usage || {};
    const inputTokens = Number(usage.input_tokens || 0);
    const outputTokens = Number(usage.output_tokens || 0);
    const cachedInputTokens = Number(usage.input_tokens_details?.cached_tokens || 0);
    const ledger = readLedger(options);
    const row = ledger.models[model] || { requests: 0, inputTokens: 0, cachedInputTokens: 0, outputTokens: 0, projects: {} };
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
    ledger.models[model] = row;
    ledger.updatedAt = new Date(options.now || Date.now()).toISOString();
    writeLedger(ledger, options);
    return { ok: true, id: payload.id, model: payload.model || model, project, text: responseText(payload), usage: { inputTokens, cachedInputTokens, outputTokens, totalTokens: inputTokens + outputTokens }, guard: openaiUsageStatus(options) };
  }, options);
}

export const openaiComplimentaryConfig = { groups: GROUPS, pricing: PRICING, defaultProjectLimitPercent: DEFAULT_PROJECT_LIMIT_PERCENT };
