import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { openaiCatalogCheckPath, openaiComplimentaryConfig } from './openai-usage.mjs';

const HELP_JSON_URL = `${openaiComplimentaryConfig.sources.complimentary}.json`;
const MODELS_MARKDOWN_URL = `${openaiComplimentaryConfig.sources.pricing}.md`;

function atomicJsonWrite(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, file);
  if (process.platform !== 'win32') fs.chmodSync(file, 0o600);
}

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function exactComplimentaryIds(text) {
  const patterns = [
    /\b(?:gpt-[a-z0-9.]+(?:-[a-z0-9.]+)*|o\d(?:-[a-z0-9.]+)*)-\d{4}-\d{2}-\d{2}\b/gi,
    /\bgpt-\d+(?:\.\d+)*-(?:sol|terra|luna)\b/gi,
    /\bgpt-\d+(?:\.\d+)*-(?:chat-latest|codex(?:-mini)?)\b/gi,
    /\bcodex-mini-latest\b/gi
  ];
  return Array.from(new Set(patterns.flatMap(pattern => Array.from(text.matchAll(pattern), match => match[0].toLowerCase())))).sort();
}

function developerModelSlugs(text) {
  return Array.from(new Set(Array.from(text.matchAll(/\/api\/docs\/models\/([a-z0-9.-]+)\.md/gi), match => match[1].toLowerCase()))).sort();
}

function documentedModelCandidates(definition) {
  return Array.from(new Set([definition.id, ...(definition.aliases || []), definition.id.replace(/-\d{4}-\d{2}-\d{2}$/, '')]));
}

async function fetchText(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 20_000);
  try {
    const response = await (options.fetchImpl || fetch)(url, {
      signal: controller.signal,
      headers: { 'user-agent': 'AICC catalog drift checker/1.0', accept: 'text/html,text/markdown,application/json' }
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } finally {
    clearTimeout(timeout);
  }
}

export async function checkOpenaiCatalog(options = {}) {
  const checkedAt = new Date(options.now || Date.now()).toISOString();
  const trackedModels = openaiComplimentaryConfig.models.filter(model => model.catalogSource === 'global-help');
  const known = trackedModels.map(model => model.id).sort();
  const knownFamilies = new Set(openaiComplimentaryConfig.models.flatMap(documentedModelCandidates));
  try {
    const [helpText, modelsText] = await Promise.all([
      fetchText(HELP_JSON_URL, options),
      fetchText(MODELS_MARKDOWN_URL, options)
    ]);
    const official = exactComplimentaryIds(helpText);
    const developerModels = developerModelSlugs(modelsText);
    const added = official.filter(id => !knownFamilies.has(id) && !knownFamilies.has(id.replace(/-\d{4}-\d{2}-\d{2}$/, '')));
    const removed = known.filter(id => !official.includes(id));
    const developerCatalogMissing = openaiComplimentaryConfig.models
      .filter(model => !documentedModelCandidates(model).some(candidate => developerModels.includes(candidate)))
      .map(model => model.id);
    const result = {
      schemaVersion: 1,
      status: added.length || removed.length ? 'drift_detected' : 'current',
      checkedAt,
      catalogAsOf: openaiComplimentaryConfig.catalogAsOf,
      sources: {
        complimentary: openaiComplimentaryConfig.sources.complimentary,
        pricing: openaiComplimentaryConfig.sources.pricing
      },
      sourceHashes: { complimentary: sha256(helpText), models: sha256(modelsText) },
      counts: { tracked: known.length, official: official.length, developerCatalog: developerModels.length },
      added,
      removed,
      developerCatalogMissing,
      officialModels: official,
      note: '변경 후보만 기록합니다. source code와 가격표는 공식 문서를 사람이 검토한 뒤 갱신합니다.'
    };
    atomicJsonWrite(openaiCatalogCheckPath(options), result);
    return { ok: true, ...result };
  } catch (error) {
    const result = {
      schemaVersion: 1,
      status: 'unavailable',
      checkedAt,
      catalogAsOf: openaiComplimentaryConfig.catalogAsOf,
      error: String(error.message || error).slice(0, 300),
      added: [],
      removed: []
    };
    atomicJsonWrite(openaiCatalogCheckPath(options), result);
    return { ok: false, ...result };
  }
}

export function openaiCatalogCheckStatus(options = {}) {
  const file = openaiCatalogCheckPath(options);
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return { status: 'not_checked', checkedAt: null, added: [], removed: [] };
    throw error;
  }
}

if (path.resolve(process.argv[1] || '') === path.resolve(fileURLToPath(import.meta.url))) {
  const result = await checkOpenaiCatalog({ home: os.homedir() });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (!result.ok) process.exitCode = 1;
}
