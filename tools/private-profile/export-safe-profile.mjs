#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { redactText, sanitize } from '../../src/lib/redact.mjs';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const home = fs.realpathSync(os.homedir());
const output = path.resolve(process.argv[2] ?? path.join(projectRoot, 'runtime', 'private-profile-export'));

function portableText(value) {
  return redactText(String(value ?? ''))
    .replaceAll(projectRoot, '${HOME}/dev/projects/tools/AICC')
    .replaceAll(home, '${HOME}')
    .replace(/^\s*(?:api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret|credential|cookie)\s*=.*$/gim,
      '# secret omitted; restore through login or the operating-system secret store');
}

function portableCodexConfig(value) {
  const generatedSections = /^(marketplaces\.|tui\.model_availability_nux$)/;
  let skip = false;
  return portableText(value).split(/\r?\n/).filter(line => {
    const section = line.match(/^\[([^\]]+)\]\s*$/)?.[1];
    if (section) skip = generatedSections.test(section);
    return !skip;
  }).join('\n').trim();
}

function write(relative, value, mode = 0o600) {
  const target = path.join(output, relative);
  fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
  fs.writeFileSync(target, value.endsWith('\n') ? value : `${value}\n`, { encoding: 'utf8', mode });
}

function readIfPresent(file) {
  return fs.existsSync(file) && fs.statSync(file).isFile() ? fs.readFileSync(file, 'utf8') : null;
}

function command(commandName, args = []) {
  try { return execFileSync(commandName, args, { encoding: 'utf8', timeout: 10_000 }).trim(); }
  catch { return null; }
}

function namesAt(root) {
  if (!fs.existsSync(root)) return [];
  return fs.readdirSync(root, { withFileTypes: true })
    .filter(entry => !entry.name.startsWith('.') && (entry.isDirectory() || entry.isSymbolicLink() || entry.isFile()))
    .map(entry => entry.isFile() ? entry.name.replace(/\.[^.]+$/, '') : entry.name).sort();
}

fs.mkdirSync(output, { recursive: true, mode: 0o700 });

const codexConfig = readIfPresent(path.join(home, '.codex', 'config.toml'));
if (codexConfig) write('profile/codex/config.portable.toml', portableCodexConfig(codexConfig));

const coordination = readIfPresent(path.join(home, '.ai-control-center', 'guidance', 'coordination.toml'));
if (coordination) write('profile/aicc/coordination.portable.toml', portableText(coordination));

const workspaceConfigFile = path.join(home, '.ai-control-center', 'workspace-mcp', 'config.json');
if (fs.existsSync(workspaceConfigFile)) {
  const workspaceConfig = sanitize(JSON.parse(fs.readFileSync(workspaceConfigFile, 'utf8')));
  const portable = JSON.stringify(workspaceConfig, null, 2)
    .replaceAll(projectRoot, '${HOME}/dev/projects/tools/AICC')
    .replaceAll(home, '${HOME}');
  write('profile/aicc/workspace-mcp.portable.json', portable);
}

const ocxConfigFile = path.join(home, '.opencodex', 'config.json');
if (fs.existsSync(ocxConfigFile)) {
  const source = JSON.parse(fs.readFileSync(ocxConfigFile, 'utf8'));
  const safe = sanitize({
    port: source.port,
    defaultProvider: source.defaultProvider,
    disabledModels: source.disabledModels,
    subagentModels: source.subagentModels,
    providerIds: Object.keys(source.providers ?? {}).sort(),
    note: 'Accounts, OAuth material, active account IDs and provider credentials are intentionally omitted.'
  });
  write('profile/ocx/settings.safe.json', JSON.stringify(safe, null, 2));
}

const publicRepository = 'https://github.com/AgenticLab-SH/AICC.git';
const remoteCommit = command('git', ['ls-remote', publicRepository, 'refs/heads/main'])?.split(/\s+/)[0];
const gitCommit = process.env.AICC_PUBLIC_COMMIT || remoteCommit || command('git', ['-C', projectRoot, 'rev-parse', 'HEAD']);
const inventory = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  publicAicc: {
    repository: publicRepository,
    commit: gitCommit
  },
  runtimes: {
    node: process.version,
    codex: command(path.join(home, '.codex', 'packages', 'standalone', 'current', 'codex'), ['--version'])
      ?? command('/Applications/ChatGPT.app/Contents/Resources/codex', ['--version']),
    ocx: command('ocx', ['--version'])
  },
  codex: {
    skills: namesAt(path.join(home, '.codex', 'skills')),
    agents: namesAt(path.join(home, '.codex', 'agents')),
    plugins: [...(codexConfig?.matchAll(/^\[plugins\."([^"]+)"\]/gm) ?? [])].map(match => match[1]).sort(),
    mcpServers: [...(codexConfig?.matchAll(/^\[mcp_servers\.([^\]]+)\]/gm) ?? [])].map(match => match[1]).sort()
  },
  exclusions: [
    'auth.json and account databases', 'session JSONL and SQLite state', 'API and Tunnel keys',
    'cookies and browser profiles', 'Keychain material', 'OCX OAuth accounts and provider credentials'
  ]
};
write('inventory.json', JSON.stringify(inventory, null, 2), 0o644);

write('README.md', `# my AICC\n\nThis private repository pins the public AICC source and stores only portable, non-secret machine overlays.\n\n## Restore on another Mac\n\n1. Clone the public repository at the commit in \`inventory.json\`.\n2. Run \`./install.sh\`, \`aicc setup\`, and \`aicc guidance deploy\`.\n3. Review the portable files under \`profile/\`, replace \`\${HOME}\`, and merge them into the new machine.\n4. Log in to Codex, OCX providers, ChatGPT Business, Secure MCP Tunnel, mail, and browsers on that machine.\n5. Run \`aicc status --json\`, \`aicc guidance check\`, \`aicc workspace configure\`, and \`ocx health\`.\n\nPrivate Git is not a secret store. The exclusions in \`inventory.json\` are deliberate and must not be bypassed.\n`, 0o644);

console.log(JSON.stringify({ ok: true, output, files: fs.readdirSync(output).sort() }, null, 2));
