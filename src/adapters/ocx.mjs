import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { envCommand, runCommand } from '../lib/command.mjs';
import { sanitize } from '../lib/redact.mjs';

function executableCandidates(explicit) {
  if (explicit) return [explicit];
  const pathEntries = String(process.env.PATH ?? '').split(path.delimiter).filter(Boolean);
  return [...new Set([
    process.env.AICC_OCX_EXECUTABLE?.trim(),
    ...pathEntries.map(entry => path.join(entry, 'ocx')),
    path.join(os.homedir(), '.local', 'bin', 'ocx'),
    '/opt/homebrew/bin/ocx',
    '/usr/local/bin/ocx',
    'ocx'
  ].filter(Boolean))];
}

function firstInstalled(candidates) {
  return candidates.find(candidate => candidate === 'ocx' || (() => {
    try { fs.accessSync(candidate, fs.constants.X_OK); return true; } catch { return false; }
  })()) ?? candidates.at(-1) ?? 'ocx';
}

function parseJson(result) {
  if (!result?.ok) return null;
  try { return sanitize(JSON.parse(result.stdout)); } catch { return null; }
}

function command(executable, args) {
  return { executable, args };
}

async function mapWithConcurrency(items, limit, operation) {
  const results = new Array(items.length);
  let cursor = 0;
  async function worker() {
    while (cursor < items.length) {
      const index = cursor++;
      try { results[index] = await operation(items[index], index); }
      catch { results[index] = null; }
    }
  }
  const workerCount = Math.max(1, Math.min(items.length, Number(limit) || 1));
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return results;
}

function moduleState(payload, result) {
  if (payload) return 'ready';
  if (result?.timedOut) return 'timeout';
  return 'unavailable';
}

function groupedModels(models) {
  const counts = new Map();
  for (const model of models) counts.set(model.provider ?? 'unknown', (counts.get(model.provider ?? 'unknown') ?? 0) + 1);
  return [...counts].map(([provider, count]) => ({ provider, count }));
}

export async function ocxStatus(options = {}) {
  const executable = firstInstalled(executableCandidates(options.executable));
  const versionSpec = options.versionCommand ?? envCommand('AICC_OCX_VERSION', {
    executable,
    args: ['--version']
  });
  const healthSpec = options.healthCommand ?? envCommand('AICC_OCX_HEALTH', {
    executable,
    args: ['health', '--json']
  });
  const runner = options.runCommand ?? runCommand;
  const readOnlySpecs = options.readOnlyCommands ?? {
    providers: command(executable, ['provider', 'list', '--json']),
    models: command(executable, ['models', 'list', '--json']),
    agents: command(executable, ['agent', 'status', '--json']),
    system: command(executable, ['system', 'status', '--json']),
    usage: command(executable, ['observe', 'usage', '--json']),
    combos: command(executable, ['combo', 'list', '--json']),
    storage: command(executable, ['observe', 'storage', '--json']),
    diagnostics: command(executable, ['system', 'diagnostics', '--json']),
    endpoints: command(executable, ['access', 'endpoints', '--json'])
  };
  const [version, health] = await Promise.all([
    runner(versionSpec.executable, versionSpec.args, { timeoutMs: options.timeoutMs ?? 5_000 }),
    runner(healthSpec.executable, healthSpec.args, { timeoutMs: options.timeoutMs ?? 5_000 })
  ]);
  const readOnlyResults = await mapWithConcurrency(
    Object.values(readOnlySpecs),
    options.readOnlyConcurrency ?? 3,
    spec => Promise.resolve(runner(spec.executable, spec.args, {
      timeoutMs: options.readOnlyTimeoutMs ?? 8_000
    }))
  );

  let healthPayload = null;
  if (health.ok) {
    try { healthPayload = sanitize(JSON.parse(health.stdout)); } catch { healthPayload = null; }
  }
  const installed = version.ok;
  const healthy = Boolean(healthPayload?.ok);
  const readOnly = Object.fromEntries(Object.keys(readOnlySpecs).map((key, index) => [key, parseJson(readOnlyResults[index])]));
  const providers = readOnly.providers?.configured ?? [];
  const models = readOnly.models?.models ?? [];
  const startup = readOnly.system?.startup ?? readOnly.system?.settings?.startupHealth ?? null;
  const memory = readOnly.system?.memory ?? null;
  const usage = readOnly.usage?.summary ?? null;
  const agent = readOnly.agents ?? null;
  const storage = readOnly.storage ?? null;
  const diagnostics = readOnly.diagnostics ?? null;
  const endpoints = readOnly.endpoints ?? null;
  const sectionState = key => moduleState(readOnly[key], readOnlyResults[Object.keys(readOnlySpecs).indexOf(key)]);
  const providerSummaries = providers.map(provider => ({
    name: provider.name ?? null,
    adapter: provider.adapter ?? null,
    authMode: provider.authMode ?? null,
    isDefault: provider.isDefault === true,
    modelCount: Array.isArray(provider.models) ? provider.models.length : 0
  }));
  const chosenSubagents = agent?.subagents?.chosen ?? [];
  const fallbackModels = agent?.fallback?.models ?? [];
  const storageBuckets = (storage?.buckets ?? []).map(bucket => ({
    key: bucket.key ?? null,
    label: bucket.label ?? null,
    bytes: Number.isFinite(bucket.bytes) ? bucket.bytes : null,
    fileCount: Number.isFinite(bucket.fileCount) ? bucket.fileCount : null,
    rows: Number.isFinite(bucket.rows) ? bucket.rows : null
  }));
  const endpointCount = endpoints ? ['responsesEndpoint', 'chatCompletionsEndpoint', 'messagesEndpoint', 'modelsEndpoint'].filter(key => endpoints[key]).length : null;

  return {
    id: 'ocx',
    label: 'OCX 모델 연결',
    state: !installed ? 'unavailable' : healthy ? 'ready' : 'offline',
    detail: !installed ? 'OCX를 찾지 못했습니다.' : healthy ? 'OCX가 실행 중입니다.' : 'OCX는 설치됐지만 실행 중이 아닙니다.',
    installed,
    healthy,
    version: installed ? version.stdout.trim().replace(/^opencodex\s+/i, '') : null,
    runtime: healthPayload,
    dashboardUrl: 'http://127.0.0.1:10100/#dashboard',
    overview: {
      providerCount: providers.length,
      providerNames: providers.map(provider => provider.name).filter(Boolean),
      defaultProvider: providers.find(provider => provider.isDefault)?.name ?? null,
      modelCount: models.length,
      comboCount: readOnly.combos?.combos?.length ?? null,
      multiAgentMode: agent?.v2?.multiAgentMode ?? null,
      subagentCount: agent?.subagents?.chosen?.length ?? null,
      startupStatus: startup?.status ?? null,
      rebootSafe: startup?.rebootSafe ?? null,
      serviceRunning: startup?.serviceRunning ?? null,
      uptimeSeconds: memory?.uptimeSeconds ?? null,
      rssBytes: memory?.rss ?? null,
      memoryBudgetBytes: memory?.appOwnedBytes?.budgetBytes ?? null,
      memoryRetainedBytes: memory?.appOwnedBytes?.retainedBytes ?? null,
      activeTranslatorBuffers: memory?.appOwnedBytes?.observedInFlight?.translator_buffers?.active ?? null,
      requests30d: usage?.requests ?? null,
      totalTokens30d: usage?.totalTokens ?? null,
      usageCoverageRatio: usage?.coverageRatio ?? null
    },
    sections: {
      providers: {
        state: sectionState('providers'),
        count: providers.length,
        registryCount: readOnly.providers?.registryCount ?? null,
        defaultProvider: providers.find(provider => provider.isDefault)?.name ?? null,
        items: providerSummaries
      },
      models: {
        state: sectionState('models'),
        count: models.length,
        byProvider: groupedModels(models),
        defaultModels: models.filter(model => model.isDefault).map(model => ({ provider: model.provider, model: model.model }))
      },
      agents: {
        state: sectionState('agents'),
        v2Enabled: agent?.v2?.enabled === true,
        multiAgentMode: agent?.v2?.multiAgentMode ?? null,
        chosenCount: chosenSubagents.length,
        chosen: chosenSubagents,
        fallbackCount: fallbackModels.length,
        sidecars: agent?.sidecars ?? null
      },
      usage: {
        state: sectionState('usage'),
        range: readOnly.usage?.range ?? '30d',
        requests: usage?.requests ?? null,
        totalTokens: usage?.totalTokens ?? null,
        coverageRatio: usage?.coverageRatio ?? null,
        estimatedCostUsd: usage?.estimatedCostUsd ?? null,
        measuredRequests: usage?.measuredRequests ?? null,
        unmeteredRequests: usage?.unmeteredRequests ?? null
      },
      runtime: {
        state: sectionState('system'),
        startupStatus: startup?.status ?? null,
        rebootSafe: startup?.rebootSafe ?? null,
        serviceRunning: startup?.serviceRunning ?? null,
        routingInjected: startup?.routingInjected ?? null,
        diagnosticStale: startup?.diagnosticStale ?? null,
        uptimeSeconds: memory?.uptimeSeconds ?? null,
        rssBytes: memory?.rss ?? null,
        memoryBudgetBytes: memory?.appOwnedBytes?.budgetBytes ?? null,
        retainedBytes: memory?.appOwnedBytes?.retainedBytes ?? null,
        overBudgetBytes: memory?.appOwnedBytes?.overBudgetBytes ?? null,
        activeTurns: memory?.activeTurnCount ?? null,
        draining: memory?.isDraining ?? null
      },
      storage: {
        state: sectionState('storage'),
        totalBytes: storage?.total?.bytes ?? null,
        fileCount: storage?.total?.fileCount ?? null,
        buckets: storageBuckets
      },
      diagnostics: {
        state: sectionState('diagnostics'),
        warningCount: Array.isArray(diagnostics?.warnings) ? diagnostics.warnings.length : null,
        groupCount: Array.isArray(diagnostics?.grouped) ? diagnostics.grouped.length : null
      },
      endpoints: {
        state: sectionState('endpoints'),
        baseUrl: endpoints?.baseUrl ?? null,
        endpointCount
      },
      combos: {
        state: sectionState('combos'),
        count: readOnly.combos?.combos?.length ?? null
      }
    },
    source: versionSpec.executable
  };
}
