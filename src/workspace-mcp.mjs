import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { workspacePublicationStatus } from './workspace-publish.mjs';

const ignoredDirectories = new Set([
  '.git', '.next', '.cache', '.venv', 'node_modules', 'dist', 'build', 'coverage',
  'Library', 'backups', 'quickshare'
]);

export const workspaceMcpRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function realDirectory(candidate) {
  try {
    const stat = fs.lstatSync(candidate);
    if (!stat.isDirectory() || stat.isSymbolicLink()) return null;
    return fs.realpathSync(candidate);
  } catch { return null; }
}

export function discoverGitWorkspaces(baseRoot, options = {}) {
  const root = realDirectory(baseRoot);
  if (!root) throw new Error(`워크스페이스 검색 루트를 찾지 못했습니다: ${baseRoot}`);
  const maxDepth = options.maxDepth ?? 8;
  const workspaces = [];
  const visit = (directory, depth) => {
    if (fs.existsSync(path.join(directory, '.git'))) workspaces.push(directory);
    if (depth >= maxDepth) return;
    let entries = [];
    try { entries = fs.readdirSync(directory, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      if (!entry.isDirectory() || entry.isSymbolicLink() || ignoredDirectories.has(entry.name)) continue;
      if (entry.name.startsWith('.') && entry.name !== '.openai') continue;
      visit(path.join(directory, entry.name), depth + 1);
    }
  };
  visit(root, 0);
  return [...new Set(workspaces.map(item => fs.realpathSync(item)))].sort();
}

export function workspaceMcpPaths(options = {}) {
  const stateRoot = options.stateRoot
    ?? process.env.AICC_STATE_ROOT?.trim()
    ?? path.join(os.homedir(), '.ai-control-center');
  const root = path.join(stateRoot, 'workspace-mcp');
  return {
    root,
    config: path.join(root, 'config.json'),
    registry: path.join(root, 'workspace-registry.json'),
    logs: path.join(root, 'logs'),
    backups: path.join(root, 'backups'),
    runtime: path.join(root, 'runtime')
  };
}

function stableAlias(root, projectsRoot, used) {
  const relative = path.relative(projectsRoot, root).split(path.sep).filter(Boolean);
  const base = (relative.at(-1) || path.basename(root))
    .normalize('NFKC')
    .toLocaleLowerCase('en-US')
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'workspace';
  let alias = base;
  if (used.has(alias)) {
    const group = relative.slice(-2, -1)[0]?.normalize('NFKC').toLocaleLowerCase('en-US')
      .replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
    alias = group ? `${group}-${base}` : base;
  }
  if (used.has(alias)) alias = `${alias}-${createHash('sha256').update(root).digest('hex').slice(0, 8)}`;
  used.add(alias);
  return alias;
}

export function buildWorkspaceMcpConfig(options = {}) {
  const projectsRoot = fs.realpathSync(options.projectsRoot ?? process.env.AICC_WORKSPACE_PROJECTS_ROOT?.trim() ?? path.join(os.homedir(), 'dev', 'projects'));
  const allowedRoots = (options.allowedRoots ?? discoverGitWorkspaces(projectsRoot)).map(root => fs.realpathSync(root));
  if (!allowedRoots.length) throw new Error('등록할 Git 워크스페이스가 없습니다.');
  const used = new Set();
  const workspaces = allowedRoots.map(root => ({
    alias: stableAlias(root, projectsRoot, used),
    label: path.basename(root),
    root
  }));
  const preferredDefault = options.defaultRoot ? fs.realpathSync(options.defaultRoot) : null;
  const defaultWorkspace = workspaces.find(item => item.root === preferredDefault)?.alias
    ?? workspaces.find(item => item.label === 'AICC')?.alias
    ?? workspaces[0].alias;
  return {
    schemaVersion: 2,
    generatedAt: new Date().toISOString(),
    projectsRoot,
    defaultWorkspace,
    workspaces,
    permissions: {
      files: 'read-write',
      commands: true,
      network: options.network !== false,
      maxReadBytes: Number(options.maxReadBytes ?? 1_048_576),
      maxOutputBytes: Number(options.maxOutputBytes ?? 262_144),
      commandTimeoutMs: Number(options.commandTimeoutMs ?? 120_000)
    },
    transport: { mode: 'secure-mcp-tunnel', runtimeAlias: 'aicc-workspace' },
    skillRoots: [path.join(workspaceMcpRoot, 'guidance', 'skills')],
    executionBoundary: {
      modelInference: 'chatgpt-web-only',
      codexTaskDelegation: false,
      desktopBrowserAndComputerUse: 'codex-web-gpt-full-harness-only',
      externalWorkspaceTools: 'workspace-files-terminal-and-aicc-skills'
    }
  };
}

function atomicJson(file, value, mode = 0o600) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode });
  fs.renameSync(temporary, file);
  if (process.platform !== 'win32') fs.chmodSync(file, mode);
}

export function configureWorkspaceMcp(options = {}) {
  const paths = workspaceMcpPaths(options);
  const config = buildWorkspaceMcpConfig(options);
  if (fs.existsSync(paths.config)) {
    fs.mkdirSync(paths.backups, { recursive: true, mode: 0o700 });
    const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
    fs.copyFileSync(paths.config, path.join(paths.backups, `config.${stamp}.json`));
  }
  atomicJson(paths.config, config);
  return { ok: true, configPath: paths.config, workspaceCount: config.workspaces.length, config };
}

export function readWorkspaceMcpConfig(options = {}) {
  const paths = workspaceMcpPaths(options);
  if (!fs.existsSync(paths.config)) return null;
  const parsed = JSON.parse(fs.readFileSync(paths.config, 'utf8'));
  if (parsed.schemaVersion !== 2 || !Array.isArray(parsed.workspaces)) {
    throw new Error('Workspace MCP 설정 형식이 올바르지 않습니다. 다시 구성해야 합니다.');
  }
  return parsed;
}

export function workspaceMcpCommand(config, options = {}) {
  const node = options.nodeExecutable ?? process.execPath;
  const server = options.serverPath ?? path.join(workspaceMcpRoot, 'components', 'workspace-mcp', 'server.mjs');
  return { executable: node, args: [server, '--config', options.configPath ?? workspaceMcpPaths(options).config], cwd: workspaceMcpRoot };
}

async function defaultTunnelProbe(options = {}) {
  if ((options.platform ?? process.platform) !== 'darwin') return { running: false, healthy: false, ready: false, reason: 'macOS 전용 자동 시작' };
  const label = 'com.agenticlab.aicc-workspace-tunnel';
  const uid = typeof process.getuid === 'function' ? process.getuid() : null;
  const printed = uid === null ? { status: 1 } : spawnSync('launchctl', ['print', `gui/${uid}/${label}`], { encoding: 'utf8', timeout: 3_000 });
  const running = printed.status === 0 && /\bstate = running\b/.test(printed.stdout ?? '');
  const healthFile = path.join(os.homedir(), 'Library', 'Application Support', 'tunnel-client', 'health', 'aicc-workspace.url');
  if (!running || !fs.existsSync(healthFile)) return { running, healthy: false, ready: false, reason: running ? 'health URL 없음' : 'launchd 중지' };
  const baseUrl = fs.readFileSync(healthFile, 'utf8').trim();
  const probe = async suffix => {
    try {
      const response = await fetch(`${baseUrl}${suffix}`, { signal: AbortSignal.timeout(options.timeoutMs ?? 2_000), cache: 'no-store' });
      return response.ok;
    } catch { return false; }
  };
  const [healthy, ready] = await Promise.all([probe('/healthz'), probe('/readyz')]);
  return { running, healthy, ready, reason: ready ? null : '터널 준비 안 됨' };
}

export async function workspaceMcpStatus(options = {}) {
  const paths = workspaceMcpPaths(options);
  let config;
  try { config = readWorkspaceMcpConfig(options); }
  catch (error) {
    return { id: 'workspace-mcp', label: 'AICC Workspace MCP', state: 'attention', detail: error.message };
  }
  if (!config) {
    return { id: 'workspace-mcp', label: 'AICC Workspace MCP', state: 'unavailable', detail: '아직 구성되지 않았습니다.', optional: false };
  }
  const missing = config.workspaces.filter(item => !realDirectory(item.root));
  const command = workspaceMcpCommand(config, { ...options, configPath: paths.config });
  const serverExists = fs.existsSync(command.args[0]);
  const dependencyCheck = spawnSync(command.executable, ['-e', "import('@modelcontextprotocol/sdk/server/mcp.js')"], {
    cwd: command.cwd,
    encoding: 'utf8',
    timeout: 5_000
  });
  const tunnel = await (options.tunnelProbe ?? defaultTunnelProbe)(options);
  const publication = workspacePublicationStatus(options);
  const ready = missing.length === 0 && serverExists && dependencyCheck.status === 0 && tunnel.ready;
  return {
    id: 'workspace-mcp',
    label: 'AICC Workspace MCP',
    state: ready ? 'ready' : 'attention',
    detail: missing.length
      ? `등록 경로 ${missing.length}개를 찾지 못했습니다.`
      : !serverExists
        ? '고정 STDIO 서버를 찾지 못했습니다.'
        : dependencyCheck.status !== 0
          ? 'MCP 런타임 의존성을 불러오지 못했습니다.'
          : !tunnel.running
            ? `${config.workspaces.length}개 워크스페이스 · Tunnel 자동 시작 중지`
            : !tunnel.ready
              ? `${config.workspaces.length}개 워크스페이스 · Tunnel 연결 대기`
              : `${config.workspaces.length}개 워크스페이스 · Secure Tunnel 준비됨`,
    configured: true,
    serverReady: ready,
    workspaceCount: config.workspaces.length,
    missingCount: missing.length,
    permissions: config.permissions,
    executionBoundary: config.executionBoundary ?? null,
    transport: config.transport,
    tunnel: { running: tunnel.running, healthy: tunnel.healthy, ready: tunnel.ready },
    publication: {
      needsPublish: publication.needsPublish,
      toolCount: publication.manifest.toolCount,
      readToolCount: publication.manifest.readToolCount,
      writeToolCount: publication.manifest.writeToolCount,
      tools: publication.manifest.tools,
      published: publication.published,
      manageUrl: publication.manageUrl
    },
    configPath: paths.config,
    command
  };
}
