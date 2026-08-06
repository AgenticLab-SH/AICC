function finiteNumber(value) {
  return Number.isFinite(value) ? value : null;
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function guidanceTargets(result) {
  const checks = Array.isArray(result?.checks) ? result.checks : [];
  return unique(checks.flatMap(check => check?.result?.selected_target_groups ?? []));
}

export function diagnosticPresentation(taskId, taskResult) {
  const result = taskResult?.result;
  const ok = taskResult?.ok !== false;
  const duration = finiteNumber(taskResult?.durationMs);
  const durationText = duration === null ? null : duration >= 1000 ? `${(duration / 1000).toFixed(1)}초` : `${duration}ms`;
  const base = {
    tone: ok ? 'ready' : 'attention',
    headline: ok ? '점검을 마쳤습니다.' : '확인이 필요한 항목이 있습니다.',
    detail: durationText ? `${durationText} 만에 완료했습니다.` : '진단이 완료되었습니다.',
    highlights: []
  };

  if (taskId === 'status' && result?.summary) {
    const ready = finiteNumber(result.summary.ready) ?? 0;
    const total = finiteNumber(result.summary.total) ?? 0;
    const attention = finiteNumber(result.summary.attention) ?? Math.max(0, total - ready);
    return {
      ...base,
      headline: attention ? `${attention}개 핵심 연결을 확인해 주세요.` : '모든 핵심 연결이 정상입니다.',
      detail: `핵심 연결 ${total}개 중 ${ready}개가 준비되었습니다.`,
      highlights: [
        { label: '준비됨', value: `${ready}/${total}`, tone: attention ? 'attention' : 'ready' },
        { label: '확인 필요', value: `${attention}개`, tone: attention ? 'attention' : 'muted' }
      ]
    };
  }

  if (taskId === 'guidance.check' && result && typeof result === 'object') {
    const checks = Array.isArray(result.checks) ? result.checks : [];
    const totalChecks = checks.reduce((sum, check) => sum + (finiteNumber(check?.result?.check_count) ?? 0), 0);
    const failed = finiteNumber(result.failed_count)
      ?? checks.reduce((sum, check) => sum + (finiteNumber(check?.result?.failed_count) ?? 0), 0);
    const targets = guidanceTargets(result);
    return {
      ...base,
      tone: failed ? 'attention' : 'ready',
      headline: failed ? `${failed}개 지침 검사를 확인해 주세요.` : '지침과 스킬이 모두 일치합니다.',
      detail: totalChecks ? `총 ${totalChecks}개 검사를 확인했습니다.` : base.detail,
      highlights: [
        { label: '검사', value: failed ? `${failed}개 실패` : `${totalChecks}개 통과`, tone: failed ? 'attention' : 'ready' },
        ...(targets.length ? [{ label: '배포 대상', value: targets.map(target => target === 'codex' ? 'Codex' : target === 'claude' ? 'Claude' : target).join(' · '), tone: 'muted' }] : [])
      ]
    };
  }

  if (result && typeof result === 'object') {
    const failed = finiteNumber(result.failed_count);
    const checked = finiteNumber(result.check_count);
    const summary = result.summary;
    if (summary && Number.isFinite(summary.ready) && Number.isFinite(summary.total)) {
      base.highlights.push({ label: '준비됨', value: `${summary.ready}/${summary.total}`, tone: summary.attention ? 'attention' : 'ready' });
    } else if (checked !== null) {
      base.highlights.push({ label: '검사', value: failed ? `${failed}개 실패` : `${checked}개 통과`, tone: failed ? 'attention' : 'ready' });
    }
  } else if (typeof result === 'string') {
    const firstLine = result.split('\n').map(line => line.trim()).find(Boolean);
    if (firstLine && firstLine.length <= 140) base.detail = firstLine;
  }

  return base;
}

export function componentPresentation(component) {
  if (component?.optional && component?.state === 'unavailable') {
    return { stateClass: 'optional', label: '선택 기능', hint: '설치하지 않아도 핵심 기능은 정상 동작합니다.' };
  }
  const labels = { ready: '준비됨', offline: '꺼짐', degraded: '확인 필요', unavailable: '없음' };
  return { stateClass: component?.state ?? 'unknown', label: labels[component?.state] ?? component?.state ?? '알 수 없음', hint: '' };
}
