#!/usr/bin/env node
import { recordWorkspacePublication, workspacePublicationStatus } from '../../../src/workspace-publish.mjs';
import { workspaceMcpStatus } from '../../../src/workspace-mcp.mjs';

const args = process.argv.slice(2);
const json = args.includes('--json');
const markIndex = args.indexOf('--mark-published');
const appName = markIndex >= 0 ? args[markIndex + 1] : null;

const runtime = await workspaceMcpStatus();
const publication = appName
  ? recordWorkspacePublication({ appName })
  : workspacePublicationStatus();
const result = {
  ok: runtime.state === 'ready',
  runtime: {
    state: runtime.state,
    detail: runtime.detail,
    workspaceCount: runtime.workspaceCount ?? 0,
    tunnelReady: runtime.tunnel?.ready === true
  },
  publication: {
    needsPublish: publication.needsPublish,
    toolCount: publication.manifest.toolCount,
    readToolCount: publication.manifest.readToolCount,
    writeToolCount: publication.manifest.writeToolCount,
    manifestHash: publication.manifest.hash,
    tools: publication.manifest.tools,
    published: publication.published,
    manageUrl: publication.manageUrl
  },
  nextSteps: runtime.state === 'ready' ? [
    'ChatGPT Business의 앱 관리 화면에서 기존 AICC Workspace 초안을 열거나 새로 만듭니다.',
    'Secure MCP Tunnel을 선택하고 도구 목록을 다시 불러옵니다.',
    `읽기 ${publication.manifest.readToolCount}개와 쓰기 ${publication.manifest.writeToolCount}개, 총 ${publication.manifest.toolCount}개인지 확인합니다.`,
    '테스트 호출 후 게시하고, 실제 ChatGPT 대화에서 새 도구가 보이는지 검증합니다.',
    '검증이 끝난 뒤 이 스크립트를 --mark-published "AICC Workspace"로 다시 실행해 로컬 스냅샷을 기록합니다.'
  ] : ['Secure Tunnel과 로컬 MCP 런타임을 먼저 정상화합니다.']
};

if (json) console.log(JSON.stringify(result, null, 2));
else {
  console.log(`AICC Workspace 게시 사전검사: ${result.ok ? '준비됨' : '확인 필요'}`);
  console.log(result.runtime.detail);
  console.log(`도구 ${result.publication.toolCount}개 · 다시 게시 ${result.publication.needsPublish ? '필요' : '불필요'}`);
  console.log(result.publication.manageUrl);
}
process.exitCode = result.ok ? 0 : 1;
