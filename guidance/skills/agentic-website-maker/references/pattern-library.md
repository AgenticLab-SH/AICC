# AgenticFabWorks UI 패턴 라이브러리: 현재 목적과 화면 골격을 보존하는 미세 개선안.
로드 시점: 다섯 사이트의 정적 HTML/CSS/JS UI를 손보기 전, 기능·카피·상태를 결정할 때만 연다.
도입 전: 아래 출처와 대상 사이트의 라이브 화면을 다시 확인하고, 현재 요소·접근성·CSP와 충돌하지 않는지 검증한다.

## 목차

- [공통](#공통)
- [허브](#허브--agenticfabworkscom)
- [tools](#tools--toolsagenticfabworkscom)
- [skct](#skct--skctagenticfabworkscom)
- [calendar](#calendar--calendaragenticfabworkscom)
- [interview](#interview--interviewagenticfabworkscom)
- [도입 우선순위](#도입-우선순위)
- [제외한 패턴](#제외한-패턴)

## 공통

### C1. 보이는 키보드 단서와 동일한 실제 동작

- 출처/실제: [Vercel Geist Command Menu](https://vercel.com/geist/command-menu)는 `⌘K`/`Ctrl+K`, `↑`/`↓`, `Enter`, `Esc`를 명시하고, 빈 검색창에도 Recent 항목을 보여 준다.
- 대상/적합: **tools**의 `/` 검색, **skct**의 시험 조작, **calendar**의 포커스 시작은 마우스를 찾아다니지 않게 하되 기존 레이아웃은 그대로 둔다.
- 최소 구현: 이미 보이는 버튼 옆에 `<kbd>` 1개를 붙이고, `document.addEventListener('keydown', handler)`에서 포커스가 `input, textarea, [contenteditable]`이면 전역 키를 무시한다; `Escape`는 모달/패널만 닫는다.
- skip if: 단축키가 브라우저 기본 키 또는 사용자가 텍스트를 쓰는 키와 충돌하고, 재할당 또는 비활성화 방법을 제공할 수 없으면 넣지 않는다.

### C2. 즉시 반응 뒤에는 짧고 조용한 상태 확인

- 출처/실제: [Linear Peek](https://linear.app/docs/peek)는 `Space`로 미리보기를 열고 `Esc`로 닫으며, `↑`/`↓` 이동 시 동일 패널을 갱신한다.
- 대상/적합: **tools** 계산 결과, **calendar** 이동/늘이기, **interview** 저장 완료는 전환 화면 없이 현재 맥락에서 결과를 확인하게 한다.
- 최소 구현: 상태 문구를 `<output aria-live="polite">` 하나로 유지하고 성공 시 2.5초 후 `opacity` class만 제거한다; CSS transition은 `120ms` 이하, `prefers-reduced-motion`에서는 0ms로 둔다.
- skip if: 사용자가 다음 행동을 하기 위해 꼭 읽어야 하는 오류·권한·데이터 손실 경고라면 자동으로 사라지게 하지 않는다.

### C3. 고정 크기 터치 표적과 눈에 보이는 focus

- 출처/실제: [Vercel Geist Menu](https://vercel.com/geist/menu)는 메뉴를 hover가 아닌 click으로 열고, 화면 경계에서 자동 반전하며 키보드 탐색을 지원한다.
- 대상/적합: 다섯 사이트의 아이콘 버튼(검색, 타이머, 더보기, 녹음)은 작은 시각 아이콘을 유지하면서도 조작 실패를 줄인다.
- 최소 구현: 버튼의 실제 hit area는 최소 `40px × 40px`, `:focus-visible`은 2px solid outline과 2px offset, 메뉴는 `click`/`pointerdown`으로 열고 CSS class로 위치를 바꾼다.
- skip if: 시험 시간 중에 화면 경계 자동 반전이 OMR 또는 타이머와 겹쳐 시야를 가리면, 그 화면에서는 고정 위치를 우선한다.

## 허브 — agenticfabworks.com

### H1. 카드 안의 정직한 제품 미리보기

- 출처/실제: [Vercel Templates](https://vercel.com/templates)는 템플릿별 실제 화면 썸네일과 용도·기술 태그를 카드에서 함께 보여 주고 상세로 이동시킨다.
- 대상/적합: **허브**의 5개 서비스 카드는 현재 screenshot preview를 더 유용한 선택 근거로 만들며, 서비스 구성이나 목적을 바꾸지 않는다.
- 최소 구현: 기존 `<a class="service-card">` 안에 16:10 `img` preview, 한 줄 설명, `방문하기 →`를 둔다; 이미지는 `loading="lazy"`(첫 화면 1~2개만 eager), `width`/`height` 속성으로 레이아웃 이동을 막는다.
- skip if: 실제 서비스 화면이 아직 안정적이지 않거나 screenshot이 민감한 개인 데이터·콘텐츠를 포함하면 썸네일을 추가하지 않는다.

### H2. 카드 선택의 키보드 빠른 이동

- 출처/실제: [Linear Board](https://linear.app/docs/board-layout)는 키보드로 항목을 선택·이동하고, 마우스와 키보드 조작의 위치 결과를 일관되게 유지한다.
- 대상/적합: **허브**에서 5개 카드 중 목적지 하나를 고르는 일은 빈번하므로, 시각 골격을 바꾸지 않고 포커스 순서를 또렷하게 한다.
- 최소 구현: 카드 전체를 단일 `<a>`로 두고 DOM 순서를 시각 순서와 같게 유지한다; `Tab` focus에서 2px teal `#59d6c7` ring, `Enter`로 기존 링크 이동, 카드 내부의 중복 버튼은 만들지 않는다.
- skip if: 카드 안에 독립적인 액션이 2개 이상 생겨 한 링크로 의미를 묶을 수 없다면, 카드 전체 링크를 고집하지 않는다.

### H3. ‘기기 밖으로 나가지 않음’의 범위가 보이는 trust note

- 출처/실제: [Stripe 보안 문서](https://docs.stripe.com/security/stripe)는 보안·데이터 처리 설명을 별도 문서로 연결해, 짧은 주장과 검증 가능한 근거를 분리한다.
- 대상/적합: **허브**의 `data stays on your device` 섹션은 강한 신뢰 장점이지만, 녹음·localStorage처럼 사이트별 차이를 숨기지 않는 작은 보강이 필요하다.
- 최소 구현: 섹션에 3개 `<li>`만 둔다: `계산은 브라우저에서 실행`, `저장은 이 기기 브라우저에만`, `서버 전송 없음`; 각 문구는 실제 사이트별 정책 페이지/앵커 링크로 연결한다.
- skip if: 어느 서비스라도 analytics·오류 로그·외부 요청을 보내면 ‘서버 전송 없음’이라고 쓰지 말고 해당 범위를 정확히 고친다.

### H4. 서비스 진입 전 1줄의 ‘무엇을 할 수 있나’

- 출처/실제: [Raycast Store](https://www.raycast.com/store)는 확장 카드에서 이름과 짧은 기능 설명을 나란히 제공해 사용자가 설치 전 역할을 가늠하게 한다.
- 대상/적합: **허브**는 5개 서로 다른 도구를 라우팅하므로, screenshot만 보고 계산기·시험 연습·일정 도구를 오해하지 않게 한다.
- 최소 구현: 제목 아래 44자 이내 한 줄로 `17개 계산을 즉시 실행`, `문제집과 함께 푸는 실전 화면`처럼 목적만 적는다; CSS `line-clamp: 2`가 아니라 단일 줄+ellipsis로 카드 높이를 고정한다.
- skip if: 한 줄이 기능을 과장하거나 서비스의 핵심 제약(예: 문제는 제공하지 않음)을 감춘다면, 설명보다 제약을 먼저 쓴다.

## tools — tools.agenticfabworks.com

### T1. 빈 검색창의 최근 사용 결과

- 출처/실제: [Omni Calculator Android 앱](https://www.omnicalculator.com/mobile-app)은 홈에서 favorite와 recently used를 바로 다시 열고, 검색과 카테고리 탐색을 함께 제공한다.
- 대상/적합: **tools**는 이미 `recently used`와 `/` 검색을 갖고 있어, 빈 검색 상태가 ‘아무 결과 없음’처럼 보이지 않게 만든다.
- 최소 구현: `/` 또는 검색 클릭 시 `localStorage.recentToolIds`의 최근 5개를 `Recent` group으로 렌더하고, 입력 1글자부터 title/keyword를 filter한다; `ArrowDown`, `Enter`, `Escape`만 지원한다.
- skip if: 기기 공유가 흔해 최근 도구 제목 자체가 민감한 정보를 드러낼 수 있으면 최근 목록을 기본으로 열지 않는다.

### T2. 입력 바로 아래의 즉시 결과와 계산 근거

- 출처/실제: [Wolfram|Alpha](https://www.wolframalpha.com/)는 질의를 입력하자마자 계산 결과와 해석 단위를 한 화면에 제시한다.
- 대상/적합: **tools**의 단일 목적 계산기는 결과를 보려고 스크롤하거나 별도 실행 버튼을 찾지 않아도 되어야 한다.
- 최소 구현: 마지막 유효 입력 후 `150ms` debounce로 `output`을 갱신하고, 결과 카드에는 큰 값·단위·`계산 기준` 한 줄만 둔다; 빈/잘못된 값은 결과를 지우지 말고 인접 field error를 표시한다.
- skip if: 대출처럼 계산이 무거워 150ms 안에 끝나지 않거나 소수점 입력 중 중간값이 오해를 부르면 `계산하기`를 유지한다.

### T3. 칩은 필터이며 개수를 숨기지 않는다

- 출처/실제: [Vercel Geist Tabs](https://vercel.com/geist/tabs)는 같은 범위의 sibling view만 탭으로 전환하고, active 상태를 URL에 반영하며 키보드 이동을 지원한다.
- 대상/적합: **tools**의 6개 category chip은 기존 카드 grid를 바꾸지 않고 ‘현재 몇 개를 보고 있는지’를 알려 준다.
- 최소 구현: chip group에 `aria-label="계산기 분류"`, 선택 chip에 `aria-pressed="true"`; 선택 때 `?category=finance`를 `history.replaceState`로 반영하고 결과 상단에 `금융 4개`를 출력한다.
- skip if: 분류가 서로 겹쳐 하나의 도구가 여러 칩에 속하고 URL 상태가 혼란스러우면 count만 표시하고 URL 동기화는 하지 않는다.

### T4. 숫자 입력의 단위·예시·복사 가능한 결과

- 출처/실제: [RapidTables Calculators](https://www.rapidtables.com/calc/)는 계산기마다 명확한 단위 입력과 결과값 중심의 짧은 폼을 제공한다.
- 대상/적합: **tools**의 VAT·BMI·급여·대출 도구는 입력 단위를 짐작하게 만들지 않고, 결과 재사용을 한 번의 동작으로 끝낸다.
- 최소 구현: label에 `월 급여 (원)`처럼 단위를 포함하고 placeholder는 `예: 3,500,000`; 결과 행에 `복사` 40px button을 붙여 `navigator.clipboard.writeText()` 후 `복사됨`을 2.5초 표시한다.
- skip if: 세금·급여 결과가 법적 확정값처럼 보일 가능성이 있으면 복사 버튼 옆에 `참고용 추정` 문구와 기준 연도를 반드시 표시한다.

## skct — skct.agenticfabworks.com

### S1. 상단 고정 시험 상태: 시간·진행·검토 표시

- 출처/실제: [Microsoft Certification exam experience](https://learn.microsoft.com/en-us/credentials/support/exam-duration-exam-experience)는 full-screen header에 남은 시간과 문항 수를 두고, 문제 mark-for-review와 review screen을 제공한다.
- 대상/적합: **skct**의 dense exam screen은 사용자가 가져온 문제집을 풀 때 현재 위치와 시간 압박을 한눈에 이해해야 한다.
- 최소 구현: header 높이 `52px`에 `남은 42:17 · 18/50 · 검토 3`만 고정하고, `검토` click은 OMR의 `.is-marked`로 scroll/focus한다; 60초 미만만 amber, 10초 미만만 red로 바꾼다.
- skip if: 실제 모의고사에 문제 수 또는 시간 제한을 사용자 스스로 설정하지 않았으면 임의의 총 문항·종료 경고를 만들지 않는다.

### S2. OMR 선택과 검토 표식을 서로 다른 상태로

- 출처/실제: [Microsoft exam FAQ](https://learn.microsoft.com/en-us/credentials/certifications/frequently-asked-questions)는 답을 바꾸기 전에 review screen에서 검토할 수 있도록 답변과 review를 분리한다.
- 대상/적합: **skct**는 문제 내용을 제공하지 않으므로, 사용자가 자기 문제집의 ‘나중에 다시 볼 문항’을 OMR에서 독립적으로 표시할 수 있어야 한다.
- 최소 구현: 문항마다 `radio` 5개와 별도 `button aria-pressed` 별표를 둔다; 답 선택은 `localStorage.answers[qNo]`, 별표는 `localStorage.marked[qNo]`에 따로 저장하고 OMR에는 `●`/`☆`를 동시 표시한다.
- skip if: 답안지가 실제 채점 제출물로 오인될 수 있는 흐름이면 ‘채점’ 또는 제출 완료 상태를 추가하지 않는다.

### S3. 도구 패널은 열고 닫아도 풀이를 가리지 않는다

- 출처/실제: [LeetCode problem page 개선](https://leetcode.com/discuss/post/2238519/share-your-feedback-to-the-new-question-detail-page/)은 timer를 숨길 수 있게 하고, console은 drag로 resize하며, 실패 testcase에 초점을 맞춘다.
- 대상/적합: **skct**의 memo·drawing pad·calculator는 다 필요하지만, 문제집을 보는 주 흐름을 덮으면 연습 도구의 의도가 뒤집힌다.
- 최소 구현: 우측 도구 dock은 `width: 320px` desktop, mobile은 bottom sheet; 각 panel은 `aria-expanded`로 토글, 마지막 사용 panel만 localStorage에 기억하고 `Esc`로 접는다.
- skip if: 사용자가 태블릿에서 손글씨 pad를 전체 화면으로 써야 하는 경우에는 320px 고정폭 대신 일시 full-screen을 제공한다.

### S4. 도구 사용 종료 후에도 시험 시간은 계속 간다

- 출처/실제: [Microsoft Certification exam experience](https://learn.microsoft.com/en-us/credentials/support/exam-duration-exam-experience)는 split-screen reference를 열어도 exam timer가 계속 흐른다고 명시한다.
- 대상/적합: **skct**에서 계산기·메모·드로잉 도구는 편의 기능이지 시험 시간을 멈추는 보상이 아니므로 실전 감각을 보존한다.
- 최소 구현: 단일 `setInterval`이 epoch 차이로 header timer를 계산하고, panel open/close 또는 탭 visibility 변경에 따라 pause하지 않는다; `visibilitychange` 시 저장만 한다.
- skip if: 사용자가 ‘연습/무제한’ 모드로 명시적으로 시작한 경우에는 타이머를 강제 표시하거나 경고하지 않는다.

## calendar — calendar.agenticfabworks.com

### C4. 드래그 중에는 원래 자리와 새 시간을 동시에 보인다

- 출처/실제: [Sunsama Timeboxing](https://help.sunsama.com/docs/usage-guides/timeboxing/)은 task를 calendar의 원하는 시각으로 drag-and-drop해 timebox한다.
- 대상/적합: **calendar**의 orbit arc 이동은 원형 좌표라 시작/끝이 직선 calendar보다 덜 자명하므로, 이동 전후를 동시에 읽히게 해야 한다.
- 최소 구현: `pointerdown`에 원 arc는 `opacity: .35` ghost로 남기고 drag arc에는 `09:30–10:15` label을 붙인다; 5분 snap, `pointerup`에만 저장하며 pointer capture를 사용한다.
- skip if: 5분보다 작은 단위가 제품의 필수 정확도라면 snap 단위를 임의로 키우지 않는다.

### C5. flexible만 밀리고, 고정 일정은 절대 밀리지 않는다

- 출처/실제: [Motion Auto-scheduling](https://www.usemotion.com/help/time-management/auto-scheduling)은 duration·deadline·priority·기존 event를 고려해 변경 뒤에 task를 재배치한다.
- 대상/적합: **calendar**의 cascade-push는 핵심 목적이므로, 자동 이동의 범위를 사용자가 바로 예측 가능하게 만든다.
- 최소 구현: event에 `isFlexible` boolean을 두고 충돌 시 이후 flexible arc만 최소 필요 분만큼 순서대로 이동한다; 변경 전 `3개 일정 +25분` preview와 `Undo` button(10초)을 toast가 아닌 고정 inline bar로 둔다.
- skip if: 자정 너머, 고정 이벤트 충돌, 또는 유효한 빈 공간이 없는 경우에 자동으로 일정 길이를 줄이거나 삭제하지 않는다.

### C6. drag 끝점은 보이되 손가락 표적은 충분히 크게

- 출처/실제: [TimeTree event move/copy 도움말](https://support.timetreeapp.com/hc/en-us/articles/207993013-How-to-move-and-copy-events)은 calendar event를 long press로 이동하는 직접 조작을 제공한다.
- 대상/적합: **calendar**의 arc resize는 원형 끝점이 작아지기 쉬우므로, 현재의 end-drag 핵심을 모바일에서도 실수 없이 보존한다.
- 최소 구현: 시각 handle은 arc 끝 `8px` dot이되 invisible `28px` pointer target을 별도 SVG element로 둔다; `aria-label="시작 시간 조절"`/`"종료 시간 조절"`, keyboard `Shift+Arrow` 5분 조절도 제공한다.
- skip if: SVG hit target 확장이 이웃 arc의 선택을 가로채는 고밀도 일정에서는, 선택된 event에만 handle을 보인다.

### C7. focus timer는 하나의 현재 일정만 강조한다

- 출처/실제: [Sunsama Timeboxing 기능](https://www.sunsama.com/features/timeboxing)은 time-boxed session을 timer로 실행하고, task가 고정되면 나머지 task가 그 주위로 흐르게 한다.
- 대상/적합: **calendar**의 focus timer는 원형 day planner의 ‘지금 할 일’을 선명하게 하되, 전체 일정 편집 기능을 숨기지 않아야 한다.
- 최소 구현: 선택 arc의 중앙에 `25:00`과 `일시정지`를 표시하고 해당 arc만 3px accent stroke; timer 종료 시 `완료`/`5분 연장` 두 button, 나머지 arc는 `opacity: .55`까지만 낮춘다.
- skip if: focus를 시작하면 drag·resize·일정 추가를 막아야 한다면, 잠금 대신 종료 후의 변경 여부만 확인한다.

## interview — interview.agenticfabworks.com

### I1. 녹음 전 권한 요청은 클릭 직후 한 번만

- 출처/실제: [Yoodli Practice](https://support.yoodli.ai/en/articles/9550465-practice-with-yoodli)는 Start 뒤 microphone/camera 권한을 요청하고 countdown 뒤 말하기를 시작한다.
- 대상/적합: **interview**는 브라우저 local recording이 목적이므로, 처음부터 권한 배너를 던지지 않고 사용자의 녹음 의도에 연결해야 한다.
- 최소 구현: `녹음 시작` click에서만 `getUserMedia({audio:true, video:true})`; 승인 뒤 3초 `3·2·1` countdown, 거절 시 `브라우저 주소창에서 카메라/마이크 허용`의 정적 도움말과 재시도 button을 보인다.
- skip if: audio-only 모드가 현재 제품의 명시 기능이면 camera 권한을 함께 요구하지 않는다.

### I2. 한 질문의 녹음은 저장 전 언제든 다시 시도

- 출처/실제: [Big Interview Record your Interview](https://support.biginterview.com/en/article/practice-sets-1p0blzg/)은 질문 재생 → Start Recording → Save answer → Next question 순서로 응답을 남긴다.
- 대상/적합: **interview**는 연습용이므로 재시도 횟수나 점수 압박 없이, 사용자가 자신의 답변을 고를 수 있어야 한다.
- 최소 구현: stop 뒤 `<video controls>` preview와 `다시 녹음`, `이 답변 저장` 2개 button; 새 녹음을 시작할 때에만 현재 blob을 교체한다고 명시하고, 저장 전에는 IndexedDB에 쓰지 않는다.
- skip if: 사용자가 녹음 직후 원본을 유지해야 하는 연구·평가 모드라면 재시도로 기존 blob을 덮어쓰지 않는다.

### I3. 로컬 저장의 위치·삭제·내보내기를 같은 자리에서

- 출처/실제: [Big Interview의 저장 답변 검토](https://support.biginterview.com/en/article/rating-and-reviewing-practice-videos-1dck9ye/)는 저장된 답변을 별도 목록에서 다시 열어 검토하는 흐름을 제공한다.
- 대상/적합: **interview**의 핵심 약속은 browser local storage이므로, ‘어디에 있고 어떻게 없애는지’를 실제 녹음 카드에서 확인시켜야 한다.
- 최소 구현: saved recording card footer에 `이 브라우저에만 저장됨`, `내보내기`, `삭제`를 둔다; delete는 2-click confirm(버튼 문구가 `정말 삭제`로 변함), export는 `URL.createObjectURL(blob)` download만 사용한다.
- skip if: 실제로 서버 업로드·백업·analytics가 있으면 local-only 문구나 브라우저 내 export만으로 신뢰를 대체하지 않는다.

### I4. 다음 시도용 짧은 자기평가, 채점은 하지 않는다

- 출처/실제: [Anki Studying](https://docs.ankiweb.net/studying.html)에서는 답을 본 뒤 Again/Hard/Good/Easy를 사용자가 선택하며 키 `1`–`4`와 다음 복습 시점을 함께 보여 준다.
- 대상/적합: **interview**는 녹음 연습의 반복을 돕되 자동 점수나 AI 평가를 새로 넣지 않고, 사용자의 즉시 회고만 남긴다.
- 최소 구현: 저장 뒤 `다시 해볼 점` 단일 `<textarea maxlength="180">`와 `좋음/다시 연습` 2-state button을 노출한다; `Ctrl/Cmd+Enter`로 저장, notes는 recording id에 붙여 IndexedDB에 저장한다.
- skip if: 현재 화면이 완전히 무평가·무기록인 1회성 연습으로 설계됐고 메모가 부담을 높이면 이 회고를 기본 노출하지 않는다.

## 도입 우선순위

1. **T1 최근 사용 검색 상태** — 기대 효과: 17개 도구에서 재방문 경로를 1회 키 입력으로 단축; 노력: S, `localStorage`와 기존 card data만 사용.
2. **S2 OMR 답/검토 분리** — 기대 효과: 사용자 문제집 기반이라는 skct의 본질을 보강하고 재검토 실수를 줄임; 노력: M, 별도 저장 key와 상태 클래스.
3. **C5 flexible cascade preview+Undo** — 기대 효과: calendar의 차별 기능을 예측 가능하게 하며 자동 이동 불안을 낮춤; 노력: M, 순차 충돌 계산과 10초 undo snapshot.
4. **I1 의도 기반 권한+3초 countdown** — 기대 효과: interview의 첫 녹음 실패를 줄이고 사생활 기대를 명확히 함; 노력: S, `getUserMedia` 오류 분기.
5. **T2 150ms 즉시 계산 결과** — 기대 효과: 계산기 페이지의 단일 목적을 강화하고 불필요한 submit click 제거; 노력: S, input listener와 output 상태.
6. **H3 범위가 명시된 trust note** — 기대 효과: hub의 ‘기기에 남음’ 주장을 검증 가능한 약속으로 전환; 노력: S, 실제 데이터 흐름 감사 후 3행 카피.
7. **S1 고정 시험 상태/검토 카운트** — 기대 효과: skct 장시간 연습의 위치·시간 인지를 개선; 노력: S, header와 OMR anchor.
8. **C6 arc 끝점 28px hit target** — 기대 효과: orbit의 resize를 모바일에서도 신뢰할 수 있게 함; 노력: M, SVG pointer events와 키보드 조절.

## 제외한 패턴

- Google Interview Warmup의 실시간 전사·키워드 분석은 [2026년 종료 보도](https://www.aceround.app/blog/google-interview-warmup-review/)가 있어 출처 제품을 현재 live reference로 채택하지 않았다; 또한 현 제품의 local-only 녹음 약속에 서버 음성 분석을 섞지 않는다.
- Motion식 완전 자동 스케줄러는 [자동 재배치](https://www.usemotion.com/help/time-management/auto-scheduling)가 강점이지만, calendar의 사용자가 직접 arc를 조작하는 목적을 대체하므로 flexible cascade 범위만 참고한다.
- Vercel/Linear식 전역 command palette는 [Vercel 기준](https://vercel.com/geist/command-menu)상 수십 개 전역 자원에 알맞다; tools의 17개 검색과 skct의 화면 조작에는 새 오버레이·framework보다 기존 검색/버튼 단축키가 작다.
- 자동 재생 동영상, 과도한 reveal 애니메이션, signup/paywall 유도, 가짜 ‘n명이 사용 중’ 표시는 현재 목적·정직성·정적 CSP 제약에 맞지 않아 제외한다.
