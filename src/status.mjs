import os from 'node:os';
import path from 'node:path';
import { accountStatus } from './adapters/accounts.mjs';
import { ocxStatus } from './adapters/ocx.mjs';
import { ocxAccountStatus } from './adapters/ocx-accounts.mjs';
import { localToolStatus } from './adapters/local-tools.mjs';
import { pathStatus } from './lib/fs-status.mjs';
import { sanitize } from './lib/redact.mjs';
import { authPortalStatus } from './adapters/auth-portal.mjs';
import { guidanceStatusQuick } from './adapters/guidance-status.mjs';
import { agentsStatus } from './agents.mjs';
import { workspaceMcpStatus } from './workspace-mcp.mjs';
import { webGptStatus } from './adapters/web-gpt.mjs';
import { codexRouteStatus } from './adapters/codex-routes.mjs';

async function isolatedComponent(id, label, operation, fallback = null) {
  try { return await operation(); }
  catch {
    if (fallback !== null) return fallback;
    return {
      id,
      label,
      state: 'attention',
      detail: '이 구역의 상태 조회만 실패했습니다. 다른 AICC 기능은 계속 사용할 수 있습니다.',
      isolatedFailure: true
    };
  }
}

export async function collectStatus(options = {}) {
  const stateRoot = process.env.AICC_STATE_ROOT || path.join(os.homedir(), '.ai-control-center');
  const [accounts, ocxAccounts, ocx, webGpt, routes, portal, guidance, agents, workspace, tools] = await Promise.all([
    isolatedComponent('accounts', 'GPT 계정', () => (options.accountStatus ?? accountStatus)(options.accounts)),
    isolatedComponent('ocx-accounts', 'OCX 계정 풀', () => (options.ocxAccountStatus ?? ocxAccountStatus)(options.ocxAccounts)),
    isolatedComponent('ocx', 'OCX 모델 연결', () => (options.ocxStatus ?? ocxStatus)(options.ocx)),
    isolatedComponent('web-gpt', 'Web GPT 모델 브리지', () => (options.webGptStatus ?? webGptStatus)(options.webGpt)),
    isolatedComponent('codex-routes', 'Codex 모델 경로', () => (options.codexRouteStatus ?? codexRouteStatus)(options.codexRoutes)),
    isolatedComponent('auth-portal', '웹 로그인 전달 포털', () => (options.authPortalStatus ?? authPortalStatus)(options.authPortal)),
    isolatedComponent('guidance', '지침·스킬·Codex 에이전트', () => Promise.resolve((options.guidanceStatus ?? guidanceStatusQuick)(options.guidance))),
    isolatedComponent('codex-agents', 'Codex 하위 에이전트', () => Promise.resolve((options.agentsStatus ?? agentsStatus)(options.agents))),
    isolatedComponent('workspace-mcp', 'AICC 원격 작업공간 MCP', () => (options.workspaceMcpStatus ?? workspaceMcpStatus)(options.workspace)),
    isolatedComponent('local-tools', '로컬 앱', () => (options.localToolStatus ?? localToolStatus)(options.tools), [])
  ]);
  const agentComponent = agents.id === 'codex-agents' && agents.isolatedFailure
    ? agents
    : {
        id: 'codex-agents', label: 'Codex 하위 에이전트', state: agents.state === 'ready' ? 'ready' : 'attention',
        detail: agents.message, summary: agents.summary, issues: agents.issues
      };
  const components = [accounts, ocxAccounts, ocx, webGpt, routes, portal, guidance, agentComponent, workspace, ...tools];
  const healthComponents = components.filter(component => !(component.optional && component.state === 'unavailable'));
  const ready = healthComponents.filter(component => component.state === 'ready').length;

  return sanitize({
    ok: true,
    schemaVersion: 1,
    mode: 'local-control',
    generatedAt: new Date().toISOString(),
    summary: {
      ready,
      total: healthComponents.length,
      attention: healthComponents.length - ready
    },
    components,
    stateRoots: [
      pathStatus(stateRoot),
      pathStatus(path.join(stateRoot, 'workspace-mcp')),
      pathStatus(process.env.AICC_ACCOUNT_MANAGER_STATE_ROOT || path.join(stateRoot, 'account-manager')),
      pathStatus(path.join(os.homedir(), '.codex')),
      pathStatus(path.join(os.homedir(), '.codex-multi')),
      pathStatus(path.join(os.homedir(), '.opencodex'))
    ]
  });
}
