import { spawn, spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { authPortalDetails } from './adapters/auth-portal.mjs';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const implementation = path.join(projectRoot, 'components', 'account-manager', 'ops', 'local', 'codex_multi.py');

function pythonCandidates() {
  if (process.env.AICC_PYTHON) return [{ executable: process.env.AICC_PYTHON, prefix: [] }];
  if (process.platform === 'win32') return [{ executable: 'py', prefix: ['-3'] }, { executable: 'python', prefix: [] }];
  return ['python3.14', 'python3.13', 'python3.12', 'python3.11', 'python3']
    .map(executable => ({ executable, prefix: [] }));
}

function selectPython() {
  for (const candidate of pythonCandidates()) {
    const result = spawnSync(candidate.executable, [...candidate.prefix, '-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'], {
      stdio: 'ignore', windowsHide: true
    });
    if (result.status === 0) return candidate;
  }
  throw new Error('Python 3.11 이상을 찾을 수 없습니다.');
}

function accountEnvironment() {
  const stateRoot = process.env.AICC_STATE_ROOT || path.join(os.homedir(), '.ai-control-center');
  const accountState = process.env.AICC_ACCOUNT_MANAGER_STATE_ROOT || path.join(stateRoot, 'account-manager');
  return {
    ...process.env,
    CM_AUTH_LOCAL_CONFIG: process.env.CM_AUTH_LOCAL_CONFIG || path.join(accountState, 'auth-portal.env')
  };
}

function ocxArgs(args) {
  const subcommand = args[0] || 'list';
  const rest = args.slice(1);
  if (subcommand === 'list') return ['account', 'list', rest[0] && !rest[0].startsWith('-') ? rest.shift() : 'openai', ...rest];
  if (['current', 'refresh', 'auto-switch'].includes(subcommand)) return ['account', subcommand, 'openai', ...rest];
  if (['use', 'remove', 'add-key'].includes(subcommand)) return ['account', subcommand, 'openai', ...rest];
  if (['login', 'reauth', 'code', 'cancel', 'reset-credits'].includes(subcommand)) return ['account', subcommand, ...rest];
  if (subcommand === 'help' || subcommand === '--help' || subcommand === '-h') return ['account', '--help'];
  throw new Error(`알 수 없는 OCX 계정 명령: ${subcommand}`);
}

function spawnInherited(executable, args, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, {
      cwd: projectRoot,
      env,
      stdio: 'inherit',
      windowsHide: true
    });
    child.once('error', reject);
    child.once('exit', (code, signal) => {
      if (signal) process.kill(process.pid, signal);
      else resolve(code ?? 1);
    });
  });
}

export async function runAccountCli(args = []) {
  if (args[0] === 'portal') {
    const details = authPortalDetails();
    if (!details.configured) throw new Error('웹 로그인 전달 포털 주소가 구성되지 않았습니다.');
    const subcommand = args[1] || 'status';
    if (subcommand === 'status') {
      if (args.includes('--json')) console.log(JSON.stringify({ ok: true, configured: true, url: details.url }, null, 2));
      else console.log(`웹 로그인 전달 포털: ${details.url}`);
      return 0;
    }
    if (subcommand === 'open') {
      const opener = process.platform === 'darwin'
        ? ['open', [details.url]]
        : process.platform === 'win32'
          ? ['cmd.exe', ['/d', '/s', '/c', 'start', '', details.url]]
          : ['xdg-open', [details.url]];
      const child = spawn(opener[0], opener[1], { detached: true, stdio: 'ignore', windowsHide: true });
      child.unref();
      console.log(`웹 로그인 전달 포털을 여는 중입니다: ${details.url}`);
      return 0;
    }
    throw new Error(`알 수 없는 포털 명령: ${subcommand}`);
  }
  if (args[0] === 'ocx') {
    return spawnInherited(process.env.AICC_OCX_EXECUTABLE?.trim() || 'ocx', ocxArgs(args.slice(1)));
  }
  const python = selectPython();
  return spawnInherited(
    python.executable,
    [...python.prefix, implementation, ...args],
    accountEnvironment()
  );
}
