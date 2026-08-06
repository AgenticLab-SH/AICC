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
  const [version, health] = await Promise.all([
    runner(versionSpec.executable, versionSpec.args, { timeoutMs: options.timeoutMs ?? 5_000 }),
    runner(healthSpec.executable, healthSpec.args, { timeoutMs: options.timeoutMs ?? 5_000 })
  ]);

  let healthPayload = null;
  if (health.ok) {
    try { healthPayload = sanitize(JSON.parse(health.stdout)); } catch { healthPayload = null; }
  }
  const installed = version.ok;
  const healthy = Boolean(healthPayload?.ok);

  return {
    id: 'ocx',
    label: 'OCX 모델 연결',
    state: !installed ? 'unavailable' : healthy ? 'ready' : 'offline',
    detail: !installed ? 'OCX를 찾지 못했습니다.' : healthy ? 'OCX가 실행 중입니다.' : 'OCX는 설치됐지만 실행 중이 아닙니다.',
    installed,
    healthy,
    version: installed ? version.stdout.trim().replace(/^opencodex\s+/i, '') : null,
    runtime: healthPayload,
    source: versionSpec.executable
  };
}
