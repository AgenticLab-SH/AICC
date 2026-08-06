import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { envCommand, runCommand } from '../lib/command.mjs';
import { sanitize } from '../lib/redact.mjs';
import { defaultPythonCommand } from '../config.mjs';

function defaultCommand() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const embeddedScript = path.resolve(here, '../../components/account-manager/ops/local/codex_multi.py');
  if (fs.existsSync(embeddedScript)) {
    const python = process.env.AICC_PYTHON
      ? { executable: process.env.AICC_PYTHON, args: [] }
      : defaultPythonCommand();
    return { executable: python.executable, args: [...python.args, embeddedScript, 'status', '--json'] };
  }
  return { executable: 'cm', args: ['status', '--json'] };
}

function storedAccountCount() {
  const directory = path.join(os.homedir(), '.codex-multi', 'accounts');
  try {
    return fs.readdirSync(directory, { withFileTypes: true })
      .filter(entry => entry.isFile() && entry.name.endsWith('.json')).length;
  } catch {
    return null;
  }
}

export async function accountStatus(options = {}) {
  const spec = options.command ?? envCommand('AICC_CM_STATUS', defaultCommand());
  const result = await (options.runCommand ?? runCommand)(spec.executable, spec.args, {
    timeoutMs: options.timeoutMs ?? 25_000
  });

  if (!result.ok) {
    return {
      id: 'accounts',
      label: 'GPT 계정',
      state: result.timedOut ? 'degraded' : 'unavailable',
      detail: result.timedOut ? '계정 상태 조회 시간이 초과되었습니다.' : '계정 상태 JSON을 읽지 못했습니다.',
      accountCount: storedAccountCount(),
      source: spec.executable,
      error: result.error || `exit ${result.exitCode ?? 'unknown'}`
    };
  }

  try {
    const payload = sanitize(JSON.parse(result.stdout));
    return {
      id: 'accounts',
      label: 'GPT 계정',
      state: payload.ok === false ? 'degraded' : 'ready',
      detail: `${payload.account_count ?? payload.accounts?.length ?? 0}개 계정 조회`,
      accountCount: payload.account_count ?? payload.accounts?.length ?? 0,
      activeAccount: payload.active_account ?? null,
      accounts: payload.accounts ?? [],
      schemaVersion: payload.schema_version ?? null,
      source: spec.executable
    };
  } catch {
    return {
      id: 'accounts',
      label: 'GPT 계정',
      state: 'degraded',
      detail: '계정 명령이 JSON이 아닌 출력을 반환했습니다.',
      accountCount: storedAccountCount(),
      source: spec.executable,
      error: 'invalid JSON response'
    };
  }
}
