import { runCommand } from '../lib/command.mjs';

function safeAccount(account = {}) {
  return {
    id: typeof account.id === 'string' ? account.id : null,
    label: typeof account.label === 'string' ? account.label : null,
    email: typeof account.email === 'string' ? account.email : null,
    plan: typeof account.plan === 'string' ? account.plan : null,
    active: Boolean(account.active),
    paused: Boolean(account.paused),
    needsReauth: Boolean(account.needsReauth)
  };
}
export async function ocxAccountStatus(options = {}) {
  const executable = options.executable || process.env.AICC_OCX_EXECUTABLE?.trim() || 'ocx';
  const runner = options.runCommand ?? runCommand;
  const result = await runner(executable, ['account', 'list', 'openai', '--json'], {
    timeoutMs: options.timeoutMs ?? 25_000
  });
  if (!result.ok) {
    return {
      id: 'ocx-accounts',
      label: 'OCX 계정 풀',
      state: result.timedOut ? 'degraded' : 'unavailable',
      detail: result.timedOut ? 'OCX 계정 조회 시간이 초과되었습니다.' : 'OCX 계정 풀을 읽지 못했습니다.',
      accounts: [],
      error: result.error || `exit ${result.exitCode ?? 'unknown'}`
    };
  }
  try {
    const payload = JSON.parse(result.stdout);
    const accounts = Array.isArray(payload.accounts) ? payload.accounts.map(safeAccount) : [];
    return {
      id: 'ocx-accounts',
      label: 'OCX 계정 풀',
      state: accounts.some(account => account.needsReauth) ? 'degraded' : 'ready',
      detail: `${accounts.length}개 라우팅 계정 조회`,
      accountCount: accounts.length,
      activeId: accounts.find(account => account.active)?.id ?? null,
      accounts
    };
  } catch {
    return {
      id: 'ocx-accounts',
      label: 'OCX 계정 풀',
      state: 'degraded',
      detail: 'OCX가 JSON이 아닌 계정 상태를 반환했습니다.',
      accounts: [],
      error: 'invalid JSON response'
    };
  }
}
