import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { configFileSecurity, configPath, defaultPythonCommand, exampleConfig, parseEnvFile } from './config.mjs';
import { runCommand } from './lib/command.mjs';
import { fileURLToPath } from 'node:url';
import { configureWorkspaceMcp, readWorkspaceMcpConfig } from './workspace-mcp.mjs';

function privateDirectory(directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  if (process.platform !== 'win32') fs.chmodSync(directory, 0o700);
}

function copyPrivateExample(source, destination, replacements = {}) {
  if (fs.existsSync(destination)) return false;
  let content = fs.readFileSync(source, 'utf8');
  for (const [from, to] of Object.entries(replacements)) content = content.replaceAll(from, to);
  fs.writeFileSync(destination, content, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
  return true;
}

async function commandCheck(name, executable, args, required, runner) {
  const result = await runner(executable, args, { timeoutMs: 8_000 });
  return {
    name,
    required,
    ok: result.ok,
    detail: result.ok ? (result.stdout.trim().split(/\r?\n/)[0] || '사용 가능') : `${executable}을(를) 찾거나 실행할 수 없습니다.`
  };
}

export async function setupEnvironment(options = {}) {
  const suppliedEnv = options.env ?? process.env;
  const env = { ...suppliedEnv };
  const home = options.home ?? os.homedir();
  const file = options.file ?? configPath(env, home);
  const stateRoot = path.dirname(file);
  let created = false;

  if (!fs.existsSync(file) && !options.checkOnly) {
    privateDirectory(stateRoot);
    fs.writeFileSync(file, exampleConfig, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    created = true;
  }

  const security = configFileSecurity(file);
  let syntax = { ok: false, detail: security.reason };
  if (security.ok) {
    try {
      const values = parseEnvFile(fs.readFileSync(file, 'utf8'));
      for (const [key, value] of Object.entries(values)) {
        if (suppliedEnv[key] === undefined) env[key] = value;
      }
      syntax = { ok: true, detail: '지원되는 설정 형식입니다.' };
    } catch (error) {
      syntax = { ok: false, detail: error.message };
    }
  }

  if (!options.checkOnly) {
    const resolvedStateRoot = env.AICC_STATE_ROOT || stateRoot;
    const accountManagerStateRoot = env.AICC_ACCOUNT_MANAGER_STATE_ROOT || path.join(resolvedStateRoot, 'account-manager');
    privateDirectory(accountManagerStateRoot);

    const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    const guidanceState = path.join(resolvedStateRoot, 'guidance');
    privateDirectory(guidanceState);
    const examples = path.join(projectRoot, 'guidance', 'config');
    copyPrivateExample(path.join(examples, 'coordination.example.toml'), path.join(guidanceState, 'coordination.toml'), { '${AICC_STATE_ROOT}': resolvedStateRoot });
    copyPrivateExample(path.join(examples, 'website-maker.example.json'), path.join(guidanceState, 'website-maker.json'));
    copyPrivateExample(path.join(examples, 'website-projects.example.json'), path.join(guidanceState, 'website-projects.json'));
    copyPrivateExample(path.join(examples, 'agent-session-index.example.toml'), path.join(guidanceState, 'agent-session-index.toml'));
    const projectsRoot = env.AICC_WORKSPACE_PROJECTS_ROOT || path.join(home, 'dev', 'projects');
    if (fs.existsSync(projectsRoot) && !readWorkspaceMcpConfig({ stateRoot: resolvedStateRoot })) {
      configureWorkspaceMcp({ stateRoot: resolvedStateRoot, projectsRoot });
    }
  }

  const runner = options.runCommand ?? runCommand;
  const python = env.AICC_PYTHON
    ? { executable: env.AICC_PYTHON, args: [] }
    : defaultPythonCommand(options.platform);
  const checks = await Promise.all([
    commandCheck('Node.js 20+', process.execPath, ['--version'], true, runner),
    commandCheck('Python 3.11+', python.executable, [...python.args, '--version'], true, runner),
    commandCheck('OCX', env.AICC_OCX_EXECUTABLE || 'ocx', ['--version'], false, runner),
    commandCheck('ripgrep', 'rg', ['--version'], true, runner),
    ...(process.platform === 'darwin' ? [commandCheck('macOS sandbox', '/usr/bin/sandbox-exec', ['-p', '(version 1) (allow default)', '/usr/bin/true'], true, runner)] : [])
  ]);
  const nodeMajor = Number(process.versions.node.split('.')[0]);
  checks[0].ok = checks[0].ok && nodeMajor >= 20;
  if (!checks[0].ok) checks[0].detail = 'Node.js 20 이상이 필요합니다.';

  const requiredReady = security.ok && syntax.ok && checks.filter(check => check.required).every(check => check.ok);
  return { ok: requiredReady, created, file, stateRoot, security, syntax, checks };
}
