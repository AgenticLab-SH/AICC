#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
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

async function health(port) {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/healthz`, {
      signal: AbortSignal.timeout(2_000), cache: 'no-store',
    });
    if (!response.ok) return null;
    return await response.json();
  } catch { return null; }
}

async function admin(port, token, action) {
  const response = await fetch(`http://127.0.0.1:${port}/admin/${action}`, {
    method: 'POST',
    headers: { authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) throw new Error(`admin ${action} returned HTTP ${response.status}`);
  return response.json();
}

async function wait(ms) { await new Promise(resolve => setTimeout(resolve, ms)); }

function loopbackHttpEndpoint(value) {
  const endpoint = new URL(value);
  if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1') {
    throw new Error('launcher browser endpoint is not loopback HTTP');
  }
  return endpoint;
}

async function launcherPage(descriptor) {
  const endpoint = loopbackHttpEndpoint(descriptor.endpoint);
  const response = await fetch(new URL('/json/list', endpoint), {
    signal: AbortSignal.timeout(5_000), cache: 'no-store',
  });
  if (!response.ok) throw new Error(`launcher CDP discovery returned HTTP ${response.status}`);
  const targets = await response.json();
  const page = targets.find(target => target.type === 'page'
    && typeof target.url === 'string'
    && target.url.includes('/Codex%20Web%20GPT.app/Contents/Resources/'));
  if (!page?.webSocketDebuggerUrl?.startsWith('ws://127.0.0.1:')) {
    throw new Error('launcher renderer target is unavailable');
  }
  return page;
}

async function evaluate(page, expression, timeoutMs = 240_000) {
  return await new Promise((resolve, reject) => {
    const socket = new WebSocket(page.webSocketDebuggerUrl);
    const timer = setTimeout(() => {
      socket.close();
      reject(new Error(`launcher IPC evaluation timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    const finish = (callback, value) => {
      clearTimeout(timer);
      try { socket.close(); } catch {}
      callback(value);
    };
    socket.addEventListener('error', () => finish(reject, new Error('launcher CDP connection failed')));
    socket.addEventListener('open', () => {
      socket.send(JSON.stringify({
        id: 1,
        method: 'Runtime.evaluate',
        params: { expression, awaitPromise: true, returnByValue: true, userGesture: false },
      }));
    });
    socket.addEventListener('message', async event => {
      let message;
      try {
        const data = event.data;
        const raw = typeof data === 'string'
          ? data
          : typeof data?.text === 'function'
            ? await data.text()
            : Buffer.from(data).toString('utf8');
        message = JSON.parse(raw);
      } catch { return; }
      if (message.id !== 1) return;
      if (message.error) {
        finish(reject, new Error(message.error.message || 'launcher CDP evaluation failed'));
        return;
      }
      if (message.result?.exceptionDetails) {
        const exception = message.result.exceptionDetails.exception?.description
          || message.result.exceptionDetails.text
          || 'launcher IPC invocation failed';
        finish(reject, new Error(redact(exception)));
        return;
      }
      finish(resolve, message.result?.result?.value);
    });
  });
}

async function waitForIdleAndDrain(port, controlToken, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const current = await health(port);
    if (!current) {
      await wait(2_000);
      continue;
    }
    const drained = await admin(port, controlToken, 'drain');
    if (drained.active_http_turns === 0 && drained.active_browser_turns === 0) return current;
    await admin(port, controlToken, 'resume');
    await wait(2_000);
  }
  throw new Error('bridge did not become atomically idle before timeout');
}

async function waitForFull(port, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await health(port);
    if (last?.status === 'ok' && last.mode === 'full' && last.accepting_turns === true) return last;
    await wait(1_000);
  }
  throw new Error(`Responses proxy did not become ready in full mode: ${redact(JSON.stringify(last))}`);
}

async function tunnelStatusFromHealth(urlFile, timeoutMs = 3_000) {
  try {
    const endpoint = loopbackHttpEndpoint(fs.readFileSync(urlFile, 'utf8').trim());
    const response = await fetch(new URL('/healthz', endpoint), {
      headers: { accept: 'text/plain' },
      signal: AbortSignal.timeout(timeoutMs),
      cache: 'no-store',
    });
    const ready = response.ok && (await response.text()).trim() === 'live';
    return { runtime: { processRunning: ready, healthy: ready, ready, state: ready ? 'ready' : 'starting' } };
  } catch {
    return { runtime: { processRunning: false, healthy: false, ready: false, state: 'stopped' } };
  }
}

async function main() {
  const cli = required('--cli');
  const tunnelId = option('--tunnel-id');
  const runtimeKeyFile = required('--runtime-key-file');
  const browserDescriptorFile = required('--browser-host-descriptor');
  const configFile = required('--config');
  const backupConfig = required('--backup-config');
  const resultFile = required('--result-file');
  const timeoutMs = Number(option('--timeout-ms', '900000'));
  const appName = option('--app-name', 'Web GPT 작업 하네스')?.trim();
  if (!/^tunnel_[a-f0-9]{32}$/.test(tunnelId ?? '')) throw new Error('invalid --tunnel-id');
  if (!appName || appName.length > 80) throw new Error('invalid --app-name');
  for (const file of [cli, runtimeKeyFile, browserDescriptorFile, configFile, backupConfig]) {
    if (!fs.existsSync(file)) throw new Error(`required file is missing: ${file}`);
  }
  const initial = JSON.parse(fs.readFileSync(configFile, 'utf8'));
  const port = Number(initial.port || 17841);
  if (initial.host !== '127.0.0.1' || !Number.isInteger(port)) {
    throw new Error('existing bridge config is not loopback');
  }
  const descriptor = JSON.parse(fs.readFileSync(browserDescriptorFile, 'utf8'));
  if (!Number.isInteger(descriptor.pid) || descriptor.pid < 1) {
    throw new Error('launcher browser descriptor is invalid');
  }
  const runtimeKey = fs.readFileSync(runtimeKeyFile, 'utf8').trim();
  if (runtimeKey.length < 20 || runtimeKey.length > 64 * 1024) {
    throw new Error('runtime key file is empty or unexpectedly large');
  }

  let appNameChanged = false;
  let page = null;
  try {
    const observed = await health(port);
    const requiresMutation = observed?.mode !== 'full' || initial.appName !== appName;
    const current = requiresMutation
      ? await waitForIdleAndDrain(port, initial.controlToken, timeoutMs)
      : observed;
    if (!current) throw new Error('bridge health is unavailable');
    if (initial.appName !== appName) {
      atomicJson(configFile, { ...initial, appName });
      appNameChanged = true;
    }
    if (current.mode !== 'full') {
      page = await launcherPage(descriptor);
      const input = JSON.stringify({ tunnelId, runtimeKey, replace: true });
      const expression = `window.codexWebLauncher.setupMcp(${input})`;
      await evaluate(page, expression, 300_000);
    } else if (appNameChanged) {
      page = await launcherPage(descriptor);
      await evaluate(page, 'window.codexWebLauncher.setupMcp({ replace: false })', 300_000);
    } else {
      await admin(port, initial.controlToken, 'resume');
    }

    const bridge = await waitForFull(port);
    const healthUrlFile = path.join(
      os.homedir(),
      'Library',
      'Application Support',
      'tunnel-client',
      'health',
      `${JSON.parse(fs.readFileSync(configFile, 'utf8')).tunnel?.alias ?? 'codex-chatgpt-web'}.url`,
    );
    const deadline = Date.now() + 180_000;
    let doctor = null;
    let tunnel = null;
    while (Date.now() < deadline) {
      tunnel = await tunnelStatusFromHealth(healthUrlFile);
      doctor = {
        ok: bridge.status === 'ok' && tunnel.runtime.ready === true,
        checks: [
          { id: 'proxy', status: bridge.status === 'ok' ? 'ok' : 'error' },
          { id: 'tunnel-runtime', status: tunnel.runtime.ready === true ? 'ok' : 'error' },
        ],
      };
      if (doctor.ok === true) break;
      await wait(2_000);
    }
    const ocx = await fetch('http://127.0.0.1:10100/healthz', {
      signal: AbortSignal.timeout(3_000), cache: 'no-store',
    }).then(response => response.ok ? response.json() : null).catch(() => null);
    const outcome = {
      ok: doctor?.ok === true && tunnel?.runtime?.ready === true && bridge.mode === 'full',
      completedAt: new Date().toISOString(),
      bridge: { mode: bridge.mode, healthy: bridge.status === 'ok', acceptingTurns: bridge.accepting_turns === true },
      connectorName: appName,
      harnessTunnel: {
        running: tunnel?.runtime?.processRunning === true,
        healthy: tunnel?.runtime?.healthy === true,
        ready: tunnel?.runtime?.ready === true,
      },
      doctor: {
        ok: doctor?.ok === true,
        checks: doctor?.checks?.map(check => ({ id: check.id, status: check.status })) ?? [],
      },
      ocx: { healthy: ocx?.ok === true || ocx?.status === 'ok' },
    };
    atomicJson(resultFile, outcome);
    if (!outcome.ok) throw new Error('post-cutover validation did not become ready');
    process.stdout.write('Web GPT full harness cutover completed.\n');
  } catch (error) {
    if (appNameChanged) {
      atomicJson(configFile, initial);
      try {
        page ??= await launcherPage(descriptor);
        await evaluate(page, 'window.codexWebLauncher.setupMcp({ replace: false })', 300_000);
      } catch {}
    }
    const current = await health(port);
    if (current?.mode === initial.mode && current.accepting_turns === false) {
      await admin(port, initial.controlToken, 'resume').catch(() => {});
    }
    atomicJson(resultFile, {
      ok: false,
      failedAt: new Date().toISOString(),
      error: redact(error),
      launcherTransactionalRollback: true,
    });
    throw error;
  }
}

main().catch(error => {
  process.stderr.write(`Web GPT full harness cutover failed: ${redact(error?.message || error)}\n`);
  process.exitCode = 1;
});
