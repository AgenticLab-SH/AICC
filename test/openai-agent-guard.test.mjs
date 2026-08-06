import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import {
  installOpenaiAgentGuard,
  openaiAgentGuardStatus,
  rollbackOpenaiAgentGuard
} from '../tools/platform/codex/install-openai-api-guard.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const hook = path.join(root, 'tools', 'platform', 'codex', 'openai_api_guard_hook.py');

function fixture(t) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-openai-agent-guard-'));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  for (const codexHome of [path.join(home, '.codex'), path.join(home, '.codex-multi', 'homes', 'secondary')]) {
    fs.mkdirSync(codexHome, { recursive: true });
    fs.writeFileSync(path.join(codexHome, 'config.toml'), 'model = "gpt-5.6-luna"\n', { mode: 0o600 });
  }
  return { home, stateRoot: path.join(home, '.ai-control-center') };
}

test('agent guard applies and rolls back every Codex home as one managed set', t => {
  const options = fixture(t);
  assert.equal(openaiAgentGuardStatus(options).ok, false);
  const applied = installOpenaiAgentGuard(options);
  assert.equal(applied.ok, true);
  assert.equal(applied.guardedCount, 2);
  for (const codexHome of [path.join(options.home, '.codex'), path.join(options.home, '.codex-multi', 'homes', 'secondary')]) {
    const config = fs.readFileSync(path.join(codexHome, 'config.toml'), 'utf8');
    assert.match(config, /OPENAI_API_KEY = "exclude"/);
    assert.match(config, /OPENAI_ADMIN_KEY = "exclude"/);
    assert.match(fs.readFileSync(path.join(codexHome, 'requirements.toml'), 'utf8'), /Managed by AICC OpenAI API guard/);
  }
  const rolledBack = rollbackOpenaiAgentGuard(options);
  assert.equal(rolledBack.ok, false);
  assert.equal(fs.existsSync(path.join(options.home, '.codex', 'requirements.toml')), false);
  assert.equal(fs.readFileSync(path.join(options.home, '.codex', 'config.toml'), 'utf8'), 'model = "gpt-5.6-luna"\n');
});

test('agent guard preflights all homes before changing any config', t => {
  const options = fixture(t);
  const appConfig = path.join(options.home, '.codex', 'config.toml');
  const before = fs.readFileSync(appConfig, 'utf8');
  fs.writeFileSync(path.join(options.home, '.codex-multi', 'homes', 'secondary', 'requirements.toml'), '[features]\nhooks = false\n', { mode: 0o600 });
  assert.throws(() => installOpenaiAgentGuard(options), /AICC가 소유하지 않아/);
  assert.equal(fs.readFileSync(appConfig, 'utf8'), before);
  assert.equal(fs.existsSync(path.join(options.home, '.codex', 'requirements.toml')), false);
});

test('agent guard hook denies direct OpenAI calls and allows the AICC gateway', () => {
  const python = process.platform === 'win32' ? 'python' : 'python3';
  const run = command => spawnSync(python, [hook], {
    input: JSON.stringify({ tool_name: 'Bash', tool_input: { command } }),
    encoding: 'utf8'
  });
  const denied = run('curl https://api.openai.com/v1/responses');
  assert.equal(denied.status, 0);
  assert.equal(JSON.parse(denied.stdout).hookSpecificOutput.permissionDecision, 'deny');
  const allowed = run("printf 'hello' | aicc openai ask --json");
  assert.equal(allowed.status, 0);
  assert.equal(allowed.stdout, '');
});
