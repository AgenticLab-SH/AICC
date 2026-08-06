import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { ActionError, createActionController } from '../src/actions.mjs';

function temporaryState(t) {
  const stateRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-actions-'));
  t.after(() => fs.rmSync(stateRoot, { recursive: true, force: true }));
  return stateRoot;
}

function commandResult(overrides = {}) {
  return {
    ok: true,
    stdout: '',
    stderr: '',
    exitCode: 0,
    timedOut: false,
    durationMs: 3,
    ...overrides
  };
}

test('allowlist exposes only named actions', () => {
  const controller = createActionController({
    platform: 'darwin',
    arch: 'arm64',
    getOcxStatus: async () => ({}),
    getAccountStatus: async () => ({})
  });
  assert.deepEqual(controller.list().map(item => item.name), [
    'ocx.start',
    'ocx.sync',
    'ocx.stop',
    'account.switch',
    'ocx.account.use',
    'ocx.account.import-cm',
    'openai.provider.set',
    'openai.model.set',
    'openai.default-model.set',
    'openai.model.probe'
  ]);
});

test('OpenAI provider policy changes use preview, verification, and the private state root', async t => {
  const stateRoot = temporaryState(t);
  const provider = {
    enabled: true,
    defaultModel: 'gpt-5.6-luna',
    models: [
      { id: 'gpt-5.6-luna', lifecycle: 'current', callEnabled: true, agentSelectable: true, availability: { status: 'untested', checkedAt: null } },
      { id: 'gpt-5.6-terra', lifecycle: 'current', callEnabled: true, agentSelectable: true, availability: { status: 'untested', checkedAt: null } }
    ]
  };
  const calls = [];
  const controller = createActionController({
    stateRoot,
    getOcxStatus: async () => ({}),
    getAccountStatus: async () => ({}),
    getOpenaiProviderStatus: async () => provider,
    runCommand: async (_executable, args, options) => {
      calls.push({ args, stateRoot: options.env.AICC_STATE_ROOT });
      if (args.includes('provider')) provider.enabled = args.at(-1) === 'true';
      if (args.includes('default-model')) provider.defaultModel = args.at(-1);
      return commandResult();
    }
  });
  const disable = await controller.preview('openai.provider.set', { enabled: false });
  assert.equal((await controller.execute(disable.confirmationToken)).ok, true);
  assert.equal(provider.enabled, false);
  const defaultPreview = await controller.preview('openai.default-model.set', { model: 'gpt-5.6-terra' });
  assert.equal((await controller.execute(defaultPreview.confirmationToken)).ok, true);
  assert.equal(provider.defaultModel, 'gpt-5.6-terra');
  assert.ok(calls.every(call => call.stateRoot === stateRoot));
});

test('preview token is stored by hash and can execute only once', async t => {
  const stateRoot = temporaryState(t);
  let healthy = false;
  const calls = [];
  const controller = createActionController({
    stateRoot,
    ocxExecutable: 'ocx-fixture',
    getOcxStatus: async () => ({ installed: true, healthy, version: '2.7.42', runtime: { port: 10100 } }),
    getAccountStatus: async () => ({}),
    runCommand: async (executable, args) => {
      calls.push([executable, args]);
      healthy = true;
      return commandResult({ stdout: 'started' });
    }
  });

  const preview = await controller.preview('ocx.start');
  const records = fs.readdirSync(path.join(stateRoot, 'previews'));
  assert.equal(records.length, 1);
  assert.equal(records[0].includes(preview.confirmationToken), false);

  const result = await controller.execute(preview.confirmationToken);
  assert.equal(result.ok, true);
  assert.deepEqual(calls, [['ocx-fixture', ['service']]]);
  await assert.rejects(
    controller.execute(preview.confirmationToken),
    error => error instanceof ActionError && error.code === 'confirmation_not_found'
  );
});

test('OCX actions target the default App home instead of an inherited isolated home', async t => {
  const stateRoot = temporaryState(t);
  let healthy = false;
  let commandOptions;
  const controller = createActionController({
    stateRoot,
    appCodexHome: '/safe/app-home',
    env: {
      CODEX_HOME: '/unsafe/isolated-home',
      CODEX_SQLITE_HOME: '/unsafe/sqlite-home',
      CODEX_MULTI_ACCOUNT_NAME: 'isolated@example.invalid'
    },
    ocxExecutable: 'ocx-fixture',
    getOcxStatus: async () => ({ installed: true, healthy, version: '2.8.0', runtime: { port: 10100 } }),
    getAccountStatus: async () => ({}),
    runCommand: async (_executable, _args, options) => {
      commandOptions = options;
      healthy = true;
      return commandResult();
    }
  });

  const preview = await controller.preview('ocx.start');
  const result = await controller.execute(preview.confirmationToken);

  assert.equal(result.ok, true);
  assert.equal(commandOptions.env.CODEX_HOME, '/safe/app-home');
  assert.equal(commandOptions.env.CM_APP_CODEX_HOME, '/safe/app-home');
  assert.equal('CODEX_SQLITE_HOME' in commandOptions.env, false);
  assert.equal('CODEX_MULTI_ACCOUNT_NAME' in commandOptions.env, false);
});

test('OCX service start waits for launchd health before declaring failure', async t => {
  const stateRoot = temporaryState(t);
  let commandRan = false;
  let postCommandReads = 0;
  const controller = createActionController({
    stateRoot,
    verifyDelayMs: 0,
    ocxExecutable: 'ocx-fixture',
    getOcxStatus: async () => {
      const healthy = commandRan && ++postCommandReads >= 2;
      return { installed: true, healthy, version: '2.8.0', runtime: healthy ? { port: 10100 } : null };
    },
    getAccountStatus: async () => ({}),
    runCommand: async () => {
      commandRan = true;
      return commandResult();
    }
  });

  const preview = await controller.preview('ocx.start');
  const result = await controller.execute(preview.confirmationToken);

  assert.equal(result.ok, true);
  assert.equal(result.after.healthy, true);
  assert.equal(postCommandReads, 2);
});

test('execution refuses a stale preview before running a command', async t => {
  const stateRoot = temporaryState(t);
  let version = '2.7.42';
  let calls = 0;
  const controller = createActionController({
    stateRoot,
    getOcxStatus: async () => ({ installed: true, healthy: false, version, runtime: null }),
    getAccountStatus: async () => ({}),
    runCommand: async () => { calls += 1; return commandResult(); }
  });
  const preview = await controller.preview('ocx.start');
  version = '2.7.43';
  await assert.rejects(
    controller.execute(preview.confirmationToken),
    error => error instanceof ActionError && error.code === 'stale_preview'
  );
  assert.equal(calls, 0);
});

test('expired confirmation cannot execute a command', async t => {
  const stateRoot = temporaryState(t);
  let clock = 1_000;
  let calls = 0;
  const controller = createActionController({
    stateRoot,
    now: () => clock,
    previewLifetimeMs: 100,
    getOcxStatus: async () => ({ installed: true, healthy: false, version: '2.7.42', runtime: null }),
    getAccountStatus: async () => ({}),
    runCommand: async () => { calls += 1; return commandResult(); }
  });
  const preview = await controller.preview('ocx.start');
  clock = 1_101;
  await assert.rejects(
    controller.execute(preview.confirmationToken),
    error => error instanceof ActionError && error.code === 'confirmation_expired'
  );
  assert.equal(calls, 0);
});

test('one-writer lock preserves an unused preview while busy', async t => {
  const stateRoot = temporaryState(t);
  const controller = createActionController({
    stateRoot,
    getOcxStatus: async () => ({ installed: true, healthy: false, version: '2.7.42', runtime: null }),
    getAccountStatus: async () => ({}),
    runCommand: async () => commandResult()
  });
  const preview = await controller.preview('ocx.start');
  fs.writeFileSync(controller.lockPath, 'busy\n', { flag: 'wx' });
  await assert.rejects(
    controller.execute(preview.confirmationToken),
    error => error instanceof ActionError && error.code === 'action_busy'
  );
  fs.unlinkSync(controller.lockPath);
  assert.equal(fs.readdirSync(path.join(stateRoot, 'previews')).length, 1);
});

test('failed OCX start rolls back a proxy that became healthy', async t => {
  const stateRoot = temporaryState(t);
  let healthy = false;
  const calls = [];
  const controller = createActionController({
    stateRoot,
    ocxExecutable: 'ocx-fixture',
    getOcxStatus: async () => ({ installed: true, healthy, version: '2.7.42', runtime: null }),
    getAccountStatus: async () => ({}),
    runCommand: async (_executable, args) => {
      calls.push(args.join(' '));
      if (args.length === 1 && args[0] === 'service') {
        healthy = true;
        return commandResult({ ok: false, exitCode: 1, stderr: 'failed after start' });
      }
      healthy = false;
      return commandResult();
    }
  });
  const preview = await controller.preview('ocx.start');
  const result = await controller.execute(preview.confirmationToken);
  assert.equal(result.ok, false);
  assert.deepEqual(calls, ['service', 'service stop']);
  assert.deepEqual(result.rollback, {
    attempted: true,
    commandOk: true,
    restored: true,
    state: { installed: true, healthy: false, version: '2.7.42', port: null }
  });
});

test('account switch resolves a real account and delegates to the embedded command contract', async t => {
  const stateRoot = temporaryState(t);
  let activeAccount = 'one@example.invalid';
  const calls = [];
  const accounts = [
    { index: 1, account: 'one@example.invalid', id_prefix: '11111111', expired: false },
    { index: 2, account: 'two@example.invalid', id_prefix: '22222222', expired: false }
  ];
  const controller = createActionController({
    stateRoot,
    getOcxStatus: async () => ({}),
    getAccountStatus: async () => ({ state: 'ready', activeAccount, accounts }),
    accountSwitchCommand: selector => ({ executable: 'python-fixture', args: ['manager.py', 'switch', selector] }),
    runCommand: async (executable, args) => {
      calls.push([executable, args]);
      activeAccount = args.at(-1);
      return commandResult({ stdout: 'access_token=must-not-leak' });
    }
  });
  const preview = await controller.preview('account.switch', { selector: '2' });
  assert.equal(preview.args.selector, 'two@example.invalid');
  const result = await controller.execute(preview.confirmationToken);
  assert.equal(result.ok, true);
  assert.deepEqual(calls, [['python-fixture', ['manager.py', 'switch', 'two@example.invalid']]]);
  assert.equal(result.command.output, 'access_token=<redacted>');
});

test('expired and already-active accounts cannot produce a preview', async t => {
  const controller = createActionController({
    stateRoot: temporaryState(t),
    getOcxStatus: async () => ({}),
    getAccountStatus: async () => ({
      state: 'ready',
      activeAccount: 'one@example.invalid',
      accounts: [
        { index: 1, account: 'one@example.invalid', expired: false },
        { index: 2, account: 'old@example.invalid', expired: true }
      ]
    })
  });
  await assert.rejects(controller.preview('account.switch', { selector: '1' }), error => error.code === 'already_active');
  await assert.rejects(controller.preview('account.switch', { selector: '2' }), error => error.code === 'account_expired');
});

test('OCX account switch uses a guarded preview and restores the previous account on failure', async t => {
  const stateRoot = temporaryState(t);
  let activeId = 'one';
  const calls = [];
  const accounts = [
    { id: 'one', label: 'one', active: true, needsReauth: false, paused: false },
    { id: 'two', label: 'two', active: false, needsReauth: false, paused: false }
  ];
  const controller = createActionController({
    stateRoot,
    ocxExecutable: 'ocx-fixture',
    getOcxStatus: async () => ({}),
    getAccountStatus: async () => ({}),
    getOcxAccountStatus: async () => ({
      state: 'ready', activeId,
      accounts: accounts.map(account => ({ ...account, active: account.id === activeId }))
    }),
    runCommand: async (_executable, args) => {
      calls.push(args);
      activeId = args.at(-1);
      return commandResult();
    }
  });
  const preview = await controller.preview('ocx.account.use', { selector: 'two' });
  const result = await controller.execute(preview.confirmationToken);
  assert.equal(result.ok, true);
  assert.equal(activeId, 'two');
  assert.deepEqual(calls, [['account', 'use', 'openai', 'two']]);
});

test('OCX import action verifies one new account and preserves the active selection', async t => {
  const stateRoot = temporaryState(t);
  let accounts = [{ id: 'one', label: 'one', active: true, needsReauth: false, paused: false }];
  const controller = createActionController({
    stateRoot,
    getOcxStatus: async () => ({}),
    getAccountStatus: async () => ({}),
    getOcxAccountStatus: async () => ({ state: 'ready', activeId: 'one', accounts }),
    ocxImportCommand: () => ({ executable: 'import-fixture', args: [] }),
    runCommand: async () => {
      accounts = [...accounts, { id: 'two', label: 'plus', active: false, needsReauth: false, paused: false }];
      return commandResult({ stdout: '{"ok":true,"imported":true}' });
    }
  });
  const preview = await controller.preview('ocx.account.import-cm');
  const result = await controller.execute(preview.confirmationToken);
  assert.equal(result.ok, true);
  assert.equal(result.after.activeId, 'one');
  assert.equal(result.after.accounts.length, 2);
});

test('OCX import action accepts an in-place credential refresh', async t => {
  const stateRoot = temporaryState(t);
  const accounts = [
    { id: 'one', label: 'one', active: true, needsReauth: false, paused: false },
    { id: 'owner', label: 'owner', active: false, needsReauth: false, paused: false }
  ];
  const controller = createActionController({
    stateRoot,
    getOcxStatus: async () => ({}),
    getAccountStatus: async () => ({}),
    getOcxAccountStatus: async () => ({ state: 'ready', activeId: 'one', accounts }),
    ocxImportCommand: () => ({ executable: 'import-fixture', args: [] }),
    runCommand: async () => commandResult({ stdout: '{"ok":true,"imported":true}' })
  });
  const preview = await controller.preview('ocx.account.import-cm');
  const result = await controller.execute(preview.confirmationToken);
  assert.equal(result.ok, true);
  assert.equal(result.after.activeId, 'one');
  assert.equal(result.after.accounts.length, 2);
});
