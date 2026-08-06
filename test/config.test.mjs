import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { configPath, defaultPythonCommand, loadUserEnv, parseEnvFile } from '../src/config.mjs';
import { setupEnvironment } from '../src/setup.mjs';

test('personal config accepts supported values and rejects unknown keys', () => {
  assert.deepEqual(parseEnvFile('AICC_PORT=4400\nAICC_WORKSPACE_PROJECTS_ROOT="/tmp/projects"\n'), {
    AICC_PORT: '4400',
    AICC_WORKSPACE_PROJECTS_ROOT: '/tmp/projects'
  });
  assert.throws(() => parseEnvFile('PATH=/tmp/bin\n'), /지원하지 않는 설정/);
});

test('Python command defaults are platform appropriate', () => {
  assert.deepEqual(defaultPythonCommand('darwin'), { executable: 'python3', args: [] });
  assert.deepEqual(defaultPythonCommand('win32'), { executable: 'py', args: ['-3'] });
});

test('AICC_STATE_ROOT owns the personal config when explicitly set', () => {
  assert.equal(configPath({ AICC_STATE_ROOT: '/private/aicc' }, '/fixture/home'), path.join('/private/aicc', 'config.env'));
});

test('shell environment wins over the personal config file', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-config-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'config.env');
  fs.writeFileSync(file, 'AICC_PORT=4400\nAICC_WORKSPACE_PROJECTS_ROOT=/tmp/projects\n', { mode: 0o600 });
  const env = { AICC_PORT: '4500' };
  const result = loadUserEnv({ env, file });
  assert.equal(env.AICC_PORT, '4500');
  assert.equal(env.AICC_WORKSPACE_PROJECTS_ROOT, '/tmp/projects');
  assert.deepEqual(result.keys, ['AICC_WORKSPACE_PROJECTS_ROOT']);
});

test('setup creates a private personal config without secrets', async t => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-home-'));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  const result = await setupEnvironment({
    home,
    env: {},
    runCommand: async () => ({ ok: true, stdout: 'fixture 1.0\n' })
  });
  assert.equal(result.created, true);
  assert.equal(result.ok, true);
  assert.equal(fs.existsSync(path.join(home, '.ai-control-center', 'account-manager')), true);
  assert.equal(fs.existsSync(path.join(home, '.ai-control-center', 'guidance', 'coordination.toml')), true);
  assert.equal(fs.existsSync(path.join(home, '.ai-control-center', 'guidance', 'website-maker.json')), true);
  if (process.platform !== 'win32') assert.equal(fs.statSync(result.file).mode & 0o077, 0);
  assert.doesNotMatch(fs.readFileSync(result.file, 'utf8'), /sk-|Bearer|gmail\.com/);
});

test('setup check reports an insecure file instead of loading it', async t => {
  if (process.platform === 'win32') return;
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'aicc-insecure-'));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  const directory = path.join(home, '.ai-control-center');
  const file = path.join(directory, 'config.env');
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(file, 'AICC_PORT=4400\n', { mode: 0o644 });
  const result = await setupEnvironment({ home, checkOnly: true, env: {}, runCommand: async () => ({ ok: true, stdout: 'fixture\n' }) });
  assert.equal(result.ok, false);
  assert.match(result.security.reason, /0600/);
});
