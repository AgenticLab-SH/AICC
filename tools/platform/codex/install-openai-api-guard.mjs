#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const marker = '# Managed by AICC OpenAI API guard';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const hook = path.join(root, 'tools', 'platform', 'codex', 'openai_api_guard_hook.py');

function stateRoot(options = {}) {
  return options.stateRoot || process.env.AICC_STATE_ROOT?.trim() || path.join(options.home || os.homedir(), '.ai-control-center');
}

function homes(options = {}) {
  const home = options.home || os.homedir();
  const result = [path.join(home, '.codex')];
  const accounts = path.join(home, '.codex-multi', 'homes');
  try {
    for (const name of fs.readdirSync(accounts)) {
      const candidate = path.join(accounts, name);
      if (fs.statSync(candidate).isDirectory()) result.push(candidate);
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  return result;
}

function assertRegularOrMissing(file) {
  try {
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`일반 파일만 변경할 수 있습니다: ${file}`);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}

function ensureFilterBlock(text) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const header = '[shell_environment_policy.filters]';
  let start = lines.findIndex(line => line.trim() === header);
  if (start < 0) {
    const insertion = lines.findIndex(line => /^\[shell_environment_policy\./.test(line.trim()));
    const block = [header, 'OPENAI_API_KEY = "exclude"', 'OPENAI_ADMIN_KEY = "exclude"', ''];
    lines.splice(insertion < 0 ? lines.length : insertion, 0, ...block);
    return `${lines.join('\n').replace(/\n+$/, '')}\n`;
  }
  let end = start + 1;
  while (end < lines.length && !/^\s*\[/.test(lines[end])) end += 1;
  const kept = lines.slice(start + 1, end).filter(line => !/^\s*OPENAI_(?:API|ADMIN)_KEY\s*=/.test(line));
  lines.splice(start + 1, end - start - 1, 'OPENAI_API_KEY = "exclude"', 'OPENAI_ADMIN_KEY = "exclude"', ...kept);
  return `${lines.join('\n').replace(/\n+$/, '')}\n`;
}

function requirementsText() {
  const command = `/usr/bin/python3 ${JSON.stringify(hook)}`;
  return `${marker}
[features]
hooks = true

[hooks]
managed_dir = ${JSON.stringify(path.dirname(hook))}

[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = ${JSON.stringify(command)}
timeout = 5
statusMessage = "Checking AICC OpenAI API policy"
`;
}

function validateToml(files, options = {}) {
  const python = options.python || 'python3';
  const script = 'import pathlib,sys,tomllib; [tomllib.loads(pathlib.Path(p).read_text()) for p in sys.argv[1:]]';
  const result = spawnSync(python, ['-c', script, ...files], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 10_000 });
  if (result.status !== 0) throw new Error(`Codex TOML 검증 실패: ${(result.stderr || result.stdout || '').trim()}`);
}

function atomicWrite(file, value, mode = 0o600) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, value, { mode });
  fs.renameSync(temporary, file);
  if (process.platform !== 'win32') fs.chmodSync(file, mode);
}

function sha(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

export function openaiAgentGuardStatus(options = {}) {
  const rows = homes(options).map(home => {
    const config = path.join(home, 'config.toml');
    const requirements = path.join(home, 'requirements.toml');
    const configText = fs.existsSync(config) ? fs.readFileSync(config, 'utf8') : '';
    const requirementsContent = fs.existsSync(requirements) ? fs.readFileSync(requirements, 'utf8') : '';
    return {
      scope: path.basename(home) === '.codex' ? 'app' : 'account',
      envFiltered: /OPENAI_API_KEY\s*=\s*["']exclude["']/.test(configText) && /OPENAI_ADMIN_KEY\s*=\s*["']exclude["']/.test(configText),
      managedHook: requirementsContent.includes(marker) && requirementsContent.includes('openai_api_guard_hook.py')
    };
  });
  return { ok: rows.every(row => row.envFiltered && row.managedHook), scopeCount: rows.length, guardedCount: rows.filter(row => row.envFiltered && row.managedHook).length, rows };
}

export function installOpenaiAgentGuard(options = {}) {
  if (!fs.existsSync(hook)) throw new Error('AICC OpenAI guard hook가 없습니다.');
  const targetHomes = homes(options);
  const targets = targetHomes.map((home, index) => {
    const config = path.join(home, 'config.toml');
    const requirements = path.join(home, 'requirements.toml');
    assertRegularOrMissing(config);
    assertRegularOrMissing(requirements);
    if (!fs.existsSync(config)) throw new Error(`Codex config.toml이 없습니다: ${home}`);
    const configBefore = fs.readFileSync(config, 'utf8');
    const requirementBefore = fs.existsSync(requirements) ? fs.readFileSync(requirements, 'utf8') : null;
    if (requirementBefore != null && !requirementBefore.includes(marker)) throw new Error(`기존 requirements.toml은 AICC가 소유하지 않아 덮어쓰지 않습니다: ${home}`);
    return { home, index, config, requirements, configBefore, requirementBefore };
  });
  const backupRoot = path.join(stateRoot(options), 'backups', 'openai-agent-guard', new Date().toISOString().replace(/[:.]/g, '-'));
  fs.mkdirSync(backupRoot, { recursive: true, mode: 0o700 });
  const journal = [];
  const validate = [];
  try {
    for (const target of targets) {
      const relative = String(target.index).padStart(2, '0');
      const configBackup = path.join(backupRoot, `${relative}-config.toml`);
      const requirementsBackup = path.join(backupRoot, `${relative}-requirements.toml`);
      atomicWrite(configBackup, target.configBefore);
      if (target.requirementBefore != null) atomicWrite(requirementsBackup, target.requirementBefore);
      atomicWrite(target.config, ensureFilterBlock(target.configBefore));
      atomicWrite(target.requirements, requirementsText());
      validate.push(target.config, target.requirements);
      journal.push({
        home: target.home,
        config: target.config,
        requirements: target.requirements,
        configBackup,
        requirementsBackup: target.requirementBefore == null ? null : requirementsBackup,
        requirementExisted: target.requirementBefore != null,
        beforeHash: sha(target.configBefore)
      });
    }
    validateToml(validate, options);
  } catch (error) {
    for (const row of journal.reverse()) {
      atomicWrite(row.config, fs.readFileSync(row.configBackup, 'utf8'));
      if (row.requirementExisted) atomicWrite(row.requirements, fs.readFileSync(row.requirementsBackup, 'utf8'));
      else fs.rmSync(row.requirements, { force: true });
    }
    throw error;
  }
  const state = { schemaVersion: 1, appliedAt: new Date().toISOString(), backupRoot, files: journal };
  atomicWrite(path.join(stateRoot(options), 'openai-usage', 'agent-guard.json'), `${JSON.stringify(state, null, 2)}\n`);
  return openaiAgentGuardStatus(options);
}

export function rollbackOpenaiAgentGuard(options = {}) {
  const stateFile = path.join(stateRoot(options), 'openai-usage', 'agent-guard.json');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  for (const row of state.files || []) {
    atomicWrite(row.config, fs.readFileSync(row.configBackup, 'utf8'));
    if (row.requirementExisted) atomicWrite(row.requirements, fs.readFileSync(row.requirementsBackup, 'utf8'));
    else fs.rmSync(row.requirements, { force: true });
  }
  return openaiAgentGuardStatus(options);
}

if (path.resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  const command = process.argv[2] || 'status';
  const result = command === 'apply' ? installOpenaiAgentGuard() : command === 'rollback' ? rollbackOpenaiAgentGuard() : openaiAgentGuardStatus();
  process.stdout.write(`${JSON.stringify(result)}\n`);
}
