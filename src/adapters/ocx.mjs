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
    combos: command(executable, ['combo', 'list', '--json'])
  };
  const [version, health, ...readOnlyResults] = await Promise.all([
    runner(versionSpec.executable, versionSpec.args, { timeoutMs: options.timeoutMs ?? 5_000 }),
    runner(healthSpec.executable, healthSpec.args, { timeoutMs: options.timeoutMs ?? 5_000 }),
    ...Object.values(readOnlySpecs).map(spec => Promise.resolve(runner(spec.executable, spec.args, {
      timeoutMs: options.readOnlyTimeoutMs ?? 8_000
    })).catch(() => null))
  ]);

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
    source: versionSpec.executable
  };
}
