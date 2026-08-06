import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { cliToolStatus } from './cli-tools.mjs';
import { runCommand } from './lib/command.mjs';
import { redactText, sanitize } from './lib/redact.mjs';
import { setupEnvironment } from './setup.mjs';
import { collectStatus } from './status.mjs';
import { agentsStatus } from './agents.mjs';
import { workspaceMcpStatus } from './workspace-mcp.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const definitions = Object.freeze({
  'status': { title: '전체 상태', run: () => collectStatus() },
  'setup.check': { title: '설치 상태 점검', run: () => setupEnvironment({ checkOnly: true }) },
  'cli.status': { title: 'CLI 연결 점검', run: () => cliToolStatus() },
  'agents.status': { title: 'Codex 하위 에이전트 상태', run: () => agentsStatus() },
  'workspace.status': { title: 'AICC Workspace MCP 상태', run: () => workspaceMcpStatus() },
  'guidance.check': {
    title: '지침과 스킬 점검',
    command: () => ({
      executable: 'pwsh',
      args: ['-NoProfile', '-File', path.join(root, 'tools', 'platform', 'test', 'Test-AiccGuidance.ps1'), '-AiccRoot', root, '-AsJson']
    })
  }
});

function parseOutput(text) {
  const clean = redactText(String(text ?? '').trim());
  if (!clean) return null;
  try { return sanitize(JSON.parse(clean)); } catch { return clean.length > 20_000 ? `${clean.slice(0, 20_000)}\n…` : clean; }
}

export function listTasks() {
  return Object.entries(definitions).map(([id, definition]) => ({ id, title: definition.title }));
}

export async function runTask(id, options = {}) {
  const definition = definitions[id];
  if (!definition) {
    const error = new Error('허용되지 않은 진단 작업입니다.');
    error.code = 'task_not_allowed';
    error.status = 404;
    throw error;
  }
  const startedAt = Date.now();
  if (definition.run) {
    const result = sanitize(await definition.run());
    return { ok: result?.ok !== false, id, title: definition.title, durationMs: Date.now() - startedAt, result };
  }
  const runner = options.runCommand ?? runCommand;
  const command = definition.command();
  const result = await runner(command.executable, command.args, { timeoutMs: 120_000, maxBytes: 512_000 });
  const parsed = parseOutput(result.stdout || result.stderr);
  return {
    ok: result.ok,
    id,
    title: definition.title,
    durationMs: result.durationMs ?? Date.now() - startedAt,
    exitCode: result.exitCode,
    result: parsed
  };
}
