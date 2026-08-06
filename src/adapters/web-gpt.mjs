import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { sanitize } from '../lib/redact.mjs';

const WEB_MODELS = Object.freeze([
  'Web / 임시 / 낮음', 'Web / 임시 / 중간', 'Web / 임시 / 높음', 'Web / 임시 / 매우 높음',
  'Web / 저장 / 낮음', 'Web / 저장 / 중간', 'Web / 저장 / 높음', 'Web / 저장 / 매우 높음'
]);
const WEB_PRO_MODELS = Object.freeze(['Web / 임시 / Pro', 'Web / 저장 / Pro']);

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

function configuredRoute(configFile) {
  try {
    const text = fs.readFileSync(configFile, 'utf8');
    return text.match(/^\s*openai_base_url\s*=\s*["']([^"']+)["']/m)?.[1] ?? null;
  } catch { return null; }
}

async function health(url, fetcher, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(url, { headers: { accept: 'application/json' }, signal: controller.signal });
    if (!response.ok) return null;
    return sanitize(await response.json());
  } catch { return null; }
  finally { clearTimeout(timer); }
}

export async function webGptStatus(options = {}) {
  const home = options.home ?? os.homedir();
  const stateRoot = options.stateRoot ?? path.join(home, '.codex-chatgpt-web');
  const configPath = options.configPath ?? path.join(stateRoot, 'config.json');
  const codexConfigPath = options.codexConfigPath ?? path.join(home, '.codex', 'config.toml');
  const appPath = options.appPath ?? '/Applications/Codex Web GPT.app';
  const config = readJson(configPath);
  const port = Number(config?.port || 17841);
  const baseUrl = `http://127.0.0.1:${port}/v1`;
  const runtime = await health(`http://127.0.0.1:${port}/healthz`, options.fetch ?? fetch, options.timeoutMs ?? 2_500);
  const installed = Boolean(config || fs.existsSync(appPath));
  const healthy = runtime?.status === 'ok' || runtime?.ok === true;
  const route = configuredRoute(codexConfigPath);
  const routeActive = route === baseUrl;
  const mode = config?.mode ?? null;
  const proAvailable = config?.proAvailable === true;
  const modelLabels = proAvailable ? [...WEB_MODELS, ...WEB_PRO_MODELS] : [...WEB_MODELS];
  const tunnelConfigured = Boolean(config?.tunnel);
  return sanitize({
    id: 'web-gpt',
    label: 'Web GPT 모델 브리지',
    optional: !installed,
    state: healthy && routeActive ? 'ready' : installed ? 'attention' : 'unavailable',
    detail: !installed
      ? 'Web GPT v2 브리지가 설치되어 있지 않습니다.'
      : !healthy
        ? '브리지가 설치됐지만 현재 응답하지 않습니다.'
        : !routeActive
          ? '브리지는 실행 중이지만 Codex 모델 경로가 아직 연결되지 않았습니다.'
          : 'Web GPT 모델과 Codex 도구 하네스가 연결되어 있습니다.',
    installed,
    healthy,
    routeActive,
    route: routeActive ? baseUrl : null,
    version: runtime?.version ?? config?.releaseVersion ?? null,
    mode,
    browserHost: config?.browserHost ?? null,
    tunnelConfigured,
    proAvailable,
    autoApproveToolCalls: config?.autoApproveToolCalls === true,
    activeHttpTurns: runtime?.active_http_turns ?? null,
    activeBrowserTurns: runtime?.active_browser_turns ?? null,
    maxConcurrentTurns: 5,
    modelLabels,
    modelCount: modelLabels.length,
    inferenceOwner: 'chatgpt-web',
    localHarnessConsumesModelTokens: false,
    stateRoot
  });
}

export { WEB_MODELS, WEB_PRO_MODELS };
