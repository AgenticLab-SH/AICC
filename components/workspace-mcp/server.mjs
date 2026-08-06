#!/usr/bin/env node
import { createHash, randomBytes } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import * as z from 'zod/v4';
import { callCodexAppServer, publicThread, startCodexExec } from './codex-app-server.mjs';

const componentRoot = path.dirname(fileURLToPath(import.meta.url));
const blockedNames = new Set([
  '.env', '.npmrc', '.pypirc', '.netrc', '.git-credentials', 'credentials', 'credentials.json',
  'id_rsa', 'id_ed25519', 'known_hosts'
]);
const blockedExtensions = new Set(['.pem', '.key', '.p12', '.pfx']);
const ignoredSearch = ['.git', 'node_modules', '.next', 'dist', 'build', 'coverage', '.venv'];
const processSessions = new Map();
const leases = new Map();
const activatedSkills = new Map();

function response(value, isError = false) {
  return {
    content: [{ type: 'text', text: JSON.stringify(value) }],
    structuredContent: value,
    ...(isError ? { isError: true } : {})
  };
}

function safeError(error) {
  return response({ ok: false, error: error instanceof Error ? error.message : String(error) }, true);
}

function parseArguments(argv) {
  const index = argv.indexOf('--config');
  if (index < 0 || !argv[index + 1]) throw new Error('--config 경로가 필요합니다.');
  return { configPath: path.resolve(argv[index + 1]) };
}

export function loadConfig(configPath) {
  const stat = fs.lstatSync(configPath);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Workspace MCP 설정은 실제 일반 파일이어야 합니다.');
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  if (config.schemaVersion !== 2 || !Array.isArray(config.workspaces) || !config.workspaces.length) {
    throw new Error('Workspace MCP 설정 형식이 올바르지 않습니다.');
  }
  const aliases = new Set();
  for (const item of config.workspaces) {
    if (!/^[a-z0-9._-]+$/.test(item.alias) || aliases.has(item.alias)) throw new Error('워크스페이스 별칭이 올바르지 않거나 중복되었습니다.');
    const stat = fs.lstatSync(item.root);
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error(`등록 워크스페이스가 실제 디렉터리가 아닙니다: ${item.alias}`);
    item.root = fs.realpathSync(item.root);
    aliases.add(item.alias);
  }
  return config;
}

function inside(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function assertNotSensitive(relativePath) {
  const parts = relativePath.split(/[\\/]/).filter(Boolean);
  const basename = parts.at(-1)?.toLocaleLowerCase('en-US') ?? '';
  if (blockedNames.has(basename) || blockedExtensions.has(path.extname(basename))) {
    throw new Error(`민감 파일은 원격 작업공간 도구로 읽거나 수정할 수 없습니다: ${relativePath}`);
  }
  if (parts[0] === '.git' && parts[1] !== undefined) {
    throw new Error(`Git 내부 메타데이터는 원격 작업공간 도구에서 직접 다루지 않습니다: ${relativePath}`);
  }
}

export function confinedPath(root, relativePath, options = {}) {
  root = fs.realpathSync(root);
  if (!relativePath || relativePath.includes('\0') || path.isAbsolute(relativePath)) {
    throw new Error('경로는 워크스페이스 기준 상대 경로여야 합니다.');
  }
  const normalized = path.normalize(relativePath);
  if (normalized === '..' || normalized.startsWith(`..${path.sep}`)) throw new Error('경로가 워크스페이스를 벗어납니다.');
  assertNotSensitive(normalized);
  const target = path.resolve(root, normalized);
  if (!inside(root, target)) throw new Error('경로가 워크스페이스를 벗어납니다.');
  let existing = target;
  while (!fs.existsSync(existing)) {
    const parent = path.dirname(existing);
    if (parent === existing) break;
    existing = parent;
  }
  const resolvedExisting = fs.realpathSync(existing);
  if (!inside(root, resolvedExisting)) throw new Error('심볼릭 링크가 워크스페이스 밖을 가리킵니다.');
  if (!options.allowMissing && !fs.existsSync(target)) throw new Error(`파일을 찾지 못했습니다: ${relativePath}`);
  if (fs.existsSync(target)) {
    const stat = fs.lstatSync(target);
    if (stat.isSymbolicLink()) throw new Error('심볼릭 링크 자체는 원격 도구로 다루지 않습니다.');
    const real = fs.realpathSync(target);
    if (!inside(root, real)) throw new Error('경로가 워크스페이스 밖으로 해석됩니다.');
    return real;
  }
  return target;
}

function workspaceId(item) {
  return `ws_${createHash('sha256').update(`${item.alias}\0${item.root}`).digest('hex').slice(0, 24)}`;
}

function resolveLease(config, workspaceIdValue, leaseValue) {
  const lease = leases.get(leaseValue);
  if (!lease || lease.expiresAt <= Date.now() || lease.workspaceId !== workspaceIdValue) throw new Error('워크스페이스 lease가 없거나 만료되었습니다. 다시 열어 주세요.');
  const workspace = config.workspaces.find(item => workspaceId(item) === workspaceIdValue);
  if (!workspace) throw new Error('등록되지 않은 워크스페이스입니다.');
  lease.expiresAt = Date.now() + 12 * 60 * 60_000;
  return { workspace, lease };
}

function quoteSeatbelt(value) {
  return `\"${String(value).replaceAll('\\', '\\\\').replaceAll('\"', '\\\"')}\"`;
}

function allowedRuntimeReads() {
  const candidates = ['/System', '/usr', '/bin', '/sbin', '/opt/homebrew', '/Library', '/private/var/db', '/dev'];
  const executable = fs.realpathSync(process.execPath);
  candidates.push(path.dirname(path.dirname(executable)));
  return [...new Set(candidates.filter(item => fs.existsSync(item)).map(item => fs.realpathSync(item)))];
}

export function sandboxProfile(root, runtimeRoot, network = true) {
  const home = fs.realpathSync(os.homedir());
  const reads = [root, runtimeRoot, ...allowedRuntimeReads()];
  const writes = [root, runtimeRoot, '/private/tmp', '/tmp'].filter(item => fs.existsSync(item));
  return [
    '(version 1)',
    '(allow default)',
    `(deny file-read* (subpath ${quoteSeatbelt(home)}))`,
    '(deny file-write*)',
    ...reads.map(item => `(allow file-read* (subpath ${quoteSeatbelt(item)}))`),
    ...writes.map(item => `(allow file-write* (subpath ${quoteSeatbelt(fs.realpathSync(item))}))`),
    ...(network ? [] : ['(deny network*)'])
  ].join('\n');
}

function cleanEnvironment(root, runtimeRoot) {
  const pathValue = ['/usr/bin', '/bin', '/usr/sbin', '/sbin', '/opt/homebrew/bin', path.dirname(process.execPath)]
    .filter(item => fs.existsSync(item)).join(':');
  return {
    PATH: pathValue,
    LANG: process.env.LANG || 'en_US.UTF-8',
    LC_ALL: process.env.LC_ALL || process.env.LANG || 'en_US.UTF-8',
    TMPDIR: '/private/tmp',
    HOME: root,
    AICC_WORKSPACE_ROOT: root,
    AICC_RUNTIME_ROOT: runtimeRoot,
    NO_COLOR: '1',
    CI: '1'
  };
}

function sandboxInvocation(root, runtimeRoot, command, network) {
  if (process.platform !== 'darwin' || !fs.existsSync('/usr/bin/sandbox-exec')) {
    throw new Error('명령 실행은 macOS sandbox-exec가 있는 호스트에서만 지원됩니다.');
  }
  return {
    executable: '/usr/bin/sandbox-exec',
    args: ['-p', sandboxProfile(root, runtimeRoot, network), '/bin/zsh', '-f', '-c', command],
    env: cleanEnvironment(root, runtimeRoot)
  };
}

function appendOutput(session, chunk) {
  session.output += chunk.toString('utf8');
  if (Buffer.byteLength(session.output) > session.maxOutputBytes) {
    session.output = session.output.slice(-session.maxOutputBytes);
    session.truncated = true;
  }
}

function sessionResult(session, from = 0) {
  return {
    ok: session.exitCode === 0 || session.exitCode === null,
    session_id: session.id,
    running: session.exitCode === null,
    exit_code: session.exitCode,
    output: session.output.slice(from),
    output_cursor: session.output.length,
    truncated: session.truncated
  };
}

function startCommand(root, runtimeRoot, command, config, yieldTimeMs) {
  const invocation = sandboxInvocation(root, runtimeRoot, command, config.permissions.network !== false);
  const child = spawn(invocation.executable, invocation.args, {
    cwd: root,
    env: invocation.env,
    stdio: ['pipe', 'pipe', 'pipe'],
    detached: false
  });
  const id = `proc_${randomBytes(16).toString('hex')}`;
  const session = {
    id, child, output: '', exitCode: null, truncated: false,
    maxOutputBytes: config.permissions.maxOutputBytes ?? 262_144
  };
  processSessions.set(id, session);
  child.stdout.on('data', chunk => appendOutput(session, chunk));
  child.stderr.on('data', chunk => appendOutput(session, chunk));
  child.on('close', code => { session.exitCode = code ?? 1; session.child = null; });
  return new Promise(resolve => setTimeout(() => resolve(sessionResult(session)), Math.max(50, Math.min(yieldTimeMs, 10_000))));
}

function validatePatchPaths(root, patchText) {
  const paths = [];
  for (const line of patchText.replace(/\r\n/g, '\n').split('\n')) {
    if (!line.startsWith('+++ ') && !line.startsWith('--- ')) continue;
    const raw = line.slice(4).split('\t')[0].trim();
    if (raw === '/dev/null') continue;
    const relative = raw.replace(/^[ab]\//, '');
    confinedPath(root, relative, { allowMissing: true });
    paths.push(relative);
  }
  if (!paths.length) throw new Error('통합 diff에 파일 경로가 없습니다.');
  return [...new Set(paths)];
}

function runPatch(root, runtimeRoot, patchText, network) {
  const files = validatePatchPaths(root, patchText);
  const profile = sandboxProfile(root, runtimeRoot, network);
  const execute = dryRun => spawnSync('/usr/bin/sandbox-exec', [
    '-p', profile, '/usr/bin/patch', '--batch', '--forward', '-p1', ...(dryRun ? ['--dry-run'] : [])
  ], { cwd: root, input: patchText, encoding: 'utf8', env: cleanEnvironment(root, runtimeRoot), timeout: 30_000 });
  const checked = execute(true);
  if (checked.status !== 0) throw new Error(`패치 사전 검사가 실패했습니다: ${(checked.stderr || checked.stdout || '').trim()}`);
  const applied = execute(false);
  if (applied.status !== 0) throw new Error(`패치 적용이 실패했습니다: ${(applied.stderr || applied.stdout || '').trim()}`);
  return { ok: true, files, output: (applied.stdout || '').trim() };
}

function gitSummary(root, maxOutputBytes) {
  const run = args => spawnSync('/usr/bin/git', args, { cwd: root, encoding: 'utf8', timeout: 15_000, maxBuffer: maxOutputBytes });
  const status = run(['status', '--short']);
  const stat = run(['diff', '--stat']);
  const staged = run(['diff', '--cached', '--stat']);
  if (status.status !== 0) throw new Error((status.stderr || 'Git 상태를 읽지 못했습니다.').trim());
  return { ok: true, status: status.stdout, diff_stat: stat.stdout, staged_stat: staged.stdout };
}

function skillCatalog(config) {
  const entries = [];
  for (const root of config.skillRoots ?? []) {
    if (!fs.existsSync(root)) continue;
    for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
      const skillFile = path.join(root, entry.name, 'SKILL.md');
      if (!fs.existsSync(skillFile)) continue;
      const first = fs.readFileSync(skillFile, 'utf8').split('\n').slice(0, 12).join('\n');
      const description = first.match(/^description:\s*[\"']?(.*?)[\"']?\s*$/m)?.[1] ?? '';
      entries.push({ id: entry.name, description, root: path.join(root, entry.name) });
    }
  }
  return entries.sort((a, b) => a.id.localeCompare(b.id));
}

function assertThreadWorkspace(thread, workspace) {
  if (!thread?.cwd || !fs.existsSync(thread.cwd)) throw new Error('Codex 작업의 워크스페이스를 확인할 수 없습니다.');
  if (fs.realpathSync(thread.cwd) !== fs.realpathSync(workspace.root)) {
    throw new Error('선택한 워크스페이스의 Codex 작업이 아닙니다.');
  }
  return thread;
}

async function readScopedThread(config, workspace, threadId, includeTurns = false) {
  const result = await callCodexAppServer(config, 'thread/read', { threadId, includeTurns });
  return assertThreadWorkspace(result?.thread, workspace);
}

export function createWorkspaceMcpServer(config, options = {}) {
  const runtimeRoot = options.runtimeRoot ?? path.join(path.dirname(options.configPath ?? os.tmpdir()), 'runtime');
  fs.mkdirSync(runtimeRoot, { recursive: true, mode: 0o700 });
  const server = new McpServer({ name: 'aicc-workspace', version: '1.0.0' });
  const leaseFields = {
    workspace_id: z.string().regex(/^ws_[a-f0-9]{24}$/),
    lease: z.string().regex(/^lease_[a-f0-9]{32}$/)
  };
  const withLease = callback => async input => {
    try {
      const resolved = resolveLease(config, input.workspace_id, input.lease);
      return await callback(input, resolved);
    } catch (error) { return safeError(error); }
  };

  server.registerTool('aicc_workspace_open', {
    title: 'AICC 워크스페이스 열기',
    description: 'AICC에 미리 등록된 별칭으로 하나의 로컬 워크스페이스를 엽니다. 임의 경로는 허용하지 않습니다.',
    inputSchema: { alias: z.string().min(1).max(128) },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: false }
  }, async ({ alias }) => {
    try {
      const workspace = config.workspaces.find(item => item.alias === alias);
      if (!workspace) throw new Error(`등록된 워크스페이스 별칭이 아닙니다: ${alias}`);
      const id = workspaceId(workspace);
      const lease = `lease_${randomBytes(16).toString('hex')}`;
      leases.set(lease, { workspaceId: id, expiresAt: Date.now() + 12 * 60 * 60_000 });
      activatedSkills.set(lease, new Set());
      return response({ ok: true, workspace_id: id, lease, alias, label: workspace.label, expires_in_seconds: 43_200 });
    } catch (error) { return safeError(error); }
  });

  server.registerTool('aicc_workspace_list', {
    title: 'AICC 워크스페이스 목록',
    description: '등록된 워크스페이스 별칭과 표시 이름을 반환합니다. 로컬 절대 경로는 노출하지 않습니다.',
    inputSchema: {},
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  }, async () => response({ ok: true, default: config.defaultWorkspace, workspaces: config.workspaces.map(({ alias, label }) => ({ alias, label })) }));

  server.registerTool('aicc_workspace_read', {
    title: '워크스페이스 파일 읽기',
    description: '열린 워크스페이스 안의 텍스트 파일 일부를 읽습니다.',
    inputSchema: { ...leaseFields, path: z.string().min(1), start_line: z.number().int().min(1).default(1), max_lines: z.number().int().min(1).max(2000).default(400) },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  }, withLease(async (input, { workspace }) => {
    const file = confinedPath(workspace.root, input.path);
    const stat = fs.statSync(file);
    if (!stat.isFile()) throw new Error('일반 파일만 읽을 수 있습니다.');
    if (stat.size > (config.permissions.maxReadBytes ?? 1_048_576)) throw new Error('파일이 원격 읽기 제한보다 큽니다. 검색 또는 범위 읽기를 사용하세요.');
    const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);
    const start = input.start_line - 1;
    return response({ ok: true, path: input.path, start_line: input.start_line, end_line: Math.min(lines.length, start + input.max_lines), total_lines: lines.length, text: lines.slice(start, start + input.max_lines).join('\n') });
  }));

  server.registerTool('aicc_workspace_search', {
    title: '워크스페이스 검색',
    description: 'ripgrep으로 열린 워크스페이스 안의 파일명 또는 텍스트를 검색합니다.',
    inputSchema: { ...leaseFields, query: z.string().min(1).max(500), path: z.string().default('.'), files_only: z.boolean().default(false), max_results: z.number().int().min(1).max(500).default(100) },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  }, withLease(async (input, { workspace }) => {
    const searchRoot = input.path === '.' ? workspace.root : confinedPath(workspace.root, input.path);
    const args = input.files_only ? ['--files', searchRoot] : ['-n', '--hidden', '--no-messages', '--fixed-strings', '--', input.query, searchRoot];
    for (const ignored of ignoredSearch) args.unshift('--glob', `!${ignored}/**`);
    const result = spawnSync('rg', args, { cwd: workspace.root, encoding: 'utf8', timeout: 20_000, maxBuffer: config.permissions.maxOutputBytes ?? 262_144 });
    if (![0, 1].includes(result.status)) throw new Error((result.stderr || '검색 실행에 실패했습니다.').trim());
    const lines = (result.stdout || '').split('\n').filter(Boolean).slice(0, input.max_results);
    return response({ ok: true, results: lines, truncated: lines.length >= input.max_results });
  }));

  server.registerTool('aicc_workspace_apply_patch', {
    title: '워크스페이스 패치 적용',
    description: '열린 워크스페이스 안에만 통합 diff를 사전 검사한 뒤 적용합니다.',
    inputSchema: { ...leaseFields, patch: z.string().min(1).max(2_000_000) },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false }
  }, withLease(async (input, { workspace }) => response(runPatch(workspace.root, runtimeRoot, input.patch, config.permissions.network !== false))));

  server.registerTool('aicc_workspace_exec', {
    title: '워크스페이스 명령 실행',
    description: 'macOS 샌드박스에서 명령을 실행합니다. 읽기와 쓰기는 열린 워크스페이스 및 제한된 런타임 경로로 한정됩니다.',
    inputSchema: { ...leaseFields, command: z.string().min(1).max(20_000), yield_time_ms: z.number().int().min(50).max(10_000).default(1_000) },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true }
  }, withLease(async (input, { workspace }) => {
    if (!config.permissions.commands) throw new Error('이 AICC 구성에서는 명령 실행이 꺼져 있습니다.');
    return response(await startCommand(workspace.root, runtimeRoot, input.command, config, input.yield_time_ms));
  }));

  server.registerTool('aicc_workspace_write_stdin', {
    title: '실행 중인 명령에 입력',
    description: 'aicc_workspace_exec가 반환한 현재 프로세스 세션에 입력하거나 출력을 폴링합니다.',
    inputSchema: { ...leaseFields, session_id: z.string().regex(/^proc_[a-f0-9]{32}$/), chars: z.string().max(100_000).default(''), output_cursor: z.number().int().min(0).default(0) },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false }
  }, withLease(async input => {
    const session = processSessions.get(input.session_id);
    if (!session) throw new Error('프로세스 세션을 찾지 못했습니다. 런타임 재시작 뒤에는 명령을 새로 실행해야 합니다.');
    if (input.chars) {
      if (!session.child || session.exitCode !== null) throw new Error('프로세스가 이미 종료되었습니다.');
      session.child.stdin.write(input.chars);
    }
    return response(sessionResult(session, input.output_cursor));
  }));

  server.registerTool('aicc_workspace_changes', {
    title: '워크스페이스 변경 검토',
    description: '현재 Git 변경 파일과 staged/unstaged 요약을 반환합니다.',
    inputSchema: leaseFields,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  }, withLease(async (input, { workspace }) => response(gitSummary(workspace.root, config.permissions.maxOutputBytes ?? 262_144))));

  server.registerTool('aicc_skill_inventory', {
    title: 'AICC 스킬 목록',
    description: 'AICC 정본에 등록된 스킬 이름과 설명을 반환합니다.',
    inputSchema: leaseFields,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  }, withLease(async () => response({ ok: true, skills: skillCatalog(config).map(({ id, description }) => ({ id, description })) })));

  server.registerTool('aicc_skill_read', {
    title: 'AICC 스킬 읽기',
    description: '처음에는 SKILL.md 전체를 읽고, 그 뒤에만 같은 스킬이 직접 참조한 파일을 읽습니다.',
    inputSchema: { ...leaseFields, skill_id: z.string().min(1).max(200), path: z.string().default('SKILL.md') },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  }, withLease(async input => {
    const skill = skillCatalog(config).find(item => item.id === input.skill_id);
    if (!skill) throw new Error('등록된 AICC 스킬이 아닙니다.');
    const active = activatedSkills.get(input.lease) ?? new Set();
    if (input.path !== 'SKILL.md' && !active.has(input.skill_id)) throw new Error('먼저 이 스킬의 SKILL.md 전체를 읽어야 합니다.');
    const file = confinedPath(skill.root, input.path);
    const stat = fs.statSync(file);
    if (!stat.isFile() || stat.size > (config.permissions.maxReadBytes ?? 1_048_576)) throw new Error('스킬 파일을 읽을 수 없거나 제한보다 큽니다.');
    const text = fs.readFileSync(file, 'utf8');
    if (input.path === 'SKILL.md') active.add(input.skill_id);
    activatedSkills.set(input.lease, active);
    return response({ ok: true, skill_id: input.skill_id, path: input.path, text });
  }));

  server.registerTool('aicc_codex_task_list', {
    title: 'Codex 작업 목록',
    description: '열린 워크스페이스에서 실행된 최근 Codex 작업만 조회합니다. 이 도구는 Web GPT를 모델 provider로 등록하지 않습니다.',
    inputSchema: { ...leaseFields, limit: z.number().int().min(1).max(50).default(20), archived: z.boolean().default(false) },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  }, withLease(async (input, { workspace }) => {
    const result = await callCodexAppServer(config, 'thread/list', {
      cwd: workspace.root, limit: input.limit, archived: input.archived, useStateDbOnly: true,
      sortKey: 'recency_at', sortDirection: 'desc'
    });
    return response({ ok: true, tasks: (result?.data ?? []).map(thread => publicThread(thread)), next_cursor: result?.nextCursor ?? null });
  }));

  server.registerTool('aicc_codex_task_read', {
    title: 'Codex 작업 읽기',
    description: '열린 워크스페이스의 Codex 작업에서 사용자·응답·계획·압축 표시만 안전하게 읽습니다. 명령 출력과 비밀 경로는 반환하지 않습니다.',
    inputSchema: { ...leaseFields, task_id: z.string().uuid() },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  }, withLease(async (input, { workspace }) => {
    const thread = await readScopedThread(config, workspace, input.task_id, true);
    return response({ ok: true, task: publicThread(thread, { includeTurns: true }) });
  }));

  server.registerTool('aicc_codex_task_create', {
    title: 'Codex 작업 시작',
    description: '열린 워크스페이스에 지속되는 Codex 작업을 만들고 첫 요청을 보냅니다. 로컬 기본 Codex/OCX 경로를 사용하며 Web GPT 하위 대화를 만들지는 않습니다.',
    inputSchema: {
      ...leaseFields,
      prompt: z.string().min(1).max(50_000),
      reasoning_effort: z.enum(['low', 'medium', 'high', 'xhigh']).default('high')
    },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true }
  }, withLease(async (input, { workspace }) => {
    if (config.nativeGateways?.codex?.tasks === false) throw new Error('Codex 작업 위임이 이 AICC 구성에서 꺼져 있습니다.');
    const job = await startCodexExec(config, {
      workspaceRoot: workspace.root,
      runtimeRoot,
      prompt: input.prompt,
      reasoningEffort: input.reasoning_effort
    });
    return response({
      ok: true,
      task_id: job.taskId,
      status: 'started',
      note: '작업은 분리된 로컬 Codex exec 프로세스에서 계속됩니다. aicc_codex_task_read로 진행 결과를 확인하세요.'
    });
  }));

  server.registerTool('aicc_codex_task_message', {
    title: 'Codex 작업에 후속 요청',
    description: '열린 워크스페이스의 기존 Codex 작업에 후속 요청을 보냅니다.',
    inputSchema: {
      ...leaseFields,
      task_id: z.string().uuid(),
      prompt: z.string().min(1).max(50_000),
      reasoning_effort: z.enum(['low', 'medium', 'high', 'xhigh']).default('high')
    },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true }
  }, withLease(async (input, { workspace }) => {
    await readScopedThread(config, workspace, input.task_id, false);
    const job = await startCodexExec(config, {
      workspaceRoot: workspace.root,
      runtimeRoot,
      taskId: input.task_id,
      prompt: input.prompt,
      reasoningEffort: input.reasoning_effort
    });
    return response({ ok: true, task_id: job.taskId, status: 'started' });
  }));

  server.registerTool('aicc_codex_task_archive', {
    title: 'Codex 작업 보관',
    description: '열린 워크스페이스의 완료된 Codex 작업을 보관합니다. 삭제하지 않으며 되돌릴 수 있습니다.',
    inputSchema: { ...leaseFields, task_id: z.string().uuid() },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false }
  }, withLease(async (input, { workspace }) => {
    await readScopedThread(config, workspace, input.task_id, false);
    await callCodexAppServer(config, 'thread/archive', { threadId: input.task_id });
    return response({ ok: true, task_id: input.task_id, archived: true });
  }));

  return server;
}

async function main() {
  const { configPath } = parseArguments(process.argv.slice(2));
  const config = loadConfig(configPath);
  const server = createWorkspaceMcpServer(config, { configPath, runtimeRoot: path.join(path.dirname(configPath), 'runtime') });
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`[aicc-workspace-mcp] ready workspaces=${config.workspaces.length}`);
}

function shutdown() {
  for (const session of processSessions.values()) {
    if (session.child && session.exitCode === null) session.child.kill('SIGTERM');
  }
}

process.once('SIGTERM', shutdown);
process.once('SIGINT', shutdown);

if (path.resolve(process.argv[1] || '') === path.resolve(fileURLToPath(import.meta.url))) {
  main().catch(error => {
    console.error(`[aicc-workspace-mcp] fatal: ${error.message}`);
    process.exitCode = 1;
  });
}

export const __testing = { workspaceId, validatePatchPaths, gitSummary, blockedNames, componentRoot };
