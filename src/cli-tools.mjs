import { runCommand } from './lib/command.mjs';

export const pinnedCliPackages = Object.freeze({
  ocx: '@bitkyc08/opencodex@2.7.42',
  codex: '@openai/codex@0.146.0',
  claude: '@anthropic-ai/claude-code@2.1.220'
});

function firstLine(result) {
  return result.ok ? result.stdout.trim().split(/\r?\n/)[0] : '';
}

function parseJson(result) {
  if (!result.ok) return null;
  try { return JSON.parse(result.stdout); } catch { return null; }
}

function runPlatformCommand(runner, executable, args, options, platform) {
  if (platform === 'win32') {
    return runner('cmd.exe', ['/d', '/s', '/c', executable, ...args], options);
  }
  return runner(executable, args, options);
}

async function inspectCli(options = {}) {
  const runner = options.runCommand ?? runCommand;
  const env = options.env ?? process.env;
  const platform = options.platform ?? process.platform;
  const ocx = env.AICC_OCX_EXECUTABLE?.trim() || 'ocx';
  const [ocxVersion, codexVersion, claudeVersion, health, systemStatus, claudeConfig] = await Promise.all([
    runPlatformCommand(runner, ocx, ['--version'], { timeoutMs: 8_000 }, platform),
    runPlatformCommand(runner, 'codex', ['--version'], { timeoutMs: 8_000 }, platform),
    runPlatformCommand(runner, 'claude', ['--version'], { timeoutMs: 8_000 }, platform),
    runPlatformCommand(runner, ocx, ['health', '--json'], { timeoutMs: 8_000 }, platform),
    runPlatformCommand(runner, ocx, ['system', 'status', '--json'], { timeoutMs: 8_000 }, platform),
    runPlatformCommand(runner, ocx, ['claude', 'config', 'status', '--json'], { timeoutMs: 8_000 }, platform)
  ]);
  return {
    commands: {
      ocx: { available: ocxVersion.ok, version: firstLine(ocxVersion) },
      codex: { available: codexVersion.ok, version: firstLine(codexVersion) },
      claude: { available: claudeVersion.ok, version: firstLine(claudeVersion) }
    },
    health: parseJson(health),
    systemStatus: parseJson(systemStatus),
    claudeConfig: parseJson(claudeConfig),
    executable: ocx
  };
}

function summarizeStatus(inspected, platform = process.platform) {
  const proxyReady = inspected.health?.ok === true;
  const codexConnected = inspected.systemStatus?.startup?.routingInjected === true;
  const claudeEnabled = inspected.claudeConfig?.enabled !== false;
  const plainClaudeConnected = platform === 'darwin' && inspected.claudeConfig?.systemEnv === true;
  return {
    ok: inspected.commands.ocx.available && inspected.commands.codex.available && inspected.commands.claude.available && proxyReady && codexConnected,
    proxyReady,
    codexConnected,
    commands: inspected.commands,
    routing: {
      codex: inspected.commands.codex.available && proxyReady && codexConnected ? 'ocx' : 'unavailable',
      claude: !inspected.commands.claude.available || !claudeEnabled
        ? 'unavailable'
        : plainClaudeConnected
          ? 'ocx-direct'
          : 'ocx-wrapper'
    },
    plainClaudeConnected,
    note: plainClaudeConnected
      ? '새 터미널에서 codex와 claude를 직접 실행할 수 있습니다.'
      : 'Codex는 OCX로 연결됩니다. Claude는 ocx claude로 실행하십시오.'
  };
}

export async function cliToolStatus(options = {}) {
  const platform = options.platform ?? process.platform;
  return summarizeStatus(await inspectCli({ ...options, platform }), platform);
}

async function installPackage(runner, npmExecutable, spec, platform) {
  return runPlatformCommand(runner, npmExecutable, ['install', '--global', spec], { timeoutMs: 180_000 }, platform);
}

export async function setupCliTools(options = {}) {
  const runner = options.runCommand ?? runCommand;
  const env = options.env ?? process.env;
  const platform = options.platform ?? process.platform;
  const nodeMajor = options.nodeMajor ?? Number(process.versions.node.split('.')[0]);
  const npmExecutable = env.AICC_NPM_EXECUTABLE?.trim() || 'npm';
  let inspected = await inspectCli({ runCommand: runner, env, platform });
  const installed = [];

  if (options.installMissing) {
    if (!inspected.commands.claude.available && nodeMajor < 22) {
      throw new Error('Claude Code 설치에는 Node.js 22 이상이 필요합니다. 아무 CLI도 설치하지 않았습니다.');
    }
    for (const name of ['ocx', 'codex', 'claude']) {
      if (inspected.commands[name].available) continue;
      const result = await installPackage(runner, npmExecutable, pinnedCliPackages[name], platform);
      if (!result.ok) throw new Error(`${pinnedCliPackages[name]} 설치에 실패했습니다.`);
      installed.push(pinnedCliPackages[name]);
    }
    inspected = await inspectCli({ runCommand: runner, env, platform });
  }

  const missing = Object.entries(inspected.commands).filter(([, value]) => !value.available).map(([name]) => name);
  const summary = summarizeStatus(inspected, platform);
  if (missing.length > 0) {
    return {
      ...summary,
      ok: false,
      installed,
      missing,
      installCommand: 'aicc cli setup --install-missing'
    };
  }

  const ensured = await runPlatformCommand(runner, inspected.executable, ['ensure'], { timeoutMs: 30_000 }, platform);
  if (!ensured.ok) throw new Error('OCX 준비에 실패했습니다. ocx doctor로 상태를 확인하십시오.');
  if (platform === 'darwin') {
    const connected = await runPlatformCommand(runner, inspected.executable, [
      'claude', 'config', 'set', '--enabled', 'on', '--system-env', 'on', '--json'
    ], { timeoutMs: 30_000 }, platform);
    if (!connected.ok) throw new Error('일반 claude 명령의 OCX 자동 연결 설정에 실패했습니다.');
  }

  const finalState = await inspectCli({ runCommand: runner, env, platform });
  return { ...summarizeStatus(finalState, platform), installed, missing: [] };
}
