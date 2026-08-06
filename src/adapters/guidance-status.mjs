import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const defaultRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

function parseJsonOutput(stdout) {
  const text = String(stdout ?? '').trim();
  if (!text) throw new Error('지침 검사 결과가 비어 있습니다.');
  const lines = text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try { return JSON.parse(lines[index]); } catch { /* continue */ }
  }
  try { return JSON.parse(text); }
  catch { throw new Error('지침 검사 JSON을 읽을 수 없습니다.'); }
}

export function guidanceStatus(options = {}) {
  const root = options.root ?? defaultRoot;
  const runner = options.spawnSync ?? spawnSync;
  const executable = options.executable ?? 'pwsh';
  const script = path.join(root, 'tools/platform/test/Test-AiccGuidance.ps1');
  const result = runner(executable, ['-NoProfile', '-File', script, '-AiccRoot', root, '-AsJson'], {
    cwd: root,
    env: options.env ?? process.env,
    encoding: 'utf8',
    windowsHide: true,
    timeout: options.timeoutMs ?? 30_000,
    maxBuffer: 2 * 1024 * 1024
  });
  if (result.error?.code === 'ENOENT') {
    return {
      id: 'guidance', label: '지침과 스킬', state: 'unavailable', optional: false,
      detail: 'PowerShell 7을 찾지 못해 정본 정합성을 확인하지 못했습니다.'
    };
  }
  try {
    const report = parseJsonOutput(result.stdout);
    const failed = Number(report.failed_count ?? 0);
    const skills = report.checks?.find?.(check => check.name === 'skills')?.result;
    const directives = report.checks?.find?.(check => check.name === 'directives')?.result;
    const agents = report.checks?.find?.(check => check.name === 'agents')?.result;
    const issueCount = Number(skills?.deployment_issue_count ?? 0)
      + Number(skills?.manifest_issue_count ?? 0)
      + Number(agents?.deployment_issue_count ?? 0)
      + Number(agents?.manifest_issue_count ?? 0)
      + Number(directives?.failed_count ?? 0);
    return {
      id: 'guidance',
      label: '지침·스킬·Codex 에이전트',
      state: failed === 0 && result.status === 0 ? 'ready' : 'attention',
      detail: failed === 0 && result.status === 0
        ? `정본과 배포본이 일치합니다 · 스킬 ${skills?.central_skill_count ?? 0}개 · 에이전트 ${agents?.agent_count ?? 0}개`
        : `정본과 배포본 불일치 ${Math.max(failed, issueCount)}건`,
      checks: Number(report.check_count ?? 0),
      failed,
      skillCount: Number(skills?.central_skill_count ?? 0),
      deploymentIssues: Number(skills?.deployment_issue_count ?? 0),
      manifestIssues: Number(skills?.manifest_issue_count ?? 0),
      agentCount: Number(agents?.agent_count ?? 0),
      agentDeploymentIssues: Number(agents?.deployment_issue_count ?? 0),
      agentManifestIssues: Number(agents?.manifest_issue_count ?? 0)
    };
  } catch (error) {
    return {
      id: 'guidance', label: '지침·스킬·Codex 에이전트', state: 'attention', optional: false,
      detail: `정본 검사를 완료하지 못했습니다: ${error.message}`
    };
  }
}
