import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const guidanceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function guidanceCommands(action, root = guidanceRoot) {
  const common = ['-NoProfile', '-File'];
  if (action === 'deploy') {
    return [
      { executable: 'pwsh', args: [...common, path.join(root, 'tools/platform/core/deploy_directives.ps1'), '-AiccRoot', root, '-AsJson'] },
      { executable: 'pwsh', args: [...common, path.join(root, 'tools/platform/core/deploy_active_skills.ps1'), '-AiccRoot', root, '-PruneManaged', '-AsJson'] }
    ];
  }
  if (action === 'plan') {
    return [
      { executable: 'pwsh', args: [...common, path.join(root, 'tools/platform/core/deploy_directives.ps1'), '-AiccRoot', root, '-Plan', '-AsJson'] },
      { executable: 'pwsh', args: [...common, path.join(root, 'tools/platform/core/deploy_active_skills.ps1'), '-AiccRoot', root, '-PruneManaged', '-Plan', '-AsJson'] }
    ];
  }
  if (action === 'check') {
    return [{ executable: 'pwsh', args: [...common, path.join(root, 'tools/platform/test/Test-AiccGuidance.ps1'), '-AiccRoot', root, '-AsJson'] }];
  }
  throw new Error(`알 수 없는 guidance 명령: ${action}`);
}

export function runGuidance(action, options = {}) {
  const runner = options.spawnSync ?? spawnSync;
  const commands = guidanceCommands(action, options.root ?? guidanceRoot);
  for (const command of commands) {
    const result = runner(command.executable, command.args, {
      cwd: options.root ?? guidanceRoot,
      env: options.env ?? process.env,
      stdio: options.stdio ?? 'inherit',
      windowsHide: true
    });
    if (result.error) {
      if (result.error.code === 'ENOENT') throw new Error('PowerShell 7(pwsh)이 필요합니다.');
      throw result.error;
    }
    if (result.status !== 0) throw new Error(`guidance ${action} 실패(exit ${result.status ?? 'unknown'})`);
  }
  return { ok: true, action, commandCount: commands.length };
}
