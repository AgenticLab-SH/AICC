import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

function unquote(value) {
  const text = String(value ?? '').trim();
  if ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"))) {
    return text.slice(1, -1);
  }
  return text;
}

export function authPortalDetails(options = {}) {
  const env = options.env ?? process.env;
  const stateRoot = options.stateRoot || env.AICC_STATE_ROOT || path.join(os.homedir(), '.ai-control-center');
  const configPath = options.configPath
    || env.CM_AUTH_LOCAL_CONFIG
    || path.join(env.AICC_ACCOUNT_MANAGER_STATE_ROOT || path.join(stateRoot, 'account-manager'), 'auth-portal.env');
  let source = '';
  try { source = (options.readFile ?? fs.readFileSync)(configPath, 'utf8'); }
  catch { return { configured: false, configPath, url: null }; }
  const match = source.match(/^\s*(?:export\s+)?CM_AUTH_PORTAL_URL\s*=\s*(.+?)\s*$/m);
  const raw = unquote(match?.[1]);
  try {
    const url = new URL(raw);
    if (!['https:', 'http:'].includes(url.protocol)) throw new Error('unsupported protocol');
    return { configured: true, configPath, url: url.toString() };
  } catch {
    return { configured: false, configPath, url: null };
  }
}

export async function authPortalStatus(options = {}) {
  const details = authPortalDetails(options);
  return {
    id: 'auth-portal',
    label: '웹 로그인 전달 포털',
    state: details.configured ? 'ready' : 'unavailable',
    optional: true,
    detail: details.configured ? '원격 로그인 포털이 구성되어 있습니다.' : '원격 로그인 포털이 구성되지 않았습니다.',
    configured: details.configured,
    url: details.url
  };
}
