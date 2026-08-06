import { componentPresentation, diagnosticPresentation } from './presentation.js';

const $ = selector => document.querySelector(selector);
const components = $('#components');
const roots = $('#stateRoots');
const summary = $('#summaryCount');
const summaryHint = $('#summaryHint');
const summaryRing = $('#summaryRing');
const summaryPercent = $('#summaryPercent');
const updatedAt = $('#updatedAt');
const componentUpdated = $('#componentUpdated');
const refresh = $('#refresh');
const accountSelector = $('#accountSelector');
const accountCards = $('#accountCards');
const switchAccount = $('#switchAccount');
const ocxAccountSelector = $('#ocxAccountSelector');
const ocxAccountCards = $('#ocxAccountCards');
const switchOcxAccount = $('#switchOcxAccount');
const actionMessage = $('#actionMessage');
const actionDialog = $('#actionDialog');
const dialogTitle = $('#dialogTitle');
const dialogImpact = $('#dialogImpact');
const dialogWarnings = $('#dialogWarnings');
const dialogRollback = $('#dialogRollback');
const confirmAction = $('#confirmAction');
const resultDialog = $('#resultDialog');
const resultTitle = $('#resultTitle');
const resultSummary = $('#resultSummary');
const resultHighlights = $('#resultHighlights');
const resultDetails = $('#resultDetails');
const resultOutput = $('#resultOutput');
const toolSearch = $('#toolSearch');
const searchResults = $('#searchResults');
const quickTools = $('#quickTools');
const toolFilters = $('#toolFilters');
const toolLibrary = $('#toolLibrary');
const openaiUsageGroups = $('#openaiUsageGroups');
const openaiUsageUpdated = $('#openaiUsageUpdated');
const openaiKeyState = $('#openaiKeyState');
const openaiGuardSummary = $('#openaiGuardSummary');
const openaiProviderState = $('#openaiProviderState');
const toggleOpenaiProvider = $('#toggleOpenaiProvider');
const openaiDefaultModel = $('#openaiDefaultModel');
const setOpenaiDefaultModel = $('#setOpenaiDefaultModel');
const openaiModelSummary = $('#openaiModelSummary');
const openaiModelFilters = $('#openaiModelFilters');
const openaiModelList = $('#openaiModelList');
const openaiActionMessage = $('#openaiActionMessage');
const ocxModules = $('#ocxModules');
const supportMessage = $('#supportMessage');
const copySupportPrompt = $('#copySupportPrompt');
const copySupportJson = $('#copySupportJson');
let confirmationToken = null;
let catalog = { groups: [], items: [] };
let statusData = null;
let activeFilter = 'all';
let activeArchitectureFilter = 'all';
let activeOpenaiModelFilter = 'current';
let searchIndex = 0;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[character]);
}

function iconFor(item) {
  const icons = { dashboard: '⌂', status: '✓', 'workspace-mcp': 'M', 'codex-agents': 'A', 'auth-portal': '↥', codex: 'G', claude: 'C', ocx: 'O', 'web-gpt': 'W', accounts: '◎', workflows: '↗', system: '◇' };
  return icons[item.id] || icons[item.group] || '·';
}

function taskButtonLabel(item) {
  if (item.taskId) return '지금 확인';
  if (item.href) return '화면 열기';
  if (item.appId) return '앱 열기';
  if (item.webSection) return '이동';
  return '명령 복사';
}

function toolCard(item, compact = false) {
  return `<article class="tool-card${compact ? ' compact' : ''}" data-tool-id="${escapeHtml(item.id)}">
    <span class="tool-icon" aria-hidden="true">${escapeHtml(iconFor(item))}</span>
    <div class="tool-copy"><div class="tool-heading"><h3>${escapeHtml(item.title)}</h3>${item.taskId ? '<span class="capability">바로 실행</span>' : ''}</div><p>${escapeHtml(item.description)}</p>${compact ? '' : `<code>${escapeHtml(item.command)}</code>`}</div>
    <button type="button" class="tool-run" data-tool-run="${escapeHtml(item.id)}">${taskButtonLabel(item)}</button>
  </article>`;
}

function renderCatalog() {
  quickTools.innerHTML = catalog.items.filter(item => item.featured).map(item => toolCard(item, true)).join('');
  toolFilters.innerHTML = [{ id: 'all', label: '전체' }, ...catalog.groups]
    .map(group => `<button type="button" class="filter-chip${activeFilter === group.id ? ' active' : ''}" data-filter="${escapeHtml(group.id)}" aria-pressed="${activeFilter === group.id}">${escapeHtml(group.label)}</button>`).join('');
  const items = activeFilter === 'all' ? catalog.items : catalog.items.filter(item => item.group === activeFilter);
  toolLibrary.innerHTML = items.map(item => toolCard(item)).join('');
}

function renderArchitectureFilter() {
  document.querySelectorAll('[data-architecture-filter]').forEach(button => {
    const selected = button.dataset.architectureFilter === activeArchitectureFilter;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  document.querySelectorAll('[data-map-groups]').forEach(element => {
    const groups = String(element.dataset.mapGroups || '').split(/\s+/).filter(Boolean);
    element.classList.toggle('is-dimmed', activeArchitectureFilter !== 'all' && !groups.includes(activeArchitectureFilter));
  });
}

function renderLiveMapState(id, ready, label, detail) {
  const pill = document.querySelector(`[data-live-state="${id}"]`);
  if (pill) {
    pill.textContent = label;
    pill.classList.toggle('ready', ready === true);
    pill.classList.toggle('attention', ready !== true);
  }
  document.querySelectorAll(`[data-live-detail="${id}"]`).forEach(element => { element.textContent = detail; });
}

function compactNumber(value) {
  if (!Number.isFinite(value)) return '–';
  return new Intl.NumberFormat('ko-KR', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return '–';
  const units = ['B', 'KB', 'MB', 'GB'];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toFixed(amount >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function percent(value) {
  return Number.isFinite(value) ? `${Math.round(value * 100)}%` : '–';
}

function routeLabel(route) {
  return ({ 'web-gpt': '통합 Web GPT 브리지', ocx: 'OCX 직접 연결', native: 'Native Codex', custom: '사용자 지정 경로' })[route] || '알 수 없는 경로';
}

function renderOcxModules(ocx) {
  const sections = ocx?.sections || {};
  const cards = [
    ['providers', 'Provider', sections.providers, `${sections.providers?.count ?? '–'}개 · 기본 ${sections.providers?.defaultProvider || '미확인'}`, (sections.providers?.items || []).map(item => item.name).filter(Boolean).join(' · ') || '목록 없음'],
    ['models', '모델 catalog', sections.models, `${sections.models?.count ?? '–'}개`, (sections.models?.byProvider || []).map(item => `${item.provider} ${item.count}`).join(' · ') || 'Provider별 수량 미확인'],
    ['usage', '30일 사용량', sections.usage, `${compactNumber(sections.usage?.requests)}회`, `token ${compactNumber(sections.usage?.totalTokens)} · 측정 ${percent(sections.usage?.coverageRatio)}`],
    ['runtime', '런타임·시작', sections.runtime, sections.runtime?.serviceRunning ? '서비스 실행 중' : '서비스 확인 필요', `RSS ${formatBytes(sections.runtime?.rssBytes)} · 작업 ${sections.runtime?.activeTurns ?? '–'}개`],
    ['agents', '하위 에이전트', sections.agents, `${sections.agents?.chosenCount ?? '–'}개 선택`, `모드 ${sections.agents?.multiAgentMode || '미확인'} · fallback ${sections.agents?.fallbackCount ?? '–'}`],
    ['combos', 'Combo', sections.combos, `${sections.combos?.count ?? '–'}개`, 'failover · round-robin 가상 모델'],
    ['storage', '저장소', sections.storage, formatBytes(sections.storage?.totalBytes), `${compactNumber(sections.storage?.fileCount)}개 파일 · 민감 경로 미표시`],
    ['diagnostics', '진단', sections.diagnostics, sections.diagnostics?.warningCount === 0 ? '경고 없음' : `${sections.diagnostics?.warningCount ?? '–'}개 경고`, `${sections.diagnostics?.groupCount ?? '–'}개 진단 그룹`],
    ['endpoints', '로컬 API', sections.endpoints, `${sections.endpoints?.endpointCount ?? '–'}개 endpoint`, sections.endpoints?.baseUrl || 'loopback endpoint 미확인']
  ];
  ocxModules.innerHTML = cards.map(([id, title, section, value, detail], index) => {
    const ready = section?.state === 'ready';
    return `<article class="ocx-module-card ${ready ? 'ready' : 'attention'}" data-ocx-module="${escapeHtml(id)}"><span>${String(index + 1).padStart(2, '0')}</span><div><strong>${escapeHtml(title)}</strong><b>${escapeHtml(value)}</b><small>${escapeHtml(detail)}</small></div><i>${ready ? '정상' : section?.state === 'timeout' ? '시간 초과' : '독립 실패'}</i></article>`;
  }).join('');
}

function matchingTools(query) {
  const terms = String(query).trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  return catalog.items.filter(item => {
    const haystack = [item.title, item.description, item.command, ...(item.keywords || [])].join(' ').toLocaleLowerCase();
    return terms.every(term => haystack.includes(term));
  }).slice(0, 8);
}

function renderSearch() {
  const matches = matchingTools(toolSearch.value);
  const hasQuery = Boolean(toolSearch.value.trim());
  searchIndex = Math.max(0, Math.min(searchIndex, Math.max(0, matches.length - 1)));
  searchResults.hidden = !hasQuery;
  toolSearch.setAttribute('aria-expanded', String(hasQuery));
  toolSearch.setAttribute('aria-activedescendant', matches.length ? `search-result-${searchIndex}` : '');
  searchResults.innerHTML = matches.length
    ? matches.map((item, index) => `<button id="search-result-${index}" type="button" role="option" aria-selected="${index === searchIndex}" class="${index === searchIndex ? 'selected' : ''}" data-search-index="${index}" data-tool-run="${escapeHtml(item.id)}"><span class="tool-icon">${escapeHtml(iconFor(item))}</span><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.description)}</small></span><code>${escapeHtml(item.command)}</code></button>`).join('')
    : '<p>일치하는 도구가 없습니다. 다른 표현으로 찾아보세요.</p>';
}

function showDiagnosticResult(item, taskResult) {
  const view = diagnosticPresentation(item.taskId, taskResult);
  resultDialog.className = `result-dialog ${view.tone}`;
  resultSummary.innerHTML = `<strong>${escapeHtml(view.headline)}</strong><span>${escapeHtml(view.detail)}</span>`;
  resultHighlights.innerHTML = view.highlights.map(highlight => `<div class="result-highlight ${escapeHtml(highlight.tone)}"><span>${escapeHtml(highlight.label)}</span><strong>${escapeHtml(highlight.value)}</strong></div>`).join('');
  resultHighlights.hidden = !view.highlights.length;
  resultDetails.open = false;
}

async function copyCommand(command) {
  try {
    await navigator.clipboard.writeText(command);
    actionMessage.textContent = `명령을 복사했습니다: ${command}`;
  } catch {
    window.prompt('아래 명령을 복사하세요.', command);
  }
}

async function runTask(item) {
  resultDialog.showModal();
  resultDialog.setAttribute('aria-busy', 'true');
  resultDialog.className = 'result-dialog loading';
  resultTitle.textContent = item.title;
  resultSummary.innerHTML = '<strong>안전한 조회 작업을 실행하고 있습니다.</strong><span>완료될 때까지 이 창을 열어 두세요.</span>';
  resultHighlights.hidden = true;
  resultHighlights.innerHTML = '';
  resultDetails.open = true;
  resultOutput.textContent = '확인 중…';
  try {
    const result = await postJson('/api/tasks/run', { taskId: item.taskId }, { acceptFindings: true });
    showDiagnosticResult(item, result);
    resultOutput.textContent = typeof result.result === 'string' ? result.result : JSON.stringify(result.result, null, 2);
    if (item.taskId === 'status') await loadStatus();
  } catch (error) {
    resultDialog.className = 'result-dialog attention';
    resultSummary.innerHTML = '<strong>작업을 완료하지 못했습니다.</strong><span>아래 기술 정보를 확인해 주세요.</span>';
    resultHighlights.hidden = true;
    resultDetails.open = true;
    resultOutput.textContent = error.message;
  } finally {
    resultDialog.setAttribute('aria-busy', 'false');
  }
}

async function activateTool(item) {
  searchResults.hidden = true;
  toolSearch.setAttribute('aria-expanded', 'false');
  if (item.taskId) return runTask(item);
  if (item.id === 'auth-portal') {
    const opened = window.open('', '_blank');
    try {
      const result = await postJson('/api/apps/open', { appId: item.id });
      if (opened) opened.location = result.url;
      else window.location.href = result.url;
    } catch (error) {
      opened?.close();
      actionMessage.textContent = error.message;
    }
    return;
  }
  if (item.appId) {
    try {
      await postJson('/api/apps/open', { appId: item.appId });
      actionMessage.textContent = `${item.title}을(를) 열었습니다.`;
    } catch (error) { actionMessage.textContent = error.message; }
    return;
  }
  if (item.href) return window.open(item.href, '_blank', 'noopener');
  if (item.webSection) {
    document.querySelector(`#${item.webSection}`)?.scrollIntoView({ behavior: 'smooth' });
    if (item.action && item.action !== 'account.switch') return previewAction(item.action);
    return;
  }
  return copyCommand(item.command);
}

async function postJson(path, body, options = {}) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok || (!data.ok && !options.acceptFindings)) {
    throw new Error(data.error || data.message || `HTTP ${response.status}`);
  }
  return data;
}

function fillAccounts(data) {
  const accountComponent = data.components.find(component => component.id === 'accounts');
  const accounts = accountComponent?.accounts ?? [];
  accountSelector.innerHTML = accounts.length
    ? accounts.map(account => `<option value="${escapeHtml(account.account)}" ${account.expired || account.is_app_active ? 'disabled' : ''}>${escapeHtml(account.account)}${account.is_app_active ? ' (현재)' : account.expired ? ' (만료)' : ''}</option>`).join('')
    : '<option value="">전환 가능한 계정 없음</option>';
  const firstAvailable = accounts.find(account => !account.expired && !account.is_app_active);
  accountSelector.value = firstAvailable?.account ?? '';
  switchAccount.disabled = !firstAvailable;
  accountCards.innerHTML = accounts.length ? accounts.map(account => {
    const available = account.quota?.long_remaining_percent;
    const remaining = Number.isFinite(available) ? `${available}% 남음` : '한도 미확인';
    return `<article class="account-card${account.is_app_active ? ' active' : ''}"><div><span class="avatar">${escapeHtml(String(account.account || '?').slice(0, 1).toUpperCase())}</span><span><strong>${escapeHtml(account.account)}</strong><small>${escapeHtml(account.plan || '요금제 미확인')} · ${escapeHtml(remaining)}</small></span></div><span class="account-state">${account.is_app_active ? '현재 계정' : account.expired ? '갱신 필요' : '사용 가능'}</span></article>`;
  }).join('') : '<p class="empty">표시할 계정이 없습니다.</p>';
}

function fillOcxAccounts(data) {
  const component = data.components.find(item => item.id === 'ocx-accounts');
  const accounts = component?.accounts ?? [];
  ocxAccountSelector.innerHTML = accounts.length
    ? accounts.map(account => `<option value="${escapeHtml(account.id)}" ${account.active || account.needsReauth || account.paused ? 'disabled' : ''}>${escapeHtml(account.label || account.email || account.id)}${account.active ? ' (현재)' : account.needsReauth ? ' (재인증 필요)' : account.paused ? ' (일시 정지)' : ''}</option>`).join('')
    : '<option value="">전환 가능한 OCX 계정 없음</option>';
  const firstAvailable = accounts.find(account => !account.active && !account.needsReauth && !account.paused);
  ocxAccountSelector.value = firstAvailable?.id ?? '';
  switchOcxAccount.disabled = !firstAvailable;
  ocxAccountCards.innerHTML = accounts.length ? accounts.map(account => {
    const name = account.label || account.email || account.id;
    const state = account.active ? '현재 라우팅' : account.needsReauth ? '재인증 필요' : account.paused ? '일시 정지' : '사용 가능';
    return `<article class="account-card${account.active ? ' active' : ''}"><div><span class="avatar">${escapeHtml(String(name || '?').slice(0, 1).toUpperCase())}</span><span><strong>${escapeHtml(name)}</strong><small>${escapeHtml(account.plan || '요금제 미확인')} · ${escapeHtml(account.email || '이메일 미확인')}</small></span></div><span class="account-state">${escapeHtml(state)}</span></article>`;
  }).join('') : '<p class="empty">OCX 계정 풀을 표시할 수 없습니다.</p>';
}

async function previewAction(action, args = {}) {
  actionMessage.textContent = '변경 내용을 확인 중입니다.';
  openaiActionMessage.textContent = '변경 내용을 확인 중입니다.';
  try {
    const preview = await postJson('/api/actions/preview', { action, args });
    confirmationToken = preview.confirmationToken;
    dialogTitle.textContent = preview.title;
    dialogImpact.textContent = preview.impact;
    dialogWarnings.innerHTML = (preview.warnings ?? []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    dialogRollback.textContent = `복구 방법: ${preview.rollback}`;
    actionMessage.textContent = '';
    openaiActionMessage.textContent = '';
    actionDialog.showModal();
  } catch (error) {
    confirmationToken = null;
    actionMessage.textContent = error.message;
    openaiActionMessage.textContent = error.message;
  }
}

async function executeAction() {
  if (!confirmationToken) return;
  const token = confirmationToken;
  confirmationToken = null;
  confirmAction.disabled = true;
  actionMessage.textContent = '작업을 실행하고 결과를 확인 중입니다.';
  openaiActionMessage.textContent = '작업을 실행하고 결과를 확인 중입니다.';
  try {
    const result = await postJson('/api/actions/execute', { confirmationToken: token });
    actionMessage.textContent = `${result.title}: ${result.message}`;
    openaiActionMessage.textContent = `${result.title}: ${result.message}`;
    await load();
  } catch (error) {
    actionMessage.textContent = error.message;
  } finally {
    confirmAction.disabled = false;
  }
}

function renderStatus(data) {
  const percent = data.summary.total ? Math.round(data.summary.ready / data.summary.total * 100) : 0;
  summary.textContent = `${data.summary.total}개 중 ${data.summary.ready}개 준비됨`;
  summaryHint.textContent = data.summary.attention ? `${data.summary.attention}개 항목을 확인해 주세요.` : '모든 핵심 연결이 정상입니다.';
  summaryPercent.textContent = `${percent}%`;
  summaryRing.setAttribute('stroke-dasharray', `${percent} ${100 - percent}`);
  const date = new Date(data.generatedAt).toLocaleString('ko-KR');
  updatedAt.textContent = `마지막 확인 ${date}`;
  componentUpdated.textContent = date;
  components.innerHTML = data.components.map(component => {
    const presentation = componentPresentation(component);
    return `<article class="component-card ${escapeHtml(presentation.stateClass)}">
      <span class="component-dot"></span><div><div class="card-head"><h3>${escapeHtml(component.label)}</h3><span class="state">${escapeHtml(presentation.label)}</span></div><p>${escapeHtml(component.detail)}</p>${presentation.hint ? `<small>${escapeHtml(presentation.hint)}</small>` : ''}</div>
    </article>`;
  }).join('');
  const ocx = data.components.find(component => component.id === 'ocx');
  const webGpt = data.components.find(component => component.id === 'web-gpt');
  const workspace = data.components.find(component => component.id === 'workspace-mcp');
  const routeView = (prefix, component) => {
    $(`#${prefix}RouteState`).textContent = component?.state === 'ready' ? '정상' : component?.state === 'unavailable' ? '미설치' : '확인 필요';
    $(`#${prefix}RouteDetail`).textContent = component?.detail || '상태를 확인할 수 없습니다.';
    document.querySelector(`[data-route-card="${prefix === 'workspace' ? 'workspace' : prefix === 'webGpt' ? 'web-gpt' : prefix}"]`)?.classList.toggle('ready', component?.state === 'ready');
  };
  routeView('webGpt', webGpt);
  routeView('ocx', ocx);
  routeView('workspace', workspace);
  renderLiveMapState(
    'web-bridge',
    webGpt?.healthy === true && webGpt?.routeActive === true,
    webGpt?.healthy === true && webGpt?.routeActive === true ? '브리지 정상' : '브리지 확인',
    webGpt?.detail || 'Web GPT 상태를 확인할 수 없습니다.'
  );
  renderLiveMapState(
    'web-harness',
    webGpt?.harnessReady === true,
    webGpt?.harnessReady === true ? 'Full 하네스 준비' : webGpt?.harnessConfigured ? 'Tunnel 확인 필요' : 'Full 하네스 구성 전',
    webGpt?.harnessReady === true ? '현재 프로젝트 도구 사용 가능' : webGpt?.harnessConfigured ? '전용 Tunnel 또는 커넥터 확인 필요' : '브라우저 전용 모드'
  );
  renderLiveMapState(
    'workspace-tunnel',
    workspace?.tunnel?.ready === true,
    workspace?.tunnel?.ready === true ? 'Tunnel 준비' : 'Tunnel 확인',
    workspace?.tunnel?.ready === true ? '외부 ChatGPT 연결 준비됨' : '로컬 MCP 또는 Tunnel 확인 필요'
  );
  renderLiveMapState(
    'ocx',
    ocx?.state === 'ready',
    ocx?.state === 'ready' ? 'OCX 정상' : 'OCX 확인',
    ocx?.detail || 'OCX 상태를 확인할 수 없습니다.'
  );
  $('#webGptDetail').textContent = webGpt?.detail || '상태를 확인할 수 없습니다.';
  $('#webGptIndicator').classList.toggle('online', webGpt?.state === 'ready');
  $('#webGptVersion').textContent = webGpt?.version || '미확인';
  $('#webGptMode').textContent = webGpt?.mode === 'full' ? '전체 Codex 하네스' : webGpt?.mode === 'browser-only' ? '브라우저 전용' : '미설정';
  $('#webGptHarness').textContent = webGpt?.harnessReady ? '현재 프로젝트 도구 사용 가능' : webGpt?.harnessConfigured ? 'Tunnel 확인 필요' : '구성 전';
  $('#webGptTunnel').textContent = webGpt?.tunnelRuntime?.ready ? '준비됨' : webGpt?.tunnelRuntime?.running ? '연결 대기' : webGpt?.harnessConfigured ? '중지' : '미구성';
  $('#webGptConnector').textContent = webGpt?.connectorVerification === 'verified'
    ? 'Web GPT 작업 하네스 검증됨'
    : webGpt?.connectorVerification === 'chatgpt-required' ? 'ChatGPT에서 1회 검증' : '하네스 준비 후 확인';
  $('#webGptTurns').textContent = Number.isInteger(webGpt?.activeBrowserTurns) ? `${webGpt.activeBrowserTurns}/${webGpt.maxConcurrentTurns}` : '–';
  const modelLabels = webGpt?.modelLabels || [];
  $('#webGptModelCount').textContent = `${modelLabels.length}개`;
  $('#webGptModels').innerHTML = modelLabels.length ? modelLabels.map(label => `<span class="model-chip">${escapeHtml(label)}</span>`).join('') : '<span class="empty">Web GPT 모델 구성이 아직 없습니다.</span>';
  $('#workspaceDetail').textContent = workspace?.detail || '상태를 확인할 수 없습니다.';
  $('#workspaceIndicator').classList.toggle('online', workspace?.state === 'ready');
  $('#workspaceCount').textContent = Number.isInteger(workspace?.workspaceCount) ? `${workspace.workspaceCount}개` : '–';
  $('#workspaceTunnel').textContent = workspace?.tunnel?.ready ? '준비됨' : workspace?.tunnel?.running ? '연결 대기' : '중지';
  $('#workspaceFilePermission').textContent = workspace?.permissions?.files === 'read-write' ? '읽기·쓰기' : workspace?.permissions?.files || '–';
  $('#workspaceCommandPermission').textContent = workspace?.permissions?.commands ? '사용 가능' : '사용 안 함';
  const publication = workspace?.publication;
  const tools = publication?.tools || [];
  $('#workspaceToolCount').textContent = Number.isInteger(publication?.toolCount) ? `${publication.toolCount}개` : '–';
  $('#workspaceReadToolCount').textContent = Number.isInteger(publication?.readToolCount) ? `${publication.readToolCount}개` : '–';
  $('#workspaceWriteToolCount').textContent = Number.isInteger(publication?.writeToolCount) ? `${publication.writeToolCount}개` : '–';
  $('#workspaceToolSummary').textContent = `${tools.length}개`;
  $('#workspacePublishState').textContent = publication?.needsPublish ? '갱신 필요' : '게시 일치';
  $('#workspacePublishState').classList.toggle('attention', publication?.needsPublish === true);
  $('#workspacePublishDetail').textContent = publication?.needsPublish
    ? '로컬 도구 구성이 게시된 ChatGPT 앱 스냅샷과 다릅니다. 사전검사 후 앱을 다시 게시하세요.'
    : publication?.published?.verifiedAt
      ? `마지막 검증 ${new Date(publication.published.verifiedAt).toLocaleString('ko-KR')}`
      : '게시 검증 기록이 아직 없습니다.';
  $('#workspaceTools').innerHTML = tools.length ? tools.map(tool => `<div class="workspace-tool ${tool.mode === 'write' ? 'write' : 'read'}"><span>${tool.mode === 'write' ? '쓰기' : '읽기'}</span><div><strong>${escapeHtml(tool.title)}</strong><code>${escapeHtml(tool.name)}</code></div></div>`).join('') : '<span class="empty">게시할 로컬 도구 스냅샷이 없습니다.</span>';
  $('#ocxDetail').textContent = ocx?.detail || '상태를 확인할 수 없습니다.';
  $('#ocxIndicator').classList.toggle('online', ocx?.state === 'ready');
  const ocxOverview = ocx?.overview || {};
  $('#ocxConsoleIndicator').classList.toggle('online', ocx?.state === 'ready');
  $('#ocxConsoleState').textContent = ocx?.state === 'ready' ? `OCX ${ocx.version || ''} 정상`.trim() : 'OCX 확인 필요';
  $('#ocxConsoleDetail').textContent = ocx?.detail || '읽기 전용 운영 지표를 불러오지 못했습니다.';
  $('#ocxProviderCount').textContent = Number.isInteger(ocxOverview.providerCount) ? `${ocxOverview.providerCount}개` : '–';
  $('#ocxProviderNames').textContent = ocxOverview.providerNames?.length ? ocxOverview.providerNames.join(' · ') : 'Provider 미확인';
  $('#ocxModelCount').textContent = Number.isInteger(ocxOverview.modelCount) ? `${ocxOverview.modelCount}개` : '–';
  $('#ocxRequests30d').textContent = compactNumber(ocxOverview.requests30d);
  $('#ocxCoverage').textContent = Number.isFinite(ocxOverview.usageCoverageRatio) ? `측정 ${Math.round(ocxOverview.usageCoverageRatio * 100)}%` : '측정 범위 미확인';
  $('#ocxMemoryRss').textContent = formatBytes(ocxOverview.rssBytes);
  $('#ocxMemoryBudget').textContent = Number.isFinite(ocxOverview.memoryBudgetBytes) ? `앱 보유 예산 ${formatBytes(ocxOverview.memoryBudgetBytes)}` : '예산 미확인';
  $('#ocxRebootSafe').textContent = ocxOverview.rebootSafe === true ? '안전' : ocxOverview.rebootSafe === false ? '확인 필요' : '–';
  $('#ocxStartupState').textContent = ocxOverview.startupStatus ? `시작 보호 ${ocxOverview.startupStatus}` : '시작 보호 미확인';
  $('#ocxSubagentCount').textContent = Number.isInteger(ocxOverview.subagentCount) ? `${ocxOverview.subagentCount}개` : '–';
  $('#ocxMultiAgentMode').textContent = ocxOverview.multiAgentMode ? `모드 ${ocxOverview.multiAgentMode}` : '모드 미확인';
  renderOcxModules(ocx);
  const routes = data.components.find(component => component.id === 'codex-routes');
  $('#codexRouteLabel').textContent = routeLabel(routes?.activeRoute);
  $('#codexRouteState').textContent = routes?.state === 'ready' ? '복구 준비됨' : '확인 필요';
  $('#codexRouteState').classList.toggle('attention', routes?.state !== 'ready');
  $('#codexRouteDetail').textContent = routes?.detail || '모델 경로 상태를 확인할 수 없습니다.';
  $('#nativeProfileState').textContent = routes?.nativeReady ? '공식 endpoint 검증됨' : '확인 필요';
  $('#routeWebGptState').textContent = routes?.webGpt?.healthy ? `정상 · ${routes.webGpt.mode || '모드 미확인'}` : '연결 안 됨';
  $('#routeOcxState').textContent = routes?.ocx?.healthy ? '정상 · 10100' : '연결 안 됨';
  $('#routeActiveTurns').textContent = Number.isFinite(routes?.webGpt?.activeTurns) ? `${routes.webGpt.activeTurns}개` : '–';
  const nativeButton = $('[data-action="codex.native.recover"]');
  const bridgeButton = $('[data-action="codex.bridge.reconnect"]');
  nativeButton.disabled = !routes?.nativeReady || routes?.activeRoute === 'native' || Number(routes?.webGpt?.activeTurns ?? 0) > 0;
  nativeButton.title = routes?.activeRoute === 'native' ? '이미 Native Codex 경로입니다.' : '미리보기 후 공식 Native endpoint로 복구합니다.';
  bridgeButton.disabled = !routes?.webGpt?.healthy || !routes?.webGpt?.acceptingTurns || routes?.activeRoute === 'web-gpt' || Number(routes?.webGpt?.activeTurns ?? 0) > 0;
  bridgeButton.title = routes?.activeRoute === 'web-gpt' ? '이미 통합 모델 경로입니다.' : '17841 브리지가 정상일 때만 다시 연결합니다.';
  const ocxRunning = ocx?.state === 'ready';
  const ocxInstalled = ocx?.installed !== false;
  const startButton = $('[data-action="ocx.start"]');
  const syncButton = $('[data-action="ocx.sync"]');
  const stopButton = $('[data-action="ocx.stop"]');
  startButton.disabled = ocxRunning || !ocxInstalled;
  startButton.textContent = ocxRunning ? '실행 중' : '시작';
  startButton.title = ocxRunning ? 'OCX가 이미 실행 중입니다.' : ocxInstalled ? 'OCX 연결 시작 미리보기' : 'OCX가 설치되어 있지 않습니다.';
  syncButton.disabled = !ocxRunning;
  syncButton.title = ocxRunning ? '모델 목록 동기화 미리보기' : 'OCX를 먼저 시작해 주세요.';
  stopButton.disabled = !ocxRunning;
  stopButton.title = ocxRunning ? 'OCX 연결 중지 미리보기' : 'OCX가 실행 중이 아닙니다.';
  fillAccounts(data);
  fillOcxAccounts(data);
  roots.innerHTML = data.stateRoots.map(item => `<div class="path"><code>${escapeHtml(item.path)}</code><span>${item.exists ? '유지 중' : '아직 없음'}</span></div>`).join('');
}

function formatTokens(value) {
  return Number(value || 0).toLocaleString('ko-KR');
}

function availabilityLabel(availability) {
  if (availability?.status === 'available') return '실호출 확인';
  if (availability?.status === 'unavailable') return '호출 불가';
  if (availability?.status === 'retired') return '종료';
  return '미확인';
}

function formatPrice(value) {
  return Number.isFinite(value) ? `$${value.toLocaleString('en-US', { maximumFractionDigits: 3 })}` : '–';
}

function renderOpenaiProvider(provider) {
  if (!provider) return;
  const enabled = provider.enabled === true;
  openaiProviderState.textContent = enabled ? 'API 켜짐' : 'API 꺼짐';
  openaiProviderState.classList.toggle('ready', enabled);
  openaiProviderState.classList.toggle('attention', !enabled);
  toggleOpenaiProvider.textContent = enabled ? 'OpenAI API 전체 끄기' : 'OpenAI API 전체 켜기';
  toggleOpenaiProvider.dataset.enabled = String(!enabled);
  toggleOpenaiProvider.classList.toggle('danger', enabled);
  const selectable = provider.models.filter(model => model.agentSelectable && model.lifecycle !== 'retired');
  openaiDefaultModel.innerHTML = selectable.map(model => `<option value="${escapeHtml(model.id)}"${model.isDefault ? ' selected' : ''}>${escapeHtml(model.label)} · ${escapeHtml(model.id)}</option>`).join('');
  setOpenaiDefaultModel.disabled = !selectable.length || openaiDefaultModel.value === provider.defaultModel;
  const available = provider.models.filter(model => model.availability?.status === 'available').length;
  openaiModelSummary.textContent = `${provider.models.length}개 공식 대상 · ${selectable.length}개 agent 허용 · ${available}개 실호출 확인`;
  const filters = [
    ['current', '현재 권장'], ['enabled', '사용 허용'], ['all', '전체'], ['frontier', '고성능 풀'], ['efficient', '경량 풀']
  ];
  openaiModelFilters.innerHTML = filters.map(([id, label]) => `<button type="button" class="filter-chip${activeOpenaiModelFilter === id ? ' active' : ''}" data-openai-filter="${id}" aria-pressed="${activeOpenaiModelFilter === id}">${label}</button>`).join('');
  const visible = provider.models.filter(model => {
    if (activeOpenaiModelFilter === 'current') return model.lifecycle === 'current';
    if (activeOpenaiModelFilter === 'enabled') return model.callEnabled;
    if (activeOpenaiModelFilter === 'frontier' || activeOpenaiModelFilter === 'efficient') return model.groupId === activeOpenaiModelFilter;
    return true;
  });
  openaiModelList.innerHTML = visible.map(model => {
    const price = model.pricing;
    const unavailable = model.lifecycle === 'retired';
    const accessClass = model.availability?.status === 'available' ? 'ready' : model.availability?.status === 'unavailable' ? 'attention' : '';
    return `<article class="openai-model-row${model.isDefault ? ' is-default' : ''}">
      <div class="openai-model-copy">
        <div class="openai-model-title"><strong>${escapeHtml(model.label)}</strong><code>${escapeHtml(model.id)}</code>${model.isDefault ? '<span class="model-policy-badge default">기본</span>' : ''}<span class="model-policy-badge">${escapeHtml(model.groupId)}</span><span class="model-policy-badge ${accessClass}">${availabilityLabel(model.availability)}</span></div>
        <p>${escapeHtml(model.role)} · input ${formatPrice(price?.input)} / cached ${formatPrice(price?.cachedInput)} / output ${formatPrice(price?.output)} per 1M</p>
        <small>오늘 입력 ${formatTokens(model.usage.inputTokens)} · 출력 ${formatTokens(model.usage.outputTokens)} · 공유 풀 ${model.usage.sharedPoolPercent}% · 표준요금 환산 ${model.usage.estimatedStandardCostUsd == null ? '–' : `$${model.usage.estimatedStandardCostUsd.toFixed(5)}`}</small>
      </div>
      <div class="openai-model-actions">
        <button type="button" class="secondary" data-openai-model-action="call" data-model="${escapeHtml(model.id)}" data-call-enabled="${!model.callEnabled}" data-agent-selectable="${model.agentSelectable}" ${unavailable ? 'disabled' : ''}>API ${model.callEnabled ? '끄기' : '켜기'}</button>
        <button type="button" class="secondary" data-openai-model-action="agent" data-model="${escapeHtml(model.id)}" data-call-enabled="${model.callEnabled}" data-agent-selectable="${!model.agentSelectable}" ${unavailable || !model.callEnabled ? 'disabled' : ''}>Agent ${model.agentSelectable ? '제외' : '허용'}</button>
        <button type="button" class="secondary" data-openai-model-action="default" data-model="${escapeHtml(model.id)}" ${unavailable || !model.agentSelectable || model.isDefault ? 'disabled' : ''}>기본 지정</button>
        <button type="button" class="ghost" data-openai-model-action="probe" data-model="${escapeHtml(model.id)}" ${unavailable || !enabled ? 'disabled' : ''}>연결 확인</button>
      </div>
    </article>`;
  }).join('') || '<p class="empty-usage">선택한 조건에 맞는 모델이 없습니다.</p>';
}

function renderOpenaiUsage(data) {
  openaiKeyState.classList.toggle('online', data.keyConfigured);
  openaiGuardSummary.textContent = data.keyConfigured
    ? `Keychain 키 확인됨 · 유료 대상 모델 차단 · 무료 풀 95%에서 하드 정지`
    : 'Keychain에서 OpenAI API 키를 찾지 못했습니다.';
  openaiUsageUpdated.textContent = data.updatedAt
    ? `즉시 원장 ${new Date(data.updatedAt).toLocaleString('ko-KR')}`
    : `UTC ${data.dayUtc} · 아직 guard 호출 없음`;
  renderOpenaiProvider(data.provider);
  const groupCards = data.groups.map(group => `
    <article class="usage-group-card">
      <div class="usage-group-head"><div><h3>${escapeHtml(group.label)}</h3><p>${formatTokens(group.tokens)} / ${formatTokens(group.freeLimit)} token</p></div><strong>${group.percent}%</strong></div>
      <div class="usage-meter"><progress aria-label="${escapeHtml(group.label)} 사용률" value="${Math.min(100, group.percent)}" max="100">${Math.min(100, group.percent)}%</progress><i title="로컬 하드 정지 95%"></i></div>
      <p class="usage-remaining">95% 하드 정지까지 ${formatTokens(group.hardRemaining)} token · 매일 00:00 UTC 초기화</p>
      <div class="model-usage-list">
        ${group.models.length ? group.models.map(model => `<div class="model-usage-row"><span><strong>${escapeHtml(model.model)}</strong><small>${formatTokens(model.requests)}회 · 입력 ${formatTokens(model.inputTokens)} · 캐시 ${formatTokens(model.cachedInputTokens)} · 출력 ${formatTokens(model.outputTokens)}</small></span><span><b>${formatTokens(model.totalTokens)}</b><small>${model.estimatedStandardCostUsd == null ? '가격 미등록' : `표준요금 환산 $${model.estimatedStandardCostUsd.toFixed(5)}`}</small></span></div>`).join('') : '<p class="empty-usage">아직 이 그룹의 guard 호출이 없습니다.</p>'}
      </div>
    </article>`).join('');
  const projects = Array.isArray(data.projects) ? data.projects : [];
  const projectCard = `
    <article class="usage-project-card">
      <div class="usage-project-heading"><div><p class="eyebrow">PROJECT BUDGETS</p><h3>프로젝트별 AICC 사용량</h3></div><code>aicc openai project status</code></div>
      ${projects.length ? `<div class="usage-project-list">${projects.map(project => `
        <div class="usage-project-row">
          <span><strong>${escapeHtml(project.label)}</strong><small>${formatTokens(project.requests)}회 · ${formatTokens(project.tokens)} token · ${project.customized ? '사용자 한도' : '기본 10% 한도'}</small></span>
          <span class="usage-project-pools">${project.groups.map(group => `<small><b>${escapeHtml(group.id)}</b> ${formatTokens(group.tokens)} / ${formatTokens(group.limit)} (${group.percent}%)</small>`).join('')}</span>
        </div>`).join('')}</div>` : '<p class="empty-usage">프로젝트로 식별된 guard 호출이 아직 없습니다. 기존 호출은 다음 요청부터 Git 프로젝트별로 자동 기록됩니다.</p>'}
    </article>`;
  openaiUsageGroups.innerHTML = groupCards + projectCard;
}

async function loadOpenaiUsage() {
  const response = await fetch('/api/openai-usage', { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  renderOpenaiUsage(data);
}

async function loadStatus() {
  const response = await fetch('/api/status', { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  statusData = data;
  renderStatus(data);
}

async function runNamedTask(taskId) {
  const item = catalog.items.find(candidate => candidate.taskId === taskId)
    || { title: taskId, taskId };
  return runTask(item);
}

async function copySupportBundle(includePrompt) {
  supportMessage.textContent = '비밀을 제외한 진단 묶음을 만들고 있습니다.';
  copySupportPrompt.disabled = true;
  copySupportJson.disabled = true;
  try {
    const task = await postJson('/api/tasks/run', { taskId: 'support.bundle' }, { acceptFindings: true });
    const payload = task.result || {};
    const text = includePrompt
      ? `${payload.consultationPrompt || '아래 진단을 분석해 주세요.'}\n\n\`\`\`json\n${JSON.stringify(payload, null, 2)}\n\`\`\``
      : JSON.stringify(payload, null, 2);
    await navigator.clipboard.writeText(text);
    supportMessage.textContent = includePrompt ? '상담문과 진단 묶음을 복사했습니다.' : '진단 JSON을 복사했습니다.';
  } catch (error) {
    supportMessage.textContent = `복사하지 못했습니다: ${error.message}`;
  } finally {
    copySupportPrompt.disabled = false;
    copySupportJson.disabled = false;
  }
}

async function load() {
  refresh.disabled = true;
  refresh.classList.add('spinning');
  summary.textContent = '확인 중';
  try {
    const [catalogResult, statusResult, usageResult] = await Promise.allSettled([
      fetch('/api/catalog', { cache: 'no-store' }).then(async response => {
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
      }),
      loadStatus(),
      loadOpenaiUsage()
    ]);
    if (catalogResult.status === 'fulfilled') {
      catalog = catalogResult.value;
      renderCatalog();
    } else {
      toolLibrary.innerHTML = `<p class="error">도구 목록만 불러오지 못했습니다: ${escapeHtml(catalogResult.reason.message)}</p>`;
    }
    if (statusResult.status === 'rejected') {
      components.innerHTML = `<p class="error">상태 API를 확인하지 못했습니다: ${escapeHtml(statusResult.reason.message)}</p>`;
      roots.innerHTML = '';
      summary.textContent = '상태 확인 실패';
    }
    if (usageResult.status === 'rejected') {
      openaiUsageGroups.innerHTML = `<p class="error">OpenAI API 구역만 확인하지 못했습니다: ${escapeHtml(usageResult.reason.message)}</p>`;
      openaiUsageUpdated.textContent = '독립 구역 확인 실패';
    }
  } finally {
    refresh.disabled = false;
    refresh.classList.remove('spinning');
  }
}

refresh.addEventListener('click', load);
$('#refreshWebGpt').addEventListener('click', load);
$('#openWebGpt').addEventListener('click', () => activateTool({ id: 'web-gpt', appId: 'web-gpt', title: 'Codex Web GPT' }));
$('#workspacePreflight').addEventListener('click', () => {
  const item = catalog.items.find(candidate => candidate.id === 'workspace-publish');
  if (item) runTask(item);
});
copySupportPrompt.addEventListener('click', () => copySupportBundle(true));
copySupportJson.addEventListener('click', () => copySupportBundle(false));
document.addEventListener('click', event => {
  const actionButton = event.target.closest('[data-action]');
  if (actionButton) previewAction(actionButton.dataset.action);
  const diagnosticButton = event.target.closest('[data-diagnostic-task]');
  if (diagnosticButton) runNamedTask(diagnosticButton.dataset.diagnosticTask);
  const toolButton = event.target.closest('[data-tool-run]');
  if (toolButton) {
    const item = catalog.items.find(candidate => candidate.id === toolButton.dataset.toolRun);
    if (item) activateTool(item);
  }
  const filterButton = event.target.closest('[data-filter]');
  if (filterButton) {
    activeFilter = filterButton.dataset.filter;
    renderCatalog();
    toolFilters.querySelector(`[data-filter="${CSS.escape(activeFilter)}"]`)?.focus();
  }
  const architectureButton = event.target.closest('[data-architecture-filter]');
  if (architectureButton) {
    activeArchitectureFilter = architectureButton.dataset.architectureFilter;
    renderArchitectureFilter();
  }
  const openaiFilter = event.target.closest('[data-openai-filter]');
  if (openaiFilter) {
    activeOpenaiModelFilter = openaiFilter.dataset.openaiFilter;
    if (statusData) loadOpenaiUsage().catch(error => { openaiActionMessage.textContent = error.message; });
  }
  const openaiModelAction = event.target.closest('[data-openai-model-action]');
  if (openaiModelAction) {
    const action = openaiModelAction.dataset.openaiModelAction;
    const model = openaiModelAction.dataset.model;
    if (action === 'call' || action === 'agent') previewAction('openai.model.set', {
      model,
      callEnabled: openaiModelAction.dataset.callEnabled === 'true',
      agentSelectable: openaiModelAction.dataset.agentSelectable === 'true'
    });
    if (action === 'default') previewAction('openai.default-model.set', { model });
    if (action === 'probe') previewAction('openai.model.probe', { model });
  }
});
toggleOpenaiProvider.addEventListener('click', () => previewAction('openai.provider.set', { enabled: toggleOpenaiProvider.dataset.enabled === 'true' }));
openaiDefaultModel.addEventListener('change', () => { setOpenaiDefaultModel.disabled = !openaiDefaultModel.value; });
setOpenaiDefaultModel.addEventListener('click', () => previewAction('openai.default-model.set', { model: openaiDefaultModel.value }));
switchAccount.addEventListener('click', () => previewAction('account.switch', { selector: accountSelector.value }));
switchOcxAccount.addEventListener('click', () => previewAction('ocx.account.use', { selector: ocxAccountSelector.value }));
actionDialog.addEventListener('close', () => {
  if (actionDialog.returnValue === 'default') executeAction();
  else confirmationToken = null;
});
toolSearch.addEventListener('input', () => { searchIndex = 0; renderSearch(); });
toolSearch.addEventListener('keydown', event => {
  const matches = matchingTools(toolSearch.value);
  if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && matches.length) {
    event.preventDefault();
    const direction = event.key === 'ArrowDown' ? 1 : -1;
    searchIndex = (searchIndex + direction + matches.length) % matches.length;
    renderSearch();
    return;
  }
  if (event.key === 'Enter') {
    const selected = matches[searchIndex];
    if (selected) { event.preventDefault(); activateTool(selected); }
  }
  if (event.key === 'Escape') { toolSearch.value = ''; searchIndex = 0; renderSearch(); toolSearch.blur(); }
});
document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === 'k') {
    event.preventDefault();
    toolSearch.focus();
  }
});
document.addEventListener('click', event => {
  if (!event.target.closest('.command-search')) { searchResults.hidden = true; toolSearch.setAttribute('aria-expanded', 'false'); }
});
const sections = [...document.querySelectorAll('.anchor-section, #home')];
const observer = new IntersectionObserver(entries => {
  const current = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!current) return;
  document.querySelectorAll('.nav-link').forEach(link => link.classList.toggle('active', link.getAttribute('href') === `#${current.target.id}`));
}, { rootMargin: '-20% 0px -65% 0px', threshold: [0, .2, .6] });
sections.forEach(section => observer.observe(section));
renderArchitectureFilter();
load();
window.setInterval(() => {
  if (!document.hidden) loadOpenaiUsage().catch(() => {});
}, 30_000);
