const groups = Object.freeze([
  { id: 'start', label: '시작' },
  { id: 'assistants', label: 'AI 도구' },
  { id: 'workflows', label: '작업 자동화' },
  { id: 'system', label: '설정과 점검' }
]);

const items = Object.freeze([
  {
    id: 'dashboard', group: 'start', title: '관리 화면 열기',
    description: '상태, 계정, OCX와 모든 도구를 브라우저에서 관리합니다.',
    command: 'aicc open', mode: 'command', featured: true, keywords: ['web', 'browser', 'dashboard', '웹', '화면']
  },
  {
    id: 'status', group: 'start', title: '전체 상태 확인',
    description: '연결된 구성 요소와 주의가 필요한 항목을 한 번에 확인합니다.',
    command: 'aicc status', mode: 'command', taskId: 'status', featured: true, keywords: ['health', 'ready', '상태']
  },
  {
    id: 'auth-portal', group: 'start', title: '웹 로그인 전달 포털',
    description: '다른 기기에서 공식 로그인을 완료하고 이 Mac의 지정 계정으로 안전하게 가져옵니다.',
    command: 'aicc account portal open', mode: 'command', featured: true,
    keywords: ['login', 'auth', 'portal', 'token', '로그인', '인증', '전달']
  },
  {
    id: 'codex', group: 'assistants', title: 'GPT 코딩 도구 시작',
    description: '현재 폴더에서 GPT CLI를 시작합니다.',
    command: 'codex', mode: 'external', featured: true, keywords: ['codex', 'gpt', '코딩']
  },
  {
    id: 'claude', group: 'assistants', title: 'Claude Code 시작',
    description: '현재 폴더에서 Claude Code를 시작합니다.',
    command: 'claude', mode: 'external', keywords: ['anthropic', 'claude', '클로드']
  },
  {
    id: 'ocx', group: 'assistants', title: 'OCX 모델 도구',
    description: 'OCX의 대화형 모델·연결 도구를 엽니다.',
    command: 'ocx', mode: 'external', keywords: ['opencodex', 'model', 'provider', '모델']
  },
  {
    id: 'web-gpt', group: 'assistants', title: 'Web GPT 모델 브리지',
    description: 'ChatGPT Web를 Codex 모델로 사용하는 브리지의 상태와 모델 목록을 관리합니다.',
    command: 'open -a "Codex Web GPT"', mode: 'external', appId: 'web-gpt', featured: true,
    webSection: 'web-gpt', keywords: ['chatgpt web', 'web gpt', 'bridge', 'model', '웹 지피티', '모델 브리지']
  },
  {
    id: 'accounts', group: 'assistants', title: 'GPT 계정 관리',
    description: 'AICC 안에서 계정 상태를 확인하고 기본 GPT Desktop 계정을 안전하게 바꿉니다.',
    command: 'aicc account', mode: 'command', webSection: 'accounts', keywords: ['account', 'cm', '계정', '전환']
  },
  {
    id: 'ocx-accounts', group: 'assistants', title: 'OCX 라우팅 계정',
    description: '새 작업에 사용할 OCX 계정 풀과 현재 선택을 확인합니다.',
    command: 'aicc account ocx list --json', mode: 'command', webSection: 'accounts', keywords: ['ocx', 'pool', 'account', '라우팅', '계정 풀']
  },
  {
    id: 'account-switch', group: 'assistants', title: '기본 GPT 계정 전환',
    description: '계정을 선택하고 변경 내용을 확인한 뒤 기본 GPT Desktop 계정을 바꿉니다.',
    command: 'aicc action preview account.switch', mode: 'action', action: 'account.switch',
    webSection: 'accounts', keywords: ['account', 'switch', '계정', '전환']
  },
  {
    id: 'ocx-account-switch', group: 'assistants', title: 'OCX 라우팅 계정 전환',
    description: '계정을 선택하고 변경 내용을 확인한 뒤 새 OCX 작업의 라우팅 계정을 바꿉니다.',
    command: 'aicc action preview ocx.account.use', mode: 'action', action: 'ocx.account.use',
    webSection: 'accounts', keywords: ['ocx', 'account', 'switch', 'pool', '라우팅', '계정 전환']
  },
  {
    id: 'ocx-account-import', group: 'assistants', title: '지정 계정 OAuth를 OCX에 적용',
    description: 'AICC에 지정된 최신 cm OAuth를 OCX native 계정 슬롯에 안전하게 추가하거나 갱신합니다.',
    command: 'aicc action preview ocx.account.import-cm', mode: 'action', action: 'ocx.account.import-cm',
    webSection: 'accounts', keywords: ['ocx', 'fbtt', 'import', 'auth', '계정', '가져오기', '재로그인']
  },
  {
    id: 'ocx-start', group: 'assistants', title: 'OCX 연결 시작',
    description: '변경 내용을 확인한 뒤 OCX 모델 연결을 시작합니다.',
    command: 'aicc action preview ocx.start', mode: 'action', action: 'ocx.start',
    webSection: 'controls', keywords: ['ocx', 'start', '시작', '연결']
  },
  {
    id: 'ocx-sync', group: 'assistants', title: 'OCX 모델 맞추기',
    description: 'OCX와 GPT의 모델 목록을 안전하게 다시 맞춥니다.',
    command: 'aicc action preview ocx.sync', mode: 'action', action: 'ocx.sync',
    webSection: 'controls', keywords: ['ocx', 'sync', 'model', '동기화', '모델']
  },
  {
    id: 'ocx-stop', group: 'assistants', title: 'OCX 연결 중지',
    description: '영향과 복구 방법을 확인한 뒤 OCX 연결을 중지합니다.',
    command: 'aicc action preview ocx.stop', mode: 'action', action: 'ocx.stop',
    webSection: 'controls', keywords: ['ocx', 'stop', '중지', '연결']
  },
  {
    id: 'workspace-mcp', group: 'workflows', title: 'ChatGPT 로컬 작업공간',
    description: 'Secure MCP Tunnel로 외부 ChatGPT에서 등록 프로젝트의 파일, 명령과 AICC 스킬을 직접 사용합니다.',
    command: 'aicc workspace status', mode: 'command', taskId: 'workspace.status', featured: true,
    keywords: ['chatgpt', 'mcp', 'workspace', 'secure tunnel', '로컬', '작업공간']
  },
  {
    id: 'workspace-publish', group: 'workflows', title: 'AICC Workspace 앱 게시 점검',
    description: '로컬 도구 스냅샷과 Secure Tunnel을 확인하고 ChatGPT Business 앱 갱신 여부를 판단합니다.',
    command: 'node tools/platform/chatgpt/Prepare-AiccWorkspacePublish.mjs --json', mode: 'command', taskId: 'workspace.publish-preflight',
    webSection: 'workspace', keywords: ['chatgpt', 'business', 'app', 'publish', 'mcp', '게시', '도구 갱신']
  },
  {
    id: 'codex-agents', group: 'workflows', title: 'Codex 하위 에이전트',
    description: 'AICC 정본에서 관리하는 Codex 하위 에이전트의 배포 상태를 확인합니다.',
    command: 'aicc agents status', mode: 'command', taskId: 'agents.status',
    keywords: ['codex', 'subagent', 'agent', '하위 에이전트', '정본']
  },
  {
    id: 'setup-check', group: 'system', title: '설치 상태 점검',
    description: '개인 설정과 필수 프로그램이 준비됐는지 확인합니다.',
    command: 'aicc setup --check', mode: 'command', taskId: 'setup.check', keywords: ['setup', 'install', '설치']
  },
  {
    id: 'cli-status', group: 'system', title: 'CLI 연결 점검',
    description: 'GPT CLI, Claude Code와 OCX 연결 상태를 확인합니다.',
    command: 'aicc cli status', mode: 'command', taskId: 'cli.status', keywords: ['cli', 'routing', '연결']
  },
  {
    id: 'cli-setup', group: 'system', title: '필요한 CLI 설치·연결',
    description: '검증된 고정 버전을 설치하고 OCX 연결을 준비합니다.',
    command: 'aicc cli setup --install-missing', mode: 'command', confirm: true, keywords: ['install', 'repair', '설치', '수리']
  },
  {
    id: 'guidance-check', group: 'system', title: '지침·스킬·에이전트 점검',
    description: 'AICC 정본과 Codex·Claude에 배포된 지침, 스킬과 Codex 에이전트가 일치하는지 검사합니다.',
    command: 'aicc guidance check', mode: 'command', taskId: 'guidance.check', keywords: ['skill', 'agents', 'directive', '스킬', '지침']
  },
  {
    id: 'guidance-manage', group: 'system', title: '지침 배포 관리',
    description: '변경 미리보기, Codex·Claude 배포와 사후 점검 명령을 안내합니다.',
    command: 'aicc guidance plan', mode: 'command', keywords: ['deploy', 'skill', '배포', '스킬']
  }
]);

export function toolCatalog() {
  return {
    schemaVersion: 1,
    groups: groups.map(group => ({ ...group })),
    items: items.map(item => ({ ...item, keywords: [...(item.keywords ?? [])] }))
  };
}

export function findCatalogItem(id) {
  return items.find(item => item.id === id) ?? null;
}

export function searchCatalog(query = '') {
  const normalized = String(query).trim().toLocaleLowerCase();
  if (!normalized) return items.map(item => ({ ...item }));
  const terms = normalized.split(/\s+/).filter(Boolean);
  return items.filter(item => {
    const haystack = [item.title, item.description, item.command, ...(item.keywords ?? [])]
      .join(' ').toLocaleLowerCase();
    return terms.every(term => haystack.includes(term));
  }).map(item => ({ ...item }));
}

export { groups as catalogGroups };
