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

export async function collectStatus(options = {}) {
  const stateRoot = process.env.AICC_STATE_ROOT || path.join(os.homedir(), '.ai-control-center');
  const [accounts, ocxAccounts, ocx, webGpt, portal, guidance, agents, workspace, tools] = await Promise.all([
    (options.accountStatus ?? accountStatus)(options.accounts),
    (options.ocxAccountStatus ?? ocxAccountStatus)(options.ocxAccounts),
    (options.ocxStatus ?? ocxStatus)(options.ocx),
    (options.webGptStatus ?? webGptStatus)(options.webGpt),
    (options.authPortalStatus ?? authPortalStatus)(options.authPortal),
    Promise.resolve((options.guidanceStatus ?? guidanceStatusQuick)(options.guidance)),
    Promise.resolve((options.agentsStatus ?? agentsStatus)(options.agents)),
    (options.workspaceMcpStatus ?? workspaceMcpStatus)(options.workspace),
    (options.localToolStatus ?? localToolStatus)(options.tools)
  ]);
  const components = [accounts, ocxAccounts, ocx, webGpt, portal, guidance, {
    id: 'codex-agents', label: 'Codex 하위 에이전트', state: agents.state === 'ready' ? 'ready' : 'attention',
    detail: agents.message, summary: agents.summary, issues: agents.issues
  }, workspace, ...tools];
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
