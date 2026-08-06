#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const label = 'com.agenticlab.aicc-workspace-tunnel';

function xml(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function plistBody({ binary, profileDir, logs, home }) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array>
<string>${xml(binary)}</string><string>run</string><string>--profile-dir</string><string>${xml(profileDir)}</string><string>--profile</string><string>aicc-workspace</string>
</array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>10</integer><key>ProcessType</key><string>Background</string>
<key>StandardOutPath</key><string>${xml(path.join(logs, 'tunnel.log'))}</string>
<key>StandardErrorPath</key><string>${xml(path.join(logs, 'tunnel.error.log'))}</string>
<key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string><key>HOME</key><string>${xml(home)}</string></dict>
</dict></plist>
`;
}

export function installWorkspaceTunnelLaunchAgent(options = {}) {
  if ((options.platform ?? process.platform) !== 'darwin') throw new Error('Workspace Tunnel 자동 시작은 macOS에서만 지원합니다.');
  const home = options.home ?? os.homedir();
  const stateRoot = options.stateRoot ?? process.env.AICC_STATE_ROOT?.trim() ?? path.join(home, '.ai-control-center');
  const root = path.join(stateRoot, 'workspace-mcp');
  const binary = path.join(root, 'bin', 'tunnel-client');
  const profileDir = path.join(root, 'tunnel', 'profiles');
  const key = path.join(root, 'secrets', 'tunnel-runtime.key');
  const logs = path.join(root, 'logs');
  for (const required of [binary, path.join(profileDir, 'aicc-workspace.yaml'), key]) {
    const stat = fs.lstatSync(required);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`실제 일반 파일이 필요합니다: ${required}`);
  }
  if ((fs.statSync(key).mode & 0o077) !== 0) throw new Error('Tunnel runtime key는 소유자 전용(0600)이어야 합니다.');
  fs.mkdirSync(logs, { recursive: true, mode: 0o700 });
  const launchAgents = path.join(home, 'Library', 'LaunchAgents');
  fs.mkdirSync(launchAgents, { recursive: true });
  const plist = path.join(launchAgents, `${label}.plist`);
  const temporary = `${plist}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, plistBody({ binary, profileDir, logs, home }), { encoding: 'utf8', mode: 0o600 });
  const checked = spawnSync('plutil', ['-lint', temporary], { encoding: 'utf8' });
  if (checked.status !== 0) {
    fs.rmSync(temporary, { force: true });
    throw new Error(`launchd 설정 검사가 실패했습니다: ${(checked.stderr || checked.stdout || '').trim()}`);
  }
  fs.renameSync(temporary, plist);
  const domain = `gui/${process.getuid()}`;
  spawnSync('launchctl', ['bootout', `${domain}/${label}`], { stdio: 'ignore' });
  const loaded = spawnSync('launchctl', ['bootstrap', domain, plist], { encoding: 'utf8' });
  if (loaded.status !== 0) throw new Error(`Workspace Tunnel 자동 시작 등록에 실패했습니다: ${(loaded.stderr || '').trim()}`);
  return { ok: true, label, plist };
}

if (path.resolve(process.argv[1] || '') === path.resolve(fileURLToPath(import.meta.url))) {
  try {
    const result = installWorkspaceTunnelLaunchAgent();
    console.log(JSON.stringify(result));
  } catch (error) {
    console.error(`workspace-tunnel-install: ${error.message}`);
    process.exitCode = 1;
  }
}
