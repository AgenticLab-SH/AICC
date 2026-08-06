#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

function option(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

function required(name) {
  const value = option(name);
  if (!value) throw new Error(`${name} is required`);
  return path.resolve(value);
}

function redact(value) {
  return String(value ?? '')
    .replace(/tunnel_[a-f0-9]{32}/g, '[tunnel-id]')
    .replace(/sk-[A-Za-z0-9_-]{12,}/g, '[redacted-key]')
    .slice(0, 4_000);
}

function atomicJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, file);
  fs.chmodSync(file, 0o600);
}

function run(executable, args, timeout = 180_000) {
  const result = spawnSync(executable, args, { encoding: 'utf8', timeout, windowsHide: true, maxBuffer: 4 * 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(redact(result.stderr || result.stdout || `exit ${result.status}`));
  return result.stdout;
}

async function health(port) {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/healthz`, { signal: AbortSignal.timeout(2_000), cache: 'no-store' });
    if (!response.ok) return null;
    return await response.json();
  } catch { return null; }
}

async function admin(port, token, action) {
  const response = await fetch(`http://127.0.0.1:${port}/admin/${action}`, {
    method: 'POST', headers: { authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(5_000)
  });
  if (!response.ok) throw new Error(`admin ${action} returned HTTP ${response.status}`);
  return response.json();
}

async function wait(ms) { await new Promise(resolve => setTimeout(resolve, ms)); }

async function waitForMode(port, mode, oldPid, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await health(port);
    if (last?.status === 'ok' && last.mode === mode && last.accepting_turns === true && last.pid !== oldPid) return last;
    await wait(500);
  }
  throw new Error(`Responses proxy did not restart in ${mode} mode: ${redact(JSON.stringify(last))}`);
}

async function main() {
  const cli = required('--cli');
  const tunnelId = option('--tunnel-id');
  const runtimeKeyFile = required('--runtime-key-file');
  const browserDescriptor = required('--browser-host-descriptor');
  const configFile = required('--config');
  const backupConfig = required('--backup-config');
  const resultFile = required('--result-file');
  const timeoutMs = Number(option('--timeout-ms', '900000'));
  if (!/^tunnel_[a-f0-9]{32}$/.test(tunnelId ?? '')) throw new Error('invalid --tunnel-id');
  for (const file of [cli, runtimeKeyFile, browserDescriptor, configFile, backupConfig]) {
    if (!fs.existsSync(file)) throw new Error(`required file is missing: ${file}`);
  }
  const initial = JSON.parse(fs.readFileSync(configFile, 'utf8'));
  const port = Number(initial.port || 17841);
  if (initial.host !== '127.0.0.1' || !Number.isInteger(port)) throw new Error('existing bridge config is not loopback');
  const deadline = Date.now() + timeoutMs;
  let drained = false;
  let originalPid = null;
  try {
    while (Date.now() < deadline) {
      const current = await health(port);
      if (!current) { await wait(2_000); continue; }
      if (current.mode === 'full' && current.accepting_turns === true) {
        originalPid = current.pid;
        break;
      }
      const result = await admin(port, initial.controlToken, 'drain');
      if (result.active_http_turns === 0 && result.active_browser_turns === 0) {
        drained = true;
        originalPid = current.pid;
        break;
      }
      await admin(port, initial.controlToken, 'resume');
      await wait(2_000);
    }
    if (!originalPid) throw new Error('bridge did not become atomically idle before timeout');

    let current = await health(port);
    if (current?.mode !== 'full') {
      run(cli, [
        'setup', '--full', '--tunnel-id', tunnelId, '--runtime-key-file', runtimeKeyFile,
        '--browser-host-descriptor', browserDescriptor, '--app-name', 'Codex Native',
        '--preserve-codex-route', '--restart-service', '--acknowledge-unofficial'
      ]);
      process.kill(originalPid, 'SIGTERM');
      current = await waitForMode(port, 'full', originalPid);
    } else if (drained) {
      await admin(port, initial.controlToken, 'resume');
    }

    const doctor = JSON.parse(run(cli, ['doctor', '--json'], 90_000));
    const tunnel = JSON.parse(run(cli, ['tunnel', 'status'], 30_000));
    const ocx = await fetch('http://127.0.0.1:10100/healthz', { signal: AbortSignal.timeout(3_000) })
      .then(response => response.ok ? response.json() : null).catch(() => null);
    const outcome = {
      ok: doctor.ok === true && tunnel?.runtime?.ready === true && current?.mode === 'full',
      completedAt: new Date().toISOString(),
      bridge: { mode: current?.mode, healthy: current?.status === 'ok', acceptingTurns: current?.accepting_turns === true },
      harnessTunnel: {
        running: tunnel?.runtime?.processRunning === true,
        healthy: tunnel?.runtime?.healthy === true,
        ready: tunnel?.runtime?.ready === true
      },
      doctor: { ok: doctor.ok === true, checks: doctor.checks?.map(check => ({ id: check.id, status: check.status })) ?? [] },
      ocx: { healthy: ocx?.ok === true || ocx?.status === 'ok' }
    };
    atomicJson(resultFile, outcome);
    if (!outcome.ok) throw new Error('post-cutover validation did not become ready');
    process.stdout.write('Web GPT full harness cutover completed.\n');
  } catch (error) {
    try {
      const currentConfig = JSON.parse(fs.readFileSync(configFile, 'utf8'));
      if (currentConfig.mode === 'full') {
        try { run(cli, ['tunnel', 'stop'], 30_000); } catch {}
      }
      fs.copyFileSync(backupConfig, configFile);
      fs.chmodSync(configFile, 0o600);
      const current = await health(port);
      if (current?.pid) process.kill(current.pid, 'SIGTERM');
      if (current?.pid) await waitForMode(port, initial.mode, current.pid, 60_000);
      else if (drained) await admin(port, initial.controlToken, 'resume').catch(() => {});
    } catch (rollbackError) {
      atomicJson(resultFile, { ok: false, failedAt: new Date().toISOString(), error: redact(error), rollbackError: redact(rollbackError) });
      throw new Error(`${redact(error)}; rollback failed: ${redact(rollbackError)}`);
    }
    atomicJson(resultFile, { ok: false, failedAt: new Date().toISOString(), error: redact(error), rolledBack: true });
    throw error;
  }
}

main().catch(error => {
  process.stderr.write(`Web GPT full harness cutover failed: ${redact(error?.message || error)}\n`);
  process.exitCode = 1;
});
