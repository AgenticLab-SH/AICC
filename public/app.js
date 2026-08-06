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
let confirmationToken = null;
let catalog = { groups: [], items: [] };
let statusData = null;
let activeFilter = 'all';
let searchIndex = 0;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[character]);
}

function iconFor(item) {
  const icons = { dashboard: '⌂', status: '✓', 'workspace-mcp': 'W', 'codex-agents': 'A', 'auth-portal': '↥', codex: 'G', claude: 'C', ocx: 'O', accounts: '◎', workflows: '↗', system: '◇' };
  return icons[item.id] || icons[item.group] || '·';
}

function taskButtonLabel(item) {
  if (item.taskId) return '지금 확인';
  if (item.href) return '화면 열기';
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
  try {
    const preview = await postJson('/api/actions/preview', { action, args });
    confirmationToken = preview.confirmationToken;
    dialogTitle.textContent = preview.title;
    dialogImpact.textContent = preview.impact;
    dialogWarnings.innerHTML = (preview.warnings ?? []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    dialogRollback.textContent = `복구 방법: ${preview.rollback}`;
    actionMessage.textContent = '';
    actionDialog.showModal();
  } catch (error) {
    confirmationToken = null;
    actionMessage.textContent = error.message;
  }
}

async function executeAction() {
  if (!confirmationToken) return;
  const token = confirmationToken;
  confirmationToken = null;
  confirmAction.disabled = true;
  actionMessage.textContent = '작업을 실행하고 결과를 확인 중입니다.';
  try {
    const result = await postJson('/api/actions/execute', { confirmationToken: token });
    actionMessage.textContent = `${result.title}: ${result.message}`;
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
  summaryRing.style.strokeDasharray = `${percent} ${100 - percent}`;
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
  $('#ocxDetail').textContent = ocx?.detail || '상태를 확인할 수 없습니다.';
  $('#ocxIndicator').classList.toggle('online', ocx?.state === 'ready');
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

async function loadStatus() {
  const response = await fetch('/api/status', { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  statusData = data;
  renderStatus(data);
}

async function load() {
  refresh.disabled = true;
  refresh.classList.add('spinning');
  summary.textContent = '확인 중';
  try {
    const [catalogResponse] = await Promise.all([fetch('/api/catalog', { cache: 'no-store' }), loadStatus()]);
    const catalogData = await catalogResponse.json();
    if (!catalogResponse.ok || !catalogData.ok) throw new Error(catalogData.error || `HTTP ${catalogResponse.status}`);
    catalog = catalogData;
    renderCatalog();
  } catch (error) {
    components.innerHTML = `<p class="error">상태를 확인하지 못했습니다: ${escapeHtml(error.message)}</p>`;
    roots.innerHTML = '';
    summary.textContent = '확인 실패';
  } finally {
    refresh.disabled = false;
    refresh.classList.remove('spinning');
  }
}

refresh.addEventListener('click', load);
document.addEventListener('click', event => {
  const actionButton = event.target.closest('[data-action]');
  if (actionButton) previewAction(actionButton.dataset.action);
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
});
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
load();
