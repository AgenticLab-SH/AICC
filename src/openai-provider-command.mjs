import { configureOpenaiProvider, probeOpenaiModel } from './openai-usage.mjs';

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
} else {
  throw new Error(`알 수 없는 OpenAI provider 명령: ${command || '(없음)'}`);
}

process.stdout.write(`${JSON.stringify(result)}\n`);
