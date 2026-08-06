import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { workspaceToolSnapshot } from '../components/workspace-mcp/tool-manifest.mjs';

export const CHATGPT_APP_MANAGE_URL = 'https://chatgpt.com/admin/apps';

export function workspacePublishStatePath(options = {}) {
  const stateRoot = options.stateRoot
    ?? process.env.AICC_STATE_ROOT?.trim()
    ?? path.join(os.homedir(), '.ai-control-center');
  return path.join(stateRoot, 'workspace-mcp', 'publish-state.json');
}

function readState(file) {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    return parsed?.schemaVersion === 1 ? parsed : null;
  } catch { return null; }
}

export function workspacePublicationStatus(options = {}) {
  const manifest = workspaceToolSnapshot();
  const stateFile = workspacePublishStatePath(options);
  const published = readState(stateFile);
  return {
    manifest,
    published: published ? {
      appName: published.appName ?? null,
      toolCount: Number(published.toolCount ?? 0),
      manifestHash: published.manifestHash ?? null,
      verifiedAt: published.verifiedAt ?? null
    } : null,
    needsPublish: !published || published.manifestHash !== manifest.hash,
    manageUrl: CHATGPT_APP_MANAGE_URL,
    stateFile
  };
}

export function recordWorkspacePublication(options = {}) {
  const appName = String(options.appName ?? '').trim();
  if (!appName) throw new Error('검증된 ChatGPT 앱 이름이 필요합니다.');
  const status = workspacePublicationStatus(options);
  const file = status.stateFile;
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const payload = {
    schemaVersion: 1,
    appName,
    toolCount: status.manifest.toolCount,
    manifestHash: status.manifest.hash,
    verifiedAt: new Date().toISOString()
  };
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(temporary, file);
  if (process.platform !== 'win32') fs.chmodSync(file, 0o600);
  return workspacePublicationStatus(options);
}
