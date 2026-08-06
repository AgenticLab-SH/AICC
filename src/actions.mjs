import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { accountStatus } from './adapters/accounts.mjs';
import { ocxStatus } from './adapters/ocx.mjs';
import { ocxAccountStatus } from './adapters/ocx-accounts.mjs';
import { runCommand } from './lib/command.mjs';
import { redactText, sanitize } from './lib/redact.mjs';
import { defaultPythonCommand } from './config.mjs';

const previewLifetimeMs = 2 * 60 * 1000;
const here = path.dirname(fileURLToPath(import.meta.url));
const embeddedAccountManager = path.resolve(here, '../components/account-manager/ops/local/codex_multi.py');
const ocxAccountImporter = path.resolve(here, '../components/account-manager/ops/auth-portal/import_current_to_ocx.py');

export class ActionError extends Error {
  constructor(code, message, status = 400) {
    super(message);
    this.name = 'ActionError';
    this.code = code;
    this.status = status;
  }
}

function stableFingerprint(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

function ensurePrivateDirectory(directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  try { fs.chmodSync(directory, 0o700); } catch { /* best effort on Windows */ }
}

function outputSummary(result) {
  const text = redactText([result.stdout, result.stderr].filter(Boolean).join('\n').trim());
  return text.length > 4_000 ? `${text.slice(0, 4_000)}\n…` : text;
}

function ocxSnapshot(status) {
  return {
    installed: Boolean(status?.installed),
    healthy: Boolean(status?.healthy),
    version: status?.version ?? null,
    port: status?.runtime?.port ?? null
  };
}

function accountSnapshot(status) {
  return {
    state: status?.state ?? null,
    activeAccount: status?.activeAccount ?? null,
    accounts: (status?.accounts ?? []).map(account => ({
      index: account.index ?? null,
      account: account.account ?? null,
      idPrefix: account.id_prefix ?? null,
      expired: Boolean(account.expired)
    }))
  };
}

function ocxAccountSnapshot(status) {
  return {
    state: status?.state ?? null,
    activeId: status?.activeId ?? null,
    accounts: (status?.accounts ?? []).map(account => ({
      id: account.id ?? null,
      label: account.label ?? null,
      email: account.email ?? null,
      plan: account.plan ?? null,
      active: Boolean(account.active),
      paused: Boolean(account.paused),
      needsReauth: Boolean(account.needsReauth)
    }))
  };
}

function resolveOcxAccount(selector, status) {
  const raw = String(selector ?? '').trim();
  if (!raw) throw new ActionError('selector_required', '전환할 OCX 계정을 선택해야 합니다.');
  if (!['ready', 'degraded'].includes(status?.state)) {
    throw new ActionError('ocx_accounts_unavailable', 'OCX 계정 풀을 확인할 수 없습니다.', 409);
  }
  const lower = raw.toLocaleLowerCase();
  const matches = (status.accounts ?? []).filter(account =>
    String(account.id ?? '').toLocaleLowerCase() === lower
    || String(account.label ?? '').toLocaleLowerCase() === lower
    || String(account.email ?? '').toLocaleLowerCase() === lower
  );
  if (matches.length !== 1) {
    throw new ActionError(
      matches.length > 1 ? 'selector_ambiguous' : 'account_not_found',
      matches.length > 1 ? '여러 OCX 계정이 같은 선택자와 일치합니다.' : '선택한 OCX 계정을 찾지 못했습니다.'
    );
  }
  const target = matches[0];
  if (target.needsReauth) throw new ActionError('account_needs_reauth', '재인증이 필요한 OCX 계정은 선택할 수 없습니다.', 409);
  if (target.paused) throw new ActionError('account_paused', '일시 정지된 OCX 계정은 먼저 해제해야 합니다.', 409);
  if (target.id === status.activeId) throw new ActionError('already_active', '이미 이 OCX 계정이 선택되어 있습니다.', 409);
  return target;
}

function resolveAccount(selector, status) {
  const raw = String(selector ?? '').trim();
  if (!raw) throw new ActionError('selector_required', '전환할 계정을 선택해야 합니다.');
  if (status?.state !== 'ready') {
    throw new ActionError('accounts_unavailable', '계정 상태를 확인할 수 없어 전환을 준비하지 않았습니다.', 409);
  }

  const lower = raw.toLowerCase();
  const matches = (status.accounts ?? []).filter(account => {
    if (String(account.index ?? '') === raw) return true;
    if (String(account.account ?? '').toLowerCase() === lower) return true;
    return String(account.id_prefix ?? '').toLowerCase() === lower;
  });
  if (matches.length !== 1) {
    throw new ActionError(
      matches.length > 1 ? 'selector_ambiguous' : 'account_not_found',
      matches.length > 1 ? '여러 계정이 같은 선택자와 일치합니다.' : '선택한 계정을 찾지 못했습니다.'
    );
  }
  const target = matches[0];
  if (target.expired) throw new ActionError('account_expired', '만료된 계정은 갱신한 뒤 전환할 수 있습니다.', 409);
  if (target.account === status.activeAccount) {
    throw new ActionError('already_active', '이미 이 계정이 기본 GPT Desktop에서 사용 중입니다.', 409);
  }
  return target;
}

function defaultAccountSwitchCommand(selector) {
  const python = process.env.AICC_PYTHON
    ? { executable: process.env.AICC_PYTHON.trim(), args: [] }
    : defaultPythonCommand();
  return {
    executable: python.executable,
    args: [...python.args, embeddedAccountManager, 'switch', selector]
  };
}

function defaultOcxImportCommand() {
  const python = process.env.AICC_PYTHON
    ? { executable: process.env.AICC_PYTHON.trim(), args: [] }
    : defaultPythonCommand();
  return { executable: python.executable, args: [...python.args, ocxAccountImporter] };
}

function buildDefinitions(options) {
  const ocxExecutable = options.ocxExecutable || process.env.AICC_OCX_EXECUTABLE?.trim() || 'ocx';
  const inheritedEnvironment = options.env ?? process.env;
  const appCodexHome = options.appCodexHome
    ?? inheritedEnvironment.CM_APP_CODEX_HOME?.trim()
    ?? path.join(os.homedir(), '.codex');
  const ocxEnvironment = {
    ...inheritedEnvironment,
    CM_APP_CODEX_HOME: appCodexHome,
    CODEX_HOME: appCodexHome
  };
  delete ocxEnvironment.CODEX_SQLITE_HOME;
  delete ocxEnvironment.CODEX_ELECTRON_USER_DATA_PATH;
  delete ocxEnvironment.CODEX_MULTI_ACCOUNT_NAME;
  const ocxCommand = args => ({ executable: ocxExecutable, args, env: ocxEnvironment });
  const accountSwitchCommand = options.accountSwitchCommand ?? defaultAccountSwitchCommand;
  return {
    'ocx.start': {
      title: 'OCX 시작',
      kind: 'provider',
      verifyAttempts: 12,
      verifyDelayMs: 250,
      readState: options.getOcxStatus,
      snapshot: ocxSnapshot,
      prepare(_args, state) {
        if (!state.installed) throw new ActionError('ocx_unavailable', 'OCX 실행 파일을 찾지 못했습니다.', 409);
        if (state.healthy) throw new ActionError('already_running', 'OCX가 이미 실행 중입니다.', 409);
        return {};
      },
      describe: () => ({
        impact: 'OCX를 로그인 시 자동 시작 서비스로 설치하고 GPT 모델 요청 경로를 OCX로 연결합니다.',
        warnings: ['시작 과정에서 GPT 모델 목록과 로컬 연결 설정이 갱신됩니다.', 'OCX 서비스는 충돌을 피하기 위해 기본 App home을 명시적으로 사용합니다.'],
        rollback: '시작 확인에 실패하면 OCX service stop으로 서비스를 멈추고 기본 GPT 경로 복구를 시도합니다.'
      }),
      command: () => ocxCommand(['service']),
      verify: (state, _args, _before, result) => Boolean(result.ok && state.healthy),
      rollback: (_before, after) => after.healthy ? ocxCommand(['service', 'stop']) : null
    },
    'ocx.sync': {
      title: 'OCX 모델 동기화',
      kind: 'provider',
      readState: options.getOcxStatus,
      snapshot: ocxSnapshot,
      prepare(_args, state) {
        if (!state.installed) throw new ActionError('ocx_unavailable', 'OCX 실행 파일을 찾지 못했습니다.', 409);
        return {};
      },
      describe: () => ({
        impact: 'OCX가 제공하는 모델 목록을 GPT 로컬 설정과 다시 맞춥니다.',
        warnings: ['OCX와 GPT의 모델 목록 파일이 갱신될 수 있습니다.'],
        rollback: 'OCX 자체의 검증된 동기화와 백업 동작에 맡기며 AICC가 파일을 직접 쓰지 않습니다.'
      }),
      command: () => ocxCommand(['sync']),
      verify: (state, _args, _before, result) => Boolean(result.ok && state.installed)
    },
    'ocx.stop': {
      title: 'OCX 중지',
      kind: 'provider',
      readState: options.getOcxStatus,
      snapshot: ocxSnapshot,
      prepare(_args, state) {
        if (!state.installed) throw new ActionError('ocx_unavailable', 'OCX 실행 파일을 찾지 못했습니다.', 409);
        if (!state.healthy) throw new ActionError('already_stopped', 'OCX가 이미 중지되어 있습니다.', 409);
        return {};
      },
      describe: () => ({
        impact: 'OCX를 중지하고 기본 GPT 연결 경로를 복구합니다.',
        warnings: ['OCX를 통과하던 요청은 중단되며 OCX 전용 모델을 사용할 수 없게 됩니다.'],
        rollback: '다시 연결하려면 새 미리보기 후 OCX 시작을 실행합니다.'
      }),
      command: () => ocxCommand(['service', 'stop']),
      verify: (state, _args, _before, result) => Boolean(result.ok && !state.healthy)
    },
    'account.switch': {
      title: '기본 GPT 계정 전환',
      kind: 'account',
      readState: options.getAccountStatus,
      snapshot: accountSnapshot,
      prepare(args, state) {
        const target = resolveAccount(args?.selector, state);
        return { selector: target.account, targetIndex: target.index ?? null };
      },
      describe: args => ({
        impact: `기본 GPT Desktop을 닫고 ${args.selector} 계정으로 인증을 바꾼 뒤 다시 실행합니다.`,
        warnings: ['기본 GPT Desktop이 재시작됩니다.', '계정별로 따로 실행한 GPT Desktop 창은 건드리지 않습니다.'],
        rollback: '전환 또는 재실행이 실패하면 포함된 Account Manager가 기존 인증을 복구합니다. 사후 확인이 다르면 AICC도 이전 계정 복귀를 시도합니다.'
      }),
      command: args => accountSwitchCommand(args.selector),
      verify: (state, args, _before, result) => Boolean(result.ok && state.activeAccount === args.selector),
      rollback: (before, after) => {
        const previous = before.activeAccount;
        if (!previous || after.activeAccount === previous) return null;
        return accountSwitchCommand(previous);
      }
    },
    'ocx.account.use': {
      title: 'OCX 라우팅 계정 전환',
      kind: 'account',
      readState: options.getOcxAccountStatus,
      snapshot: ocxAccountSnapshot,
      prepare(args, state) {
        const target = resolveOcxAccount(args?.selector, state);
        return { selector: target.id, label: target.label, email: target.email, plan: target.plan };
      },
      describe: args => ({
        impact: `${args.label || args.email || args.selector} 계정을 새 OCX 작업의 기본 라우팅 계정으로 선택합니다.`,
        warnings: ['이미 실행 중인 작업은 시작할 때 선택된 계정을 계속 사용합니다.', '토큰이나 로그인 파일은 복사하지 않습니다.'],
        rollback: '검증에 실패하면 미리보기 전의 OCX 활성 계정으로 되돌립니다.'
      }),
      command: args => ocxCommand(['account', 'use', 'openai', args.selector]),
      verify: (state, args, _before, result) => Boolean(result.ok && state.activeId === args.selector),
      rollback: before => before.activeId
        ? ocxCommand(['account', 'use', 'openai', before.activeId])
        : null
    },
    'ocx.account.import-cm': {
      title: '지정 계정 OAuth를 OCX에 적용',
      kind: 'account',
      timeoutMs: 4 * 60 * 1000,
      readState: options.getOcxAccountStatus,
      snapshot: ocxAccountSnapshot,
      prepare(_args, state) {
        if (!['ready', 'degraded'].includes(state?.state)) {
          throw new ActionError('ocx_accounts_unavailable', 'OCX 계정 풀을 확인할 수 없습니다.', 409);
        }
        return {};
      },
      describe: () => ({
        impact: 'AICC에 지정된 cm OAuth를 명시된 OCX 슬롯에 추가하거나 최신 버전으로 교체한 뒤 정상 백그라운드 서비스로 복귀합니다.',
        warnings: ['현재 OCX 연결이 잠깐 끊기므로 진행 중인 모델 응답이 없을 때 실행하세요.', '기존 슬롯 갱신은 이메일과 ChatGPT 계정 ID가 모두 일치할 때만 허용됩니다.', 'import gate는 일회성 프로세스에만 켜지며 서비스 설정에는 저장하지 않습니다.'],
        rollback: '실패 시 native API로 기존 자격증명을 되살리고, 필요하면 보존한 OCX 파일 스냅샷을 복원한 뒤 원래 활성 계정과 gate 없는 서비스를 복구합니다.'
      }),
      command: options.ocxImportCommand ?? defaultOcxImportCommand,
      verify: (state, _args, before, result) => Boolean(
        result.ok
        && state.activeId === before.activeId
        && [before.accounts.length, before.accounts.length + 1].includes(state.accounts.length)
        && !state.accounts.some(account => account.needsReauth)
      )
    }
  };
}

export function createActionController(options = {}) {
  const stateRoot = options.stateRoot
    ?? process.env.AICC_STATE_ROOT?.trim()
    ?? path.join(os.homedir(), '.ai-control-center');
  const previewsRoot = path.join(stateRoot, 'previews');
  const lockPath = path.join(stateRoot, 'action.lock');
  const now = options.now ?? (() => Date.now());
  const runner = options.runCommand ?? runCommand;
  const definitions = buildDefinitions({
    ...options,
    platform: options.platform ?? process.platform,
    arch: options.arch ?? process.arch,
    getOcxStatus: options.getOcxStatus ?? (() => ocxStatus(options.ocx)),
    getAccountStatus: options.getAccountStatus ?? (() => accountStatus(options.accounts)),
    getOcxAccountStatus: options.getOcxAccountStatus ?? (() => ocxAccountStatus(options.ocxAccounts))
  });

  function list() {
    return Object.entries(definitions).map(([name, definition]) => ({
      name,
      title: definition.title,
      kind: definition.kind
    }));
  }

  function previewPath(token) {
    if (!/^[A-Za-z0-9_-]{40,100}$/.test(token)) {
      throw new ActionError('invalid_confirmation', '확인 토큰 형식이 올바르지 않습니다.');
    }
    return path.join(previewsRoot, `${stableFingerprint(token)}.json`);
  }

  function cleanupExpiredPreviews() {
    let entries = [];
    try { entries = fs.readdirSync(previewsRoot, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
      const candidate = path.join(previewsRoot, entry.name);
      try {
        const record = JSON.parse(fs.readFileSync(candidate, 'utf8'));
        if (!Number.isFinite(record.expiresAt) || record.expiresAt <= now()) fs.unlinkSync(candidate);
      } catch { /* leave unknown files untouched */ }
    }
  }

  async function preview(name, args = {}) {
    const definition = definitions[name];
    if (!definition) throw new ActionError('action_not_allowed', '허용되지 않은 작업입니다.', 404);
    const state = await definition.readState();
    const canonicalArgs = definition.prepare(args, state);
    const snapshot = definition.snapshot(state);
    const token = crypto.randomBytes(32).toString('base64url');
    const expiresAt = now() + (options.previewLifetimeMs ?? previewLifetimeMs);
    const record = {
      schemaVersion: 1,
      action: name,
      args: canonicalArgs,
      before: snapshot,
      fingerprint: stableFingerprint({ action: name, args: canonicalArgs, state: snapshot }),
      createdAt: now(),
      expiresAt
    };
    ensurePrivateDirectory(previewsRoot);
    cleanupExpiredPreviews();
    fs.writeFileSync(previewPath(token), `${JSON.stringify(record)}\n`, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    return sanitize({
      ok: true,
      action: name,
      title: definition.title,
      args: canonicalArgs,
      current: snapshot,
      ...definition.describe(canonicalArgs, snapshot),
      confirmationToken: token,
      expiresAt: new Date(expiresAt).toISOString()
    });
  }

  function acquireLock(action) {
    ensurePrivateDirectory(stateRoot);
    try {
      const descriptor = fs.openSync(lockPath, 'wx', 0o600);
      fs.writeFileSync(descriptor, `${JSON.stringify({ pid: process.pid, action, startedAt: new Date(now()).toISOString() })}\n`);
      fs.closeSync(descriptor);
    } catch (error) {
      if (error.code === 'EEXIST') {
        throw new ActionError('action_busy', '다른 변경 작업이 진행 중입니다. 끝난 뒤 다시 시도하세요.', 409);
      }
      throw error;
    }
    return () => {
      try { fs.unlinkSync(lockPath); } catch { /* lock recovery is documented */ }
    };
  }

  async function execute(confirmationToken) {
    const token = String(confirmationToken ?? '').trim();
    const file = previewPath(token);
    let record;
    try { record = JSON.parse(fs.readFileSync(file, 'utf8')); }
    catch (error) {
      if (error.code === 'ENOENT') throw new ActionError('confirmation_not_found', '확인 토큰이 없거나 이미 사용되었습니다.', 404);
      throw new ActionError('invalid_confirmation', '확인 기록을 읽을 수 없습니다. 새로 미리보세요.');
    }
    if (record.expiresAt <= now()) {
      try { fs.unlinkSync(file); } catch { /* no-op */ }
      throw new ActionError('confirmation_expired', '확인 시간이 지났습니다. 새로 미리보세요.', 409);
    }
    const definition = definitions[record.action];
    if (!definition) throw new ActionError('action_not_allowed', '허용되지 않은 작업입니다.', 404);

    const release = acquireLock(record.action);
    try {
      fs.unlinkSync(file);
      const beforeState = await definition.readState();
      const before = definition.snapshot(beforeState);
      const fingerprint = stableFingerprint({ action: record.action, args: record.args, state: before });
      if (fingerprint !== record.fingerprint) {
        throw new ActionError('stale_preview', '현재 상태가 미리보기 이후 달라졌습니다. 다시 미리보세요.', 409);
      }

      const command = definition.command(record.args, before);
      const commandResult = await runner(command.executable, command.args, {
        timeoutMs: definition.timeoutMs ?? options.timeoutMs ?? 120_000,
        maxBytes: 256_000,
        cwd: command.cwd,
        env: command.env
      });
      let afterState = await definition.readState();
      let after = definition.snapshot(afterState);
      let verified = definition.verify(after, record.args, before, commandResult);
      const verifyAttempts = commandResult.ok ? (definition.verifyAttempts ?? 1) : 1;
      for (let attempt = 1; !verified && attempt < verifyAttempts; attempt += 1) {
        const delayMs = options.verifyDelayMs ?? definition.verifyDelayMs ?? 0;
        if (delayMs > 0) await new Promise(resolve => setTimeout(resolve, delayMs));
        afterState = await definition.readState();
        after = definition.snapshot(afterState);
        verified = definition.verify(after, record.args, before, commandResult);
      }
      let rollback = { attempted: false, restored: false };

      if (!verified && definition.rollback) {
        const rollbackCommand = definition.rollback(before, after, record.args);
        if (rollbackCommand) {
          const rollbackResult = await runner(rollbackCommand.executable, rollbackCommand.args, {
            timeoutMs: definition.timeoutMs ?? options.timeoutMs ?? 120_000,
            maxBytes: 256_000,
            cwd: rollbackCommand.cwd,
            env: rollbackCommand.env
          });
          const restoredState = definition.snapshot(await definition.readState());
          rollback = {
            attempted: true,
            commandOk: rollbackResult.ok,
            restored: stableFingerprint(restoredState) === stableFingerprint(before),
            state: restoredState
          };
        } else {
          rollback.restored = stableFingerprint(after) === stableFingerprint(before);
        }
      }

      return sanitize({
        ok: verified,
        action: record.action,
        title: definition.title,
        args: record.args,
        verified,
        command: {
          ok: commandResult.ok,
          exitCode: commandResult.exitCode,
          timedOut: commandResult.timedOut,
          durationMs: commandResult.durationMs,
          output: outputSummary(commandResult)
        },
        before,
        after,
        rollback,
        message: verified ? '작업을 실행하고 결과를 확인했습니다.' : '요청한 상태를 확인하지 못해 가능한 복구를 시도했습니다.'
      });
    } finally {
      release();
    }
  }

  return { list, preview, execute, stateRoot, lockPath };
}
