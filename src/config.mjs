import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const supportedConfigKeys = new Set([
  'AICC_HOST',
  'AICC_PORT',
  'AICC_STATE_ROOT',
  'AICC_ACCOUNT_MANAGER_STATE_ROOT',
  'AICC_PYTHON',
  'AICC_NPM_EXECUTABLE',
  'AICC_OCX_EXECUTABLE',
  'AICC_ACCOUNT_MANAGER_PATH',
  'AICC_CM_STATUS_EXECUTABLE',
  'AICC_CM_STATUS_ARGS_JSON',
  'AICC_OCX_VERSION_EXECUTABLE',
  'AICC_OCX_VERSION_ARGS_JSON',
  'AICC_OCX_HEALTH_EXECUTABLE',
  'AICC_OCX_HEALTH_ARGS_JSON',
  'AICC_WORKSPACE_PROJECTS_ROOT'
]);

export function configPath(env = process.env, home = os.homedir()) {
  return env.AICC_CONFIG_FILE?.trim()
    || path.join(env.AICC_STATE_ROOT?.trim() || path.join(home, '.ai-control-center'), 'config.env');
}

function decodeValue(raw) {
  const value = raw.trim();
  if (!value) return '';
  if (value.startsWith('"') && value.endsWith('"')) {
    try { return JSON.parse(value); } catch { throw new Error('큰따옴표 값을 읽을 수 없습니다.'); }
  }
  if (value.startsWith("'") && value.endsWith("'")) return value.slice(1, -1);
  return value;
}

export function parseEnvFile(text) {
  const values = {};
  for (const [index, sourceLine] of String(text).split(/\r?\n/).entries()) {
    const line = sourceLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = /^(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*)$/.exec(line);
    if (!match) throw new Error(`config.env ${index + 1}번째 줄 형식이 올바르지 않습니다.`);
    const [, key, rawValue] = match;
    if (!supportedConfigKeys.has(key)) {
      throw new Error(`config.env ${index + 1}번째 줄의 ${key}는 지원하지 않는 설정입니다.`);
    }
    values[key] = decodeValue(rawValue);
  }
  return values;
}

export function configFileSecurity(file) {
  try {
    const stat = fs.statSync(file);
    if (!stat.isFile()) return { ok: false, reason: '설정 경로가 파일이 아닙니다.' };
    if (process.platform !== 'win32' && (stat.mode & 0o077) !== 0) {
      return { ok: false, reason: '설정 파일 권한은 소유자 전용(0600)이어야 합니다.' };
    }
    return { ok: true, reason: null };
  } catch (error) {
    return { ok: false, reason: error.code === 'ENOENT' ? '설정 파일이 없습니다.' : error.message };
  }
}

export function loadUserEnv(options = {}) {
  const env = options.env ?? process.env;
  const file = options.file ?? configPath(env, options.home);
  if (!fs.existsSync(file)) return { loaded: false, file, keys: [] };
  const security = configFileSecurity(file);
  if (!security.ok) throw new Error(`${file}: ${security.reason}`);
  const values = parseEnvFile(fs.readFileSync(file, 'utf8'));
  const loaded = [];
  for (const [key, value] of Object.entries(values)) {
    if (env[key] === undefined) {
      env[key] = value;
      loaded.push(key);
    }
  }
  return { loaded: true, file, keys: loaded };
}

export const exampleConfig = `# AI Control Center personal configuration
# Keep this file on your machine. Never commit it.

AICC_HOST=127.0.0.1
AICC_PORT=4381
# Account Manager and Workspace MCP state default under ~/.ai-control-center
# AICC_ACCOUNT_MANAGER_STATE_ROOT=/absolute/private/account-manager/path
# AICC_WORKSPACE_PROJECTS_ROOT=/absolute/projects/path

# Uncomment only when auto-discovery does not fit your machine.
# AICC_PYTHON=python3
# AICC_NPM_EXECUTABLE=npm
# AICC_OCX_EXECUTABLE=ocx
# AICC_ACCOUNT_MANAGER_PATH=/absolute/path/to/account-manager
`;

export function defaultPythonCommand(platform = process.platform) {
  return platform === 'win32'
    ? { executable: 'py', args: ['-3'] }
    : { executable: 'python3', args: [] };
}
