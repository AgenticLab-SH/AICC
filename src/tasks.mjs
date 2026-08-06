import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { cliToolStatus } from './cli-tools.mjs';
import { runCommand } from './lib/command.mjs';
import { redactText, sanitize } from './lib/redact.mjs';
import { setupEnvironment } from './setup.mjs';
import { collectStatus } from './status.mjs';
import { agentsStatus } from './agents.mjs';
import { workspaceMcpStatus } from './workspace-mcp.mjs';
import { workspacePublicationStatus } from './workspace-publish.mjs';
import { codexRouteStatus } from './adapters/codex-routes.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const webGptCli = process.env.AICC_WEB_GPT_CLI?.trim()
  || (process.platform === 'darwin'
    ? '/Applications/Codex Web GPT.app/Contents/Resources/runtime/bin/codex-chatgpt-web'
    : 'codex-chatgpt-web');

function supportComponent(component) {
  if (!component) return null;
  const base = { id: component.id, state: component.state, detail: component.detail };
  if (component.id === 'codex-routes') return { ...base, activeRoute: component.activeRoute, nativeReady: component.nativeReady, webGpt: component.webGpt, ocx: component.ocx };
  if (component.id === 'ocx') return { ...base, version: component.version, healthy: component.healthy, overview: component.overview, sections: component.sections };
  if (component.id === 'web-gpt') return { ...base, version: component.version, mode: component.mode, routeActive: component.routeActive, harnessReady: component.harnessReady, activeHttpTurns: component.activeHttpTurns, activeBrowserTurns: component.activeBrowserTurns };
  if (component.id === 'workspace-mcp') return { ...base, serverReady: component.serverReady, workspaceCount: component.workspaceCount, tunnel: component.tunnel, publication: { needsPublish: component.publication?.needsPublish, toolCount: component.publication?.toolCount } };
  if (component.id === 'guidance') return { ...base, failed: component.failed, deploymentIssues: component.deploymentIssues };
  return base;
}

async function recoveryBundle() {
  const status = await collectStatus();
  const ids = new Set(['codex-routes', 'ocx', 'web-gpt', 'workspace-mcp', 'guidance']);
  const components = status.components.filter(component => ids.has(component.id)).map(supportComponent);
  const routes = components.find(component => component.id === 'codex-routes');
  const attention = components.filter(component => component.state !== 'ready').map(component => component.id);
  return sanitize({
    ok: attention.length === 0,
    generatedAt: status.generatedAt,
    purpose: 'Web GPT 또는 Codex에 붙여 넣을 수 있는 비밀 제외 AICC 진단 묶음',
    summary: { ready: status.summary.ready, total: status.summary.total, attention },
    components,
    recommendedNextStep: routes?.activeRoute === 'native'
      ? '17841이 정상일 때 통합 모델 경로 다시 연결을 미리보기로 실행하세요.'
      : routes?.webGpt?.healthy === false
        ? 'Native Codex 긴급 복구를 검토하고 17841 브리지를 별도로 진단하세요.'
        : '현재 경로를 유지하고 확인 필요 구역만 개별 진단하세요.',
    commands: [
      'aicc status --json',
      'codex-chatgpt-web doctor --json',
      'codex-chatgpt-web route status',
      'ocx health --json',
      'ocx status --json',
      'ocx system diagnostics --json'
    ],
    consultationPrompt: '아래 AICC 진단 묶음을 분석해 주세요. 정상 구역은 건드리지 말고, 원인 후보와 가장 안전한 다음 조치 및 롤백 방법을 순서대로 제시해 주세요.'
  });
}

const definitions = Object.freeze({
  'status': { title: '전체 상태', run: () => collectStatus() },
  'setup.check': { title: '설치 상태 점검', run: () => setupEnvironment({ checkOnly: true }) },
  'cli.status': { title: 'CLI 연결 점검', run: () => cliToolStatus() },
  'routes.status': { title: 'Codex 모델 경로 점검', run: () => codexRouteStatus() },
  'support.bundle': { title: '상담용 통합 진단 묶음', run: () => recoveryBundle() },
  'web-gpt.doctor': {
    title: 'Web GPT 브리지 정밀 진단',
    command: () => ({ executable: webGptCli, args: ['doctor', '--json'] })
  },
  'ocx.diagnostics': {
    title: 'OCX 독립 진단',
    command: () => ({ executable: process.env.AICC_OCX_EXECUTABLE?.trim() || 'ocx', args: ['system', 'diagnostics', '--json'] })
  },
  'agents.status': { title: 'Codex 하위 에이전트 상태', run: () => agentsStatus() },
  'workspace.status': { title: 'AICC 원격 작업공간 MCP 상태', run: () => workspaceMcpStatus() },
  'workspace.publish-preflight': {
    title: 'AICC Workspace 게시 사전검사',
    run: async () => {
      const runtime = await workspaceMcpStatus();
      const publication = workspacePublicationStatus();
      return {
        ok: runtime.state === 'ready',
        runtime: {
          state: runtime.state,
          detail: runtime.detail,
          workspaceCount: runtime.workspaceCount ?? 0,
          tunnelReady: runtime.tunnel?.ready === true
        },
        publication: {
          needsPublish: publication.needsPublish,
          toolCount: publication.manifest.toolCount,
          readToolCount: publication.manifest.readToolCount,
          writeToolCount: publication.manifest.writeToolCount,
          manifestHash: publication.manifest.hash,
          tools: publication.manifest.tools,
          published: publication.published,
          manageUrl: publication.manageUrl
        }
      };
    }
  },
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
