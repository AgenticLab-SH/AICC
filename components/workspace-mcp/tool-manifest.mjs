import { createHash } from 'node:crypto';

export const WORKSPACE_MCP_TOOLS = Object.freeze([
  { name: 'aicc_workspace_list', title: '워크스페이스 목록', mode: 'read' },
  { name: 'aicc_workspace_open', title: '워크스페이스 열기', mode: 'read' },
  { name: 'aicc_workspace_info', title: '워크스페이스 개요', mode: 'read' },
  { name: 'aicc_workspace_read', title: '파일 읽기', mode: 'read' },
  { name: 'aicc_workspace_read_many', title: '여러 파일 읽기', mode: 'read' },
  { name: 'aicc_workspace_search', title: '파일·본문 검색', mode: 'read' },
  { name: 'aicc_workspace_changes', title: 'Git 변경 검토', mode: 'read' },
  { name: 'aicc_skill_inventory', title: 'AICC 스킬 목록', mode: 'read' },
  { name: 'aicc_skill_read', title: 'AICC 스킬 읽기', mode: 'read' },
  { name: 'aicc_workspace_apply_patch', title: '패치 적용', mode: 'write' },
  { name: 'aicc_workspace_exec', title: '명령 실행', mode: 'write' },
  { name: 'aicc_workspace_write_stdin', title: '명령 입력·폴링', mode: 'write' },
  { name: 'aicc_workspace_process_stop', title: '명령 중지', mode: 'write' }
]);

export function workspaceToolSnapshot() {
  const tools = WORKSPACE_MCP_TOOLS.map(tool => ({ ...tool }));
  const hash = createHash('sha256').update(JSON.stringify(tools)).digest('hex');
  return {
    schemaVersion: 1,
    toolCount: tools.length,
    readToolCount: tools.filter(tool => tool.mode === 'read').length,
    writeToolCount: tools.filter(tool => tool.mode === 'write').length,
    hash,
    tools
  };
}
