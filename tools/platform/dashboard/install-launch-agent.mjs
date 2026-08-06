#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const label = 'com.agenticlab.aicc-dashboard';

function blockingPause(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
}

function launchdMessage(result) {
  return (result?.stderr || result?.stdout || '').trim();
}

function isTransientBootstrapFailure(result) {
  return result?.status === 5 || /Bootstrap failed:\s*5|Input\/output error/i.test(launchdMessage(result));
}

function xml(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function plistBody({ node, root, home, logs, port }) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array><string>${xml(node)}</string><string>${xml(path.join(root, 'src', 'server.mjs'))}</string></array>
<key>WorkingDirectory</key><string>${xml(root)}</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>10</integer><key>ProcessType</key><string>Background</string>
<key>StandardOutPath</key><string>${xml(path.join(logs, 'dashboard.log'))}</string>
<key>StandardErrorPath</key><string>${xml(path.join(logs, 'dashboard.error.log'))}</string>
<key>EnvironmentVariables</key><dict>
<key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
<key>HOME</key><string>${xml(home)}</string><key>AICC_HOST</key><string>127.0.0.1</string>
<key>AICC_PORT</key><string>${xml(port)}</string>
</dict></dict></plist>
`;
}

export function installDashboardLaunchAgent(options = {}) {
  if ((options.platform ?? process.platform) !== 'darwin') throw new Error('AICC Dashboard 자동 시작은 macOS에서만 지원합니다.');
  const home = options.home ?? os.homedir();
  const root = options.root ?? path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
  const node = options.node ?? process.execPath;
  const port = String(options.port ?? process.env.AICC_PORT ?? '4381');
  const spawn = options.spawnSync ?? spawnSync;
  const pause = options.pause ?? blockingPause;
  const bootstrapAttempts = Math.max(1, Number(options.bootstrapAttempts ?? 6));
  const uid = options.uid ?? (typeof process.getuid === 'function' ? process.getuid() : null);
  if (!Number.isInteger(uid) || uid < 0) throw new Error('macOS 사용자 UID를 확인할 수 없습니다.');
  for (const required of [node, path.join(root, 'src', 'server.mjs'), path.join(root, 'package.json')]) {
    const stat = fs.lstatSync(required);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`실제 일반 파일이 필요합니다: ${required}`);
  }
  if (!/^\d{2,5}$/.test(port) || Number(port) < 1024 || Number(port) > 65535) throw new Error(`올바르지 않은 Dashboard port: ${port}`);
  const logs = path.join(home, '.ai-control-center', 'logs');
  fs.mkdirSync(logs, { recursive: true, mode: 0o700 });
  const launchAgents = path.join(home, 'Library', 'LaunchAgents');
  fs.mkdirSync(launchAgents, { recursive: true });
  const plist = path.join(launchAgents, `${label}.plist`);
  const temporary = `${plist}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, plistBody({ node, root, home, logs, port }), { encoding: 'utf8', mode: 0o600 });
  const checked = spawn('plutil', ['-lint', temporary], { encoding: 'utf8' });
  if (checked.status !== 0) {
    fs.rmSync(temporary, { force: true });
    throw new Error(`launchd 설정 검사가 실패했습니다: ${(checked.stderr || checked.stdout || '').trim()}`);
  }
  fs.renameSync(temporary, plist);
  const domain = `gui/${uid}`;
  spawn('launchctl', ['bootout', `${domain}/${label}`], { stdio: 'ignore' });
  let loaded = null;
  let attempt = 0;
  for (; attempt < bootstrapAttempts; attempt += 1) {
    if (attempt > 0) pause(Math.min(1_000, 150 * (2 ** (attempt - 1))));
    loaded = spawn('launchctl', ['bootstrap', domain, plist], { encoding: 'utf8' });
    if (loaded.status === 0) break;
    const alreadyRegistered = spawn('launchctl', ['print', `${domain}/${label}`], { stdio: 'ignore' });
    if (alreadyRegistered.status === 0) break;
    if (!isTransientBootstrapFailure(loaded)) break;
  }
  if (loaded?.status !== 0) {
    const registered = spawn('launchctl', ['print', `${domain}/${label}`], { stdio: 'ignore' });
    if (registered.status !== 0) throw new Error(`AICC Dashboard 자동 시작 등록에 실패했습니다: ${launchdMessage(loaded)}`);
  }
  return { ok: true, label, plist, port: Number(port), bootstrapAttempts: attempt + 1 };
}

if (path.resolve(process.argv[1] || '') === path.resolve(fileURLToPath(import.meta.url))) {
  try {
    console.log(JSON.stringify(installDashboardLaunchAgent()));
  } catch (error) {
    console.error(`aicc-dashboard-install: ${error.message}`);
    process.exitCode = 1;
  }
}
