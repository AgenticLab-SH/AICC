import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_RPC_BYTES = 8 * 1024 * 1024;

function executableCandidates(config = {}) {
  return [
    config.nativeGateways?.codex?.executable,
    process.env.CODEX_BIN,
    path.join(os.homedir(), '.codex', 'packages', 'standalone', 'current', 'codex'),
    process.platform === 'darwin' ? '/Applications/ChatGPT.app/Contents/Resources/codex' : null
  ].filter(Boolean);
}

export function resolveCodexExecutable(config = {}) {
  for (const candidate of executableCandidates(config)) {
    const resolved = path.resolve(String(candidate));
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) return resolved;
  }
  const located = spawnSync(process.platform === 'win32' ? 'where' : 'which', ['codex'], {
    encoding: 'utf8', timeout: 3_000
  });
  const first = located.status === 0 ? located.stdout.split(/\r?\n/).find(Boolean) : null;
  if (first && fs.existsSync(first)) return fs.realpathSync(first);
  throw new Error('Codex app-server 실행 파일을 찾지 못했습니다. CODEX_BIN 또는 AICC 설정을 확인하세요.');
}

function rpcError(message, method) {
  const detail = message?.error?.message ?? message?.error?.code ?? '알 수 없는 RPC 오류';
  return new Error(`Codex app-server ${method} 실패: ${detail}`);
}

export async function callCodexAppServer(config, method, params, options = {}) {
  const executable = options.executable ?? resolveCodexExecutable(config);
  const timeoutMs = Number(options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const child = spawn(executable, ['app-server', '--stdio'], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: process.env
  });
  let buffer = '';
  let stderr = '';
  let settled = false;
  let timer;
  const pending = new Map();
  let nextId = 1;

  const stop = () => {
    if (timer) clearTimeout(timer);
    if (child.stdin && !child.stdin.destroyed) child.stdin.end();
    if (!child.killed) child.kill('SIGTERM');
  };
  const send = payload => {
    if (!child.stdin || child.stdin.destroyed) throw new Error('Codex app-server proxy 입력이 닫혔습니다.');
    child.stdin.write(`${JSON.stringify(payload)}\n`);
  };
  const request = (requestMethod, requestParams) => new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject, method: requestMethod });
    send({ id, method: requestMethod, params: requestParams ?? null });
  });

  child.stderr.on('data', chunk => {
    stderr += chunk.toString('utf8');
    if (stderr.length > 16_384) stderr = stderr.slice(-16_384);
  });
  child.stdout.on('data', chunk => {
    buffer += chunk.toString('utf8');
    if (Buffer.byteLength(buffer) > MAX_RPC_BYTES) {
      for (const entry of pending.values()) entry.reject(new Error('Codex app-server 응답이 안전 제한보다 큽니다.'));
      pending.clear();
      stop();
      return;
    }
    let newline;
    while ((newline = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      let message;
      try { message = JSON.parse(line); } catch { continue; }
      if (message.id !== undefined && pending.has(message.id)) {
        const entry = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) entry.reject(rpcError(message, entry.method));
        else entry.resolve(message.result);
      } else if (message.id !== undefined && message.method) {
        // The remote AICC gateway cannot approve host UI, auth, or dynamic tool requests.
        send({ id: message.id, error: { code: -32001, message: 'AICC remote task gateway does not provide interactive host approval.' } });
      }
    }
  });

  try {
    const operation = (async () => {
      await request('initialize', {
        clientInfo: { name: 'aicc-workspace', version: '1.1.0' },
        capabilities: { experimentalApi: true }
      });
      send({ method: 'initialized', params: {} });
      return request(method, params);
    })();
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Codex app-server ${method} 응답 시간이 초과되었습니다.`)), timeoutMs);
    });
    const result = await Promise.race([operation, timeout]);
    settled = true;
    return result;
  } catch (error) {
    if (!settled && child.exitCode !== null && stderr.trim()) {
      throw new Error(`Codex app-server proxy가 종료되었습니다: ${stderr.trim().split(/\r?\n/).at(-1)}`);
    }
    throw error;
  } finally {
    stop();
  }
}

function codexJobLog(runtimeRoot) {
  const jobsRoot = path.join(runtimeRoot, 'codex-jobs');
  fs.mkdirSync(jobsRoot, { recursive: true, mode: 0o700 });
  return path.join(jobsRoot, `job-${Date.now()}-${process.pid}-${Math.random().toString(16).slice(2)}.jsonl`);
}

async function waitForThreadId(logFile, child, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let text = '';
    try { text = fs.readFileSync(logFile, 'utf8'); } catch { /* output may not exist yet */ }
    for (const line of text.split(/\r?\n/)) {
      try {
        const event = JSON.parse(line);
        const id = event.thread_id ?? event.threadId ?? event.thread?.id;
        if (event.type === 'thread.started' && id) return id;
      } catch { /* partial line */ }
    }
    if (child.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  return null;
}

export async function startCodexExec(config, options) {
  const executable = options.executable ?? resolveCodexExecutable(config);
  const logFile = codexJobLog(options.runtimeRoot);
  const output = fs.openSync(logFile, 'a', 0o600);
  const args = options.taskId
    ? ['exec', 'resume', options.taskId, '--json', '--color', 'never', '-c', 'approval_policy="never"', '-c', 'sandbox_mode="workspace-write"', '-c', `model_reasoning_effort="${options.reasoningEffort ?? 'high'}"`, options.prompt]
    : ['exec', '--json', '--color', 'never', '-s', 'workspace-write', '-C', options.workspaceRoot, '-c', 'approval_policy="never"', '-c', `model_reasoning_effort="${options.reasoningEffort ?? 'high'}"`, options.prompt];
  const child = spawn(executable, args, {
    cwd: options.workspaceRoot,
    env: process.env,
    detached: true,
    stdio: ['ignore', output, output]
  });
  fs.closeSync(output);
  child.unref();
  const taskId = options.taskId ?? await waitForThreadId(logFile, child, options.startTimeoutMs ?? 12_000);
  if (!taskId) {
    throw new Error(`Codex 작업이 시작 ID를 반환하지 않았습니다. 로컬 로그를 확인하세요: ${path.basename(logFile)}`);
  }
  return { taskId, pid: child.pid, logFile };
}

function textFromContent(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content.map(item => typeof item === 'string' ? item : item?.text ?? '').filter(Boolean).join('\n');
}

function truncate(text, max = 24_000) {
  const value = String(text ?? '');
  return value.length <= max ? value : `${value.slice(0, max)}\n…[truncated]`;
}

export function publicThread(thread, options = {}) {
  const includeTurns = options.includeTurns === true;
  const summary = {
    id: thread.id,
    name: thread.name ?? null,
    preview: truncate(thread.preview, 1_000),
    status: thread.status?.type ?? thread.status ?? 'unknown',
    model_provider: thread.modelProvider ?? null,
    created_at: thread.createdAt ?? null,
    updated_at: thread.updatedAt ?? null,
    parent_thread_id: thread.parentThreadId ?? null,
    source: typeof thread.source === 'string' ? thread.source : thread.source?.type ?? null
  };
  if (!includeTurns) return summary;
  summary.turns = (thread.turns ?? []).slice(-20).map(turn => ({
    id: turn.id,
    status: turn.status,
    started_at: turn.startedAt ?? null,
    completed_at: turn.completedAt ?? null,
    duration_ms: turn.durationMs ?? null,
    error: turn.error?.message ?? turn.error?.code ?? null,
    messages: (turn.items ?? []).flatMap(item => {
      if (item.type === 'userMessage') return [{ role: 'user', text: truncate(textFromContent(item.content)) }];
      if (item.type === 'agentMessage') return [{ role: 'assistant', text: truncate(item.text) }];
      if (item.type === 'plan') return [{ role: 'plan', text: truncate(item.text, 8_000) }];
      if (item.type === 'contextCompaction') return [{ role: 'system', text: '[context compacted]' }];
      return [];
    })
  }));
  return summary;
}
