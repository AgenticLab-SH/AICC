import { checkOpenaiCatalog } from './openai-catalog-check.mjs';
import { configureOpenaiEligibility, configureOpenaiProvider, evaluateOpenaiMonitor, probeAllOpenaiModels, probeOpenaiModel } from './openai-usage.mjs';
import { installOpenaiAgentGuard, openaiAgentGuardStatus, rollbackOpenaiAgentGuard } from '../tools/platform/codex/install-openai-api-guard.mjs';

function option(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const command = process.argv[2];
let result;

if (command === 'provider') {
  result = configureOpenaiProvider({ enabled: option('--enabled') });
} else if (command === 'model') {
  result = configureOpenaiProvider({
    model: option('--model'),
    callEnabled: option('--call-enabled'),
    agentSelectable: option('--agent-selectable')
  });
} else if (command === 'default-model') {
  result = configureOpenaiProvider({ defaultModel: option('--model') });
} else if (command === 'probe') {
  result = await probeOpenaiModel(option('--model'));
} else if (command === 'probe-all') {
  result = await probeAllOpenaiModels();
} else if (command === 'catalog-check') {
  result = await checkOpenaiCatalog();
} else if (command === 'monitor-run') {
  result = evaluateOpenaiMonitor();
} else if (command === 'agent-guard') {
  const action = option('--action') || 'status';
  result = action === 'apply' ? installOpenaiAgentGuard() : action === 'rollback' ? rollbackOpenaiAgentGuard() : openaiAgentGuardStatus();
} else if (command === 'eligibility') {
  result = configureOpenaiEligibility({
    source: option('--source'),
    declaredFamilies: String(option('--declared') || '').split(',').filter(Boolean),
    observedIncentiveModels: String(option('--observed') || '').split(',').filter(Boolean)
  });
} else {
  throw new Error(`알 수 없는 OpenAI provider 명령: ${command || '(없음)'}`);
}

process.stdout.write(`${JSON.stringify(result)}\n`);
