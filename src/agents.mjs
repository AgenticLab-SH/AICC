import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';

export const agentManagementRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const agentManifestName = '.aicc-codex-agents-manifest.json';

const manifestOwner = 'ai-control-center';
const manifestTarget = 'codex-agents';
const secretAssignment = /^\s*(?:api[-_]?key|access[-_]?token|refresh[-_]?token|password|secret|credential|cookie)\s*=/im;
const privateKey = /-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----/;

function absolute(value) {
  return path.resolve(String(value));
}

export function resolveAgentRoots(options = {}) {
  const aiccRoot = absolute(options.aiccRoot ?? agentManagementRoot);
  const home = absolute(options.home ?? os.homedir());
  const targetRoot = absolute(options.targetRoot ?? path.join(home, '.codex', 'agents'));
  const stateRoot = absolute(options.stateRoot ?? path.join(home, '.ai-control-center'));
  const backupRoot = absolute(options.backupRoot ?? (
    options.targetRoot
      ? path.join(path.dirname(targetRoot), '.aicc-codex-agent-backups')
      : path.join(stateRoot, 'backups', 'codex-agents')
  ));
  return {
    aiccRoot,
    sourceRoot: absolute(options.sourceRoot ?? path.join(aiccRoot, 'guidance', 'agents', 'codex')),
    targetRoot,
    backupRoot,
    manifestPath: absolute(options.manifestPath ?? path.join(targetRoot, agentManifestName))
  };
}

function fromPosix(root, relative) {
  return path.join(root, ...relative.split('/'));
}

function validateRelativeFile(relative) {
  if (!relative || relative.includes('\\') || path.posix.isAbsolute(relative)) {
    throw new Error(`에이전트 manifest 경로가 올바르지 않습니다: ${relative || '(빈 경로)'}`);
  }
  const normalized = path.posix.normalize(relative);
  if (normalized !== relative || normalized === '..' || normalized.startsWith('../')) {
    throw new Error(`에이전트 manifest 경로가 관리 루트를 벗어납니다: ${relative}`);
  }
  if (relative === agentManifestName) {
    throw new Error(`에이전트 manifest가 자기 자신을 관리할 수 없습니다: ${relative}`);
  }
  return relative;
}

function listFiles(root, { required = false } = {}) {
  let rootStat;
  try {
    rootStat = fs.lstatSync(root);
  } catch (error) {
    if (error.code === 'ENOENT' && !required) return [];
    if (error.code === 'ENOENT') throw new Error(`Codex 에이전트 정본 디렉터리가 없습니다: ${root}`);
    throw error;
  }
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) {
    throw new Error(`Codex 에이전트 루트는 실제 디렉터리여야 합니다: ${root}`);
  }

  const files = [];
  const visit = (directory, prefix = '') => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      const fullPath = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) {
        throw new Error(`심볼릭 링크 에이전트 파일은 관리하지 않습니다: ${relative}`);
      }
      if (entry.isDirectory()) visit(fullPath, relative);
      else if (entry.isFile()) files.push(validateRelativeFile(relative));
      else throw new Error(`일반 파일이 아닌 에이전트 항목은 관리하지 않습니다: ${relative}`);
    }
  };
  visit(root);
  return files.sort();
}

function listTargetEntries(root) {
  try {
    if (!fs.lstatSync(root).isDirectory()) return [];
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
  const files = [];
  const visit = (directory, prefix = '') => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory() && !entry.isSymbolicLink()) visit(path.join(directory, entry.name), relative);
      else files.push(relative);
    }
  };
  visit(root);
  return files.sort();
}

function assertSafeSource(relative, content) {
  const text = content.toString('utf8');
  if (secretAssignment.test(text) || privateKey.test(text)) {
    throw new Error(`에이전트 정본에는 인증정보나 비밀을 넣을 수 없습니다: ${relative}`);
  }
}

function readManagedTarget(root, relative) {
  const file = fromPosix(root, relative);
  try {
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink()) {
      throw new Error(`관리 대상은 실제 일반 파일이어야 합니다: ${relative}`);
    }
    return { exists: true, content: fs.readFileSync(file) };
  } catch (error) {
    if (error.code === 'ENOENT') return { exists: false, content: null };
    throw error;
  }
}

function expectedManifest(files) {
  return {
    schemaVersion: 1,
    owner: manifestOwner,
    target: manifestTarget,
    files: [...files].sort()
  };
}

function manifestBytes(manifest) {
  return Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
}

function readManifest(file) {
  let content;
  try {
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('manifest는 실제 일반 파일이어야 합니다.');
    content = fs.readFileSync(file);
  } catch (error) {
    if (error.code === 'ENOENT') return { exists: false, content: null, manifest: expectedManifest([]) };
    throw new Error(`Codex 에이전트 manifest를 읽을 수 없습니다: ${error.message}`);
  }

  let manifest;
  try {
    manifest = JSON.parse(content.toString('utf8'));
  } catch {
    throw new Error('Codex 에이전트 manifest JSON이 올바르지 않습니다. 소유권을 확인할 수 없어 중단합니다.');
  }
  if (
    manifest?.schemaVersion !== 1
    || manifest.owner !== manifestOwner
    || manifest.target !== manifestTarget
    || !Array.isArray(manifest.files)
    || manifest.files.some(fileName => typeof fileName !== 'string')
  ) {
    throw new Error('Codex 에이전트 manifest의 소유권 또는 형식이 올바르지 않아 중단합니다.');
  }
  const files = manifest.files.map(validateRelativeFile);
  if (new Set(files).size !== files.length) throw new Error('Codex 에이전트 manifest에 중복 경로가 있습니다.');
  return { exists: true, content, manifest: { ...manifest, files: files.sort() } };
}

function actionMessage(kind, relative) {
  if (kind === 'create') return `새 관리 에이전트를 배포합니다: ${relative}`;
  if (kind === 'update') return `기존 에이전트를 백업한 뒤 갱신합니다: ${relative}`;
  return `manifest가 소유한 이전 에이전트를 백업한 뒤 제거합니다: ${relative}`;
}

export function planCodexAgents(options = {}) {
  const roots = resolveAgentRoots(options);
  const sourceFiles = listFiles(roots.sourceRoot, { required: true });
  const previous = readManifest(roots.manifestPath);
  const previousOwned = new Set(previous.manifest.files);
  const currentOwned = new Set(sourceFiles);
  const files = [];
  const actions = [];

  for (const relative of sourceFiles) {
    const sourceContent = fs.readFileSync(fromPosix(roots.sourceRoot, relative));
    assertSafeSource(relative, sourceContent);
    const target = readManagedTarget(roots.targetRoot, relative);
    const state = !target.exists ? 'create' : sourceContent.equals(target.content) ? 'unchanged' : 'update';
    const record = { path: relative, state, message: state === 'unchanged' ? `정본과 일치합니다: ${relative}` : actionMessage(state, relative) };
    files.push(record);
    if (state !== 'unchanged') actions.push(record);
  }

  for (const relative of previous.manifest.files) {
    if (currentOwned.has(relative)) continue;
    const target = readManagedTarget(roots.targetRoot, relative);
    if (target.exists) {
      const record = { path: relative, state: 'remove', message: actionMessage('remove', relative) };
      files.push(record);
      actions.push(record);
    }
  }

  const nextManifest = expectedManifest(sourceFiles);
  const nextManifestContent = manifestBytes(nextManifest);
  const manifestMatches = previous.exists && previous.content.equals(nextManifestContent);
  const targetEntries = listTargetEntries(roots.targetRoot);
  const unownedFiles = targetEntries.filter(relative => (
    relative !== path.relative(roots.targetRoot, roots.manifestPath).split(path.sep).join('/')
    && !currentOwned.has(relative)
    && !previousOwned.has(relative)
  ));
  const count = kind => actions.filter(action => action.state === kind).length;
  const inSync = actions.length === 0 && manifestMatches;
  const summary = {
    sourceFiles: sourceFiles.length,
    comparedFiles: sourceFiles.length,
    create: count('create'),
    update: count('update'),
    remove: count('remove'),
    unchanged: files.filter(file => file.state === 'unchanged').length,
    unownedPreserved: unownedFiles.length,
    manifestUpdate: !manifestMatches
  };
  return {
    ok: true,
    action: 'plan',
    inSync,
    ...roots,
    files,
    actions,
    unownedFiles,
    previousManifest: previous.manifest,
    nextManifest,
    summary,
    message: inSync
      ? `Codex 에이전트 ${sourceFiles.length}개가 정본과 일치합니다.`
      : `Codex 에이전트 변경 ${actions.length}개와 manifest ${manifestMatches ? '유지' : '갱신'}를 계획했습니다.`
  };
}

function ensureDirectory(directory, mode, forcePrivate = false) {
  fs.mkdirSync(directory, { recursive: true, mode });
  if (forcePrivate && process.platform !== 'win32') fs.chmodSync(directory, mode);
}

function atomicWrite(file, content, mode = 0o600, privateParent = false) {
  ensureDirectory(path.dirname(file), privateParent ? 0o700 : 0o755, privateParent);
  const temporary = path.join(path.dirname(file), `.${path.basename(file)}.aicc-${process.pid}-${randomBytes(6).toString('hex')}.tmp`);
  let descriptor;
  try {
    descriptor = fs.openSync(temporary, 'wx', mode);
    fs.writeFileSync(descriptor, content);
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = undefined;
    fs.renameSync(temporary, file);
    if (process.platform !== 'win32') fs.chmodSync(file, mode);
  } catch (error) {
    if (descriptor !== undefined) fs.closeSync(descriptor);
    fs.rmSync(temporary, { force: true });
    throw error;
  }
}

function backupId(now) {
  const date = typeof now === 'function' ? now() : now ?? new Date();
  if (!(date instanceof Date) || Number.isNaN(date.valueOf())) throw new Error('백업 시각이 올바르지 않습니다.');
  return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
}

function createBackup(plan, options) {
  const candidates = plan.actions.filter(action => action.state === 'update' || action.state === 'remove');
  const includeManifest = plan.summary.manifestUpdate && fs.existsSync(plan.manifestPath);
  if (candidates.length === 0 && !includeManifest) return null;

  ensureDirectory(plan.backupRoot, 0o700, true);
  const base = backupId(options.now);
  let directory = path.join(plan.backupRoot, base);
  for (let suffix = 1; fs.existsSync(directory); suffix += 1) directory = path.join(plan.backupRoot, `${base}-${suffix}`);
  ensureDirectory(directory, 0o700, true);

  for (const action of candidates) {
    const target = readManagedTarget(plan.targetRoot, action.path);
    if (!target.exists) throw new Error(`백업 직전에 관리 대상이 사라졌습니다: ${action.path}`);
    atomicWrite(fromPosix(directory, action.path), target.content, 0o600, true);
  }
  if (includeManifest) atomicWrite(path.join(directory, agentManifestName), fs.readFileSync(plan.manifestPath), 0o600, true);
  return directory;
}

export function deployCodexAgents(options = {}) {
  const plan = planCodexAgents(options);
  if (plan.inSync) return { ...plan, action: 'deploy', changed: false, backupPath: null, message: 'Codex 에이전트가 이미 정본과 일치하여 변경하지 않았습니다.' };

  const backupPath = createBackup(plan, options);
  for (const action of plan.actions.filter(item => item.state === 'create' || item.state === 'update')) {
    atomicWrite(
      fromPosix(plan.targetRoot, action.path),
      fs.readFileSync(fromPosix(plan.sourceRoot, action.path)),
      0o600
    );
  }
  for (const action of plan.actions.filter(item => item.state === 'remove')) {
    fs.unlinkSync(fromPosix(plan.targetRoot, action.path));
  }
  atomicWrite(plan.manifestPath, manifestBytes(plan.nextManifest), 0o600);

  return {
    ...plan,
    action: 'deploy',
    changed: true,
    backupPath,
    message: `Codex 에이전트 변경 ${plan.actions.length}개를 배포했고 unowned 파일 ${plan.summary.unownedPreserved}개를 보존했습니다.${backupPath ? ' 변경 전 파일은 소유자 전용 백업에 저장했습니다.' : ''}`
  };
}

export function checkCodexAgents(options = {}) {
  const plan = planCodexAgents(options);
  const issues = plan.actions.map(action => action.message);
  if (plan.summary.manifestUpdate) issues.push('Codex 에이전트 manifest가 정본의 전체 파일 목록과 일치하지 않습니다.');
  return {
    ...plan,
    action: 'check',
    ok: issues.length === 0,
    issues,
    message: issues.length === 0
      ? `Codex 에이전트 ${plan.summary.comparedFiles}개와 manifest가 모두 일치합니다.`
      : `Codex 에이전트 검사에서 불일치 ${issues.length}개를 찾았습니다.`
  };
}

export function codexAgentsStatus(options = {}) {
  try {
    const checked = checkCodexAgents(options);
    return {
      ok: checked.ok,
      action: 'status',
      state: checked.ok ? 'ready' : 'drift',
      sourceRoot: checked.sourceRoot,
      targetRoot: checked.targetRoot,
      backupRoot: checked.backupRoot,
      summary: checked.summary,
      issues: checked.issues,
      message: checked.ok ? 'Codex 에이전트 배포 상태가 정상입니다.' : 'Codex 에이전트 배포 상태에 정본과의 차이가 있습니다.'
    };
  } catch (error) {
    return { ok: false, action: 'status', state: 'error', summary: null, issues: [error.message], message: `Codex 에이전트 상태를 확인할 수 없습니다: ${error.message}` };
  }
}

export const planAgents = planCodexAgents;
export const deployAgents = deployCodexAgents;
export const checkAgents = checkCodexAgents;
export const agentsStatus = codexAgentsStatus;
export const getAgentsStatus = codexAgentsStatus;
export const statusAgents = codexAgentsStatus;
export const statusCodexAgents = codexAgentsStatus;
