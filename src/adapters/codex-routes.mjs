import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { runCommand } from '../lib/command.mjs';
import { sanitize } from '../lib/redact.mjs';

const WEB_GPT_URL = 'http://127.0.0.1:17841/v1';
const OCX_URL = 'http://127.0.0.1:10100/v1';
const NATIVE_URL = 'https://chatgpt.com/backend-api/codex';

function readText(file, reader = fs.readFileSync) {
  try { return reader(file, 'utf8'); } catch { return '' ; }
}

function tomlString(source, key) {
  const match = String(source).match(new RegExp(`^\\s*${key}\\s*=\\s*["']([^"']+)["']`, 'm'));
  return match?.[1] ?? null;
}

function routeKind(url) {
  if (!url || url === NATIVE_URL) return 'native';
  if (url === WEB_GPT_URL) return 'web-gpt';
  if (url === OCX_URL) return 'ocx';
  return 'custom';
}

function jsonResult(result) {
  if (!result?.ok) return null;
  try { return sanitize(JSON.parse(result.stdout)); } catch { return null; }
}

function defaultWebGptCli() {
  const configured = process.env.AICC_WEB_GPT_CLI?.trim();
  if (configured) return configured;
  return '/Applications/Codex Web GPT.app/Contents/Resources/runtime/bin/codex-chatgpt-web';
}

async function health(fetcher, url) {
  try {
    const response = await fetcher(url, { signal: AbortSignal.timeout(2_500) });
    if (!response.ok) return null;
    return sanitize(await response.json());
  } catch { return null; }
}

export async function codexRouteStatus(options = {}) {
  const home = options.home ?? os.homedir();
  const configPath = options.configPath ?? path.join(home, '.codex', 'config.toml');
  const nativeConfigPath = options.nativeConfigPath ?? path.join(home, '.codex', 'codex-native.config.toml');
  const reader = options.readFile ?? fs.readFileSync;
  const currentConfig = readText(configPath, reader);
  const nativeConfig = readText(nativeConfigPath, reader);
  const routeUrl = tomlString(currentConfig, 'openai_base_url');
  const nativeUrl = tomlString(nativeConfig, 'openai_base_url');
  const runner = options.runCommand ?? runCommand;
  const webGptCli = options.webGptCli ?? defaultWebGptCli();
  const fetcher = options.fetch ?? fetch;
  const [routeResult, webGptHealth, ocxHealth] = await Promise.all([
    runner(webGptCli, ['route', 'status'], { timeoutMs: 5_000 }).catch(() => null),
    health(fetcher, 'http://127.0.0.1:17841/healthz'),
    health(fetcher, 'http://127.0.0.1:10100/healthz')
  ]);
  const route = jsonResult(routeResult);
  const kind = routeKind(routeUrl);
  const webHttpTurns = Number(webGptHealth?.active_http_turns ?? 0);
  const webBrowserTurns = Number(webGptHealth?.active_browser_turns ?? 0);
  const activeTurns = Number.isFinite(webHttpTurns + webBrowserTurns) ? webHttpTurns + webBrowserTurns : null;
  const nativeReady = nativeUrl === NATIVE_URL;
  const routeKnown = ['native', 'web-gpt', 'ocx'].includes(kind);

  return sanitize({
    id: 'codex-routes',
    label: 'Codex 모델 경로',
    state: routeKnown && nativeReady ? 'ready' : 'attention',
    detail: kind === 'web-gpt'
      ? '통합 모델 선택기가 Web GPT 브리지를 사용하고 있습니다.'
      : kind === 'ocx'
        ? 'Codex가 OCX에 직접 연결되어 있습니다.'
        : kind === 'native'
          ? 'Codex가 공식 Native endpoint에 직접 연결되어 있습니다.'
          : '알 수 없는 사용자 지정 모델 경로를 확인해야 합니다.',
    activeRoute: kind,
    routeUrl: routeUrl ?? NATIVE_URL,
    routeInstalled: route?.installed === true,
    routeActive: route?.active === true,
    nativeReady,
    nativeProfile: {
      configured: Boolean(nativeConfig),
      officialEndpoint: nativeReady
    },
    webGpt: {
      healthy: webGptHealth?.status === 'ok',
      acceptingTurns: webGptHealth?.accepting_turns === true,
      activeTurns,
      mode: webGptHealth?.mode ?? null
    },
    ocx: {
      healthy: ocxHealth?.ok === true || ocxHealth?.status === 'ok',
      port: ocxHealth?.port ?? 10100
    },
    recovery: {
      nativeCommand: 'ocx restore',
      bridgeCommand: 'codex-chatgpt-web route connect',
      requiresDesktopRestart: true
    }
  });
}

export const codexRouteConstants = Object.freeze({ WEB_GPT_URL, OCX_URL, NATIVE_URL });
