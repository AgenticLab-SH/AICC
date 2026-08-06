<!-- AgenticFabWorks 화면 설계·구현용 압축 참조 파일이다. -->
<!-- 새 화면을 설계하거나 React/CSS/상호작용을 구현·검수할 때 불러온다. -->
<!-- 이 문서는 압축 정본이며 원본은 삭제됨. -->
# AgenticFabWorks 디자인 시스템

## 목차

- [디자인 토큰](#디자인-토큰)
- [화면 밀도와 정보 구조](#화면-밀도와-정보-구조)
- [컴포넌트 규칙](#컴포넌트-규칙)
- [반응형 기준](#반응형-기준)
- [모션과 인터랙션](#모션과-인터랙션)
- [현대식 기법](#현대식-기법)
- [프런트엔드 구조](#프런트엔드-구조)
- [금지 사항](#금지-사항)
- [빠른 점검](#빠른-점검)

# 디자인 토큰

## 간격·radius

| 토큰 | 값 |
|---|---:|
| spacing | 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96px |
| radius small | 8px |
| radius medium | 12px |
| radius large | 16px |
| radius overlay | 20~24px |

- 임의 간격 대신 spacing scale을 우선 사용하고, 랜딩은 여백·도구는 핵심 캔버스/문제 영역에 공간을 우선 배정한다.
## 타이포

| 역할 | size / line-height |
|---|---|
| Caption | 12px / 16px |
| Compact UI | 13px / 18px |
| Body compact | 14px / 20px |
| Body | 16px / 24px |
| Section | 20px / 28px |
| Page title | 24~32px / 32~40px |
| Landing hero | `clamp(40px, 6vw, 72px)` |

- 본문과 주요 컨트롤을 14px 미만으로 내리지 않는다.
- 12px는 보조 데이터 라벨에만 쓴다.
- 짧은 영문, KO/EN 혼용, 200% zoom에서도 잘림을 확인한다.
## 컨트롤·색·명암

| 대상 | 값 |
|---|---|
| compact desktop control | 32~36px |
| default control | 40px |
| touch control | 44~48px |
| icon visual | 16~20px |
| icon hit area | 최소 40px; touch 44px 권장 |
| 화면당 강한 accent | 최대 2개 |
| 접근성 목표 | WCAG 2.2 AA |

- 포인터 기반 밀집 도구에서만 compact variant를 허용한다.
- semantic color와 service accent를 분리하며 색만으로 선택·오류·팀을 구분하지 않는다.
- 다크 모드의 순수 검정·순수 흰색을 남용하지 않고, 데이터 시각화에는 색맹 안전 팔레트·범례를 제공한다.
- 원본은 명암비 숫자를 정하지 않았으므로 WCAG 2.2 AA를 확인하되 임의 비율을 토큰화하지 않는다.
- 서비스 전체는 한 SVG 아이콘 계열을 쓰고, 이모지와 모호한 단독 기호를 쓰지 않는다.
- 저장·내보내기·프리셋·프로젝트는 서로 다른 아이콘과 문구로 구분한다.
# 화면 밀도와 정보 구조

## 밀도 선택

| 밀도 | 적용 | 규칙 |
|---|---|---|
| Comfortable | 랜딩·온보딩·계정·결제 | 여백과 설명을 넉넉히 둔다. |
| Compact | 캘린더 편집·FBTT 설정·SKCT 시험 | 32~40px 컨트롤, 설명은 분리, 핵심 작업 영역 우선. |

- 사용자 선택보다 환경·화면 목적에 맞는 density 기본값을 정한다.
- 랜딩은 실제 제품·짧은 모션·신뢰/데이터 정책으로 기능 이해를 우선하고, 도구는 장식 최소화·단축키·Undo·패널 접기/탭화·즉시 상태 피드백을 제공한다.
## 계층·행동

- 글로벌 헤더에는 로고·서비스 이동·언어·계정, 서비스 툴바에는 현재 작업 항목만 둔다.
- 설정·백업·튜토리얼·계정은 메뉴로 이동하고, 화면당 Primary 버튼은 1개만 둔다.
- 저장/자동 저장의 차이를 명확히 하고 삭제·초기화·해지는 danger 영역으로 분리한다.
- 복잡한 기능은 단계적으로 노출하고, 핵심 캔버스·문제 영역을 첫째로 둔다.
- 0 또는 빈 문자열로 데이터 없음을 표현하지 않는다.

## 레퍼런스 채택

- 문제를 한 문장으로 정의하고 서비스 유형·화면 목적을 먼저 정한다.
- 6개 갤러리에서 후보 5~10개를 수집하고 실제 제품 URL의 desktop·mobile을 확인한다.
- 기능 유사성·정보 밀도·반응형·접근성 가능성·성능 부담·브랜드 적합성·구현 비용을 각 1~5점으로 평가한다.
- 최종 1~3개만 채택해 복제가 아닌 적용 원리를 기록하고, 카드에는 출처·실제 사이트·적용/제외 원리·반응형·접근성/성능을 남긴다.
- 랜딩은 Lapa Ninja·Land-book·Godly, 제품 미리보기는 Godly·Recent, 절제된 타이포는 SiteInspire·Land-book을 우선 탐색한다.
- 모션 상한선은 Godly·Awwwards에서 관찰하되 최소화는 Apple HIG·실제 도구형 SaaS를 따른다.

### 무료 컴포넌트 후보

현재는 무료·오픈소스 근거를 확인한 후보만 구현 대상으로 삼는다. 2026-08-06
확인 기준으로 Magic UI, SmoothUI, daisyUI는 공식 저장소가 MIT를 명시한다.
`component.gallery`는 코드 공급처가 아니라 표준 이름과 디자인 시스템 사례를 찾는
사전으로만 쓴다.

| 후보 | 쓰임 | 채택 전 확인 |
| --- | --- | --- |
| [The Component Gallery](https://component.gallery/) | 패턴 이름·사례 탐색 | 코드 복사 금지; 실제 구현 출처를 별도 확인 |
| [Magic UI](https://github.com/magicuidesign/magicui) | React/Tailwind 랜딩 모션 | 해당 파일 의존성, 번들, reduced-motion, MIT notice |
| [SmoothUI](https://github.com/educlopez/smoothui) | shadcn 호환 모션 | production registry, Motion 의존성, fallback, MIT notice |
| [daisyUI](https://github.com/saadeghi/daisyui) | Tailwind 기본 UI | 현재 Tailwind 호환성, dependency/copy 방식별 MIT notice |

무료라는 말만으로 채택하지 않는다. 실제 source ref, license, 유지보수 상태,
접근성, CSP, 현재 stack을 다시 확인하고 한 화면에는 한 체계만 사용한다. 유료 전용,
출처·license 미확인, 생성 결과의 재배포 조건이 불명확한 후보는 `deferred`로 둔다.
# 컴포넌트 규칙

## 버튼·아이콘

- `Primary`는 현재 단계 완료, `Secondary`는 보조 완료, `Ghost`는 보기/설정/낮은 우선순위, `Danger`는 삭제·초기화·해지에만 쓴다.
- `Icon` 버튼에는 보이는 레이블 또는 접근성 이름을 반드시 제공한다.
- 비핵심 기능은 툴바 wrap 전에 overflow menu로 이동한다.

## 툴팁·Popover

| 항목 | 규칙 |
|---|---|
| 용도 | 아이콘 의미·단축키·짧은 수치 정의 |
| hover delay | pointer hover 후 400~600ms |
| keyboard focus | 즉시 표시 |
| 길이 | 1~2문장, 240~320px 이내 |

- 필수 사용법, 오류 해결, 모바일 필수 정보, 복잡한 폼 설명을 tooltip에 넣지 않는다.
- tooltip 내부에 핵심 인터랙션을 넣지 않는다.
- 간단한 설정에는 Popover API 또는 동등 popover를 쓰며, 미지원 시 접근 가능한 positioning/focus fallback을 제공한다.
## Modal·sheet

- 집중 편집에는 `Dialog` 기반 Modal, 모바일 보조 작업에는 Bottom sheet, 전체 흐름에는 별도 페이지/step flow를 쓴다.
- Modal·sheet에는 닫기, `Escape`, focus trap, 원래 focus 복귀를 제공한다.
- Modal·sheet는 어느 viewport에서도 화면 밖으로 나가지 않게 한다.

## 폼·상태

- inline validation을 사용하고, 드래그만 제공하지 말고 키보드·폼 입력 대체 수단을 둔다.
- `idle`, `loading`, `empty`, `success`, `partial`, `stale`, `error`, `permission denied`, `offline`을 서로 다른 UI로 모델링한다.
- loading/error/empty·긴 텍스트·KO/EN은 isolated harness에서 확인하고, 선택/오류에는 색 외 텍스트·아이콘·형태 신호를 둔다.

# 반응형 기준

## 측정·컨테이너

| 검수 viewport | 값 |
|---|---|
| mobile small | 320×568 |
| mobile | 390×844 |
| tablet | 768×1024 |
| small laptop | 1024×768 |
| desktop | 1280×720, 1440×900, 1920×1080, 2560×1440 |
| zoom | 80, 100, 125, 150, 200% |
| DPR | 1, 1.25, 1.5, 2 |

| 컨테이너 | 값 |
|---|---|
| landing max-width | 1200~1280px |
| tool shell max-width | 1440~1600px 또는 전체 폭 |
| reading body | 680~760px |
| mobile gutter | 16px |
| tablet gutter | 24px |
| desktop gutter | 32~48px |

- breakpoint는 기기명·인치가 아닌 콘텐츠가 깨지는 지점에 두고, page에는 media query·컴포넌트에는 container query를 우선한다.
- 모바일은 작업 우선순위를 재배열하며 제목/큰 여백은 `clamp()`, 패널은 `minmax()`·`fit-content()`, 캔버스는 부모 크기 기반 계산을 쓴다.
- ellipsis만으로 텍스트를 숨기지 말고 전체 이름 확인 수단을 둔다.
## 앱 셸 전환

| 조건 | 전환 |
|---|---|
| desktop | global header → service toolbar → sidebar \| primary workspace \| contextual panel |
| sidebar | 232~304px |
| contextual panel | 280~360px |
| primary workspace | 최소 640px |
| workspace < 640px | sidebar 또는 contextual panel 하나를 tab/drawer로 전환 |
| tablet | workspace 우선; sidebar는 rail/drawer; contextual panel은 bottom/side sheet |
| mobile | header 최소화; workspace를 상단; 보조 설정은 bottom sheet |

- 모바일의 긴 좌측 탭은 상위 탭 + 하위 segmented control 또는 `select`로 바꾼다.
- Calendar desktop은 Orbit 60~70% + 우측 탭, 작은 노트북은 우측 패널 접기를 허용한다.
- Calendar mobile은 Orbit + 현재 일정 + bottom-sheet timeline으로 전환한다.
- FBTT preview는 sticky로 유지하고 모바일은 설정/preview를 단계형으로 전환하며, 1280×720에서도 최소 작업 크기를 보장한다.
- SKCT는 문제 영역과 답안 1~5 기반 OMR 폭을 우선하고, 시험 중 비핵심 메뉴를 제거하며 mobile OMR은 compact panel/bottom sheet로 제공한다.
## 완료 조건

- 가로 스크롤·핵심 버튼 잘림·viewport 밖 Modal/sheet를 허용하지 않고, sticky 요소가 focus를 가리지 않게 한다.
- 200% zoom에서 핵심 흐름을 끝내며, mobile hover 전용 기능을 두지 않고 orientation 뒤 상태를 보존한다.
# 모션과 인터랙션

## 시간·easing

| 대상 | duration |
|---|---|
| press/hover feedback | 80~120ms |
| tooltip/popover | 120~180ms |
| tab/panel | 160~220ms |
| modal/sheet | 200~300ms |
| page/shared element | 240~360ms |
| scroll reveal | 300~500ms, 1회만 |

- 모션은 입력 반영·출발/도착·공간 계층·상태 연결·직접 조작 피드백 중 하나를 해야 한다.
- 진입은 빠르게 시작해 부드럽게 정지하고 퇴장은 빠르게 사라지게 하며, spring은 drag release·reorder·snap 같은 물리 관계에만 쓴다.
- 중요한 데이터는 애니메이션 종료 전에도 읽을 수 있게 하고, 결과에는 Undo를 제공한다.

## 스크롤·전환·드래그

- 섹션 최초 1회 `opacity` + 8~16px `translate`를 허용한다.
- 카드 3~6개에는 40~70ms stagger, 제품 목업에는 짧은 상태 시연만 허용한다.
- 반복 설정 reveal·스크롤 가로채기·큰 parallax·지연 콘텐츠 순서·매번 재등장 카드를 금지한다.
- 탭은 짧은 crossfade/방향성 slide를 쓰고 shared element는 동일 객체에만 쓰며 URL·focus·scroll restoration을 우선한다.
- 드래그에는 가능 신호·원래/예상 위치·실시간 시간/수치·충돌/snap·release 결과/Undo를 제공한다.
## 로딩·reduced motion

- 300ms 미만 작업에는 spinner를 깜빡이게 하지 않는다.
- 레이아웃을 알면 skeleton, 진행률을 알면 determinate progress를 쓰며 장기 작업은 취소·백그라운드·완료 알림과 `stale` 유지 선택지를 제공한다.
- 2초를 넘길 수 있는 작업은 이전 데이터 유지 여부, 현재 단계, 취소 또는 이탈 가능 여부,
  재시도 조건을 함께 보여 준다. 결제·삭제·권한·중요 설정에는 optimistic UI를 쓰지 않는다.
- `prefers-reduced-motion: reduce`에서는 거리 이동·parallax·자동 재생을 중단하고 duration 축소/crossfade로 대체하되 기능적 상태 변화·필수 실시간 캔버스의 정적 요약은 유지한다.
# 현대식 기법

- `@container`/container queries는 재사용 컴포넌트의 크기 기반 전환에 사용하고, page 레이아웃은 media query로 유지한다.
- `Popover API`는 tooltip·simple popover·non-modal panel에 조건부 사용하고 fallback을 반드시 둔다.
- `View Transition API`는 화면 상태·페이지 전환의 progressive enhancement로만 사용하며, 미지원 브라우저는 즉시 전환한다.
- `Dialog`는 실제 Modal에 쓰고 native 지원/동작을 확인하며 동등한 focus fallback을 유지한다.
- `ResizeObserver`는 캔버스/Orbit, `AbortController`는 취소, `Web Worker`는 큰 계산, `OffscreenCanvas`는 실제 성능 필요 시에만 쓴다.
- `Service Worker`는 명확한 오프라인/알림 요구에만 쓰고, 표준 API는 Baseline·compatibility·feature detection과 fallback 없이는 채택하지 않는다.
- CSS transition/animation은 기본 microinteraction, Web Animations API는 제어형, Motion은 복잡 React layout/gesture, GSAP은 마케팅 서사에 한정한다.
- 기능적 3D·데이터 시각화가 아니면 WebGL을 쓰지 않는다.
# 프런트엔드 구조

## 경계·상태

- 기존 stack·`package.json`·lockfile을 먼저 존중하고, SEO/SSR/server 메인은 Next.js 계열·로컬 중심 복잡 SPA는 React + Vite를 검토한다.
- 공통 design token·UI·schema는 프레임워크 독립 공유하고 feature/domain 중심으로 화면·도메인·data fetching·display를 분리한다.
- `ErrorBoundary`/route error와 loading·empty·error state를 두며 memoization은 측정 뒤, `effect`는 외부 동기화에만 쓰고 파생 상태를 중복 저장하지 않는다.
| 상태 | 저장 대상·계약 |
|---|---|
| URL state | 탭·검색·필터·선택 id; 새로고침·공유·뒤로가기 보존 |
| Server state | query cache·stale time·retry·cancellation; 공식 데이터의 `fetchedAt`·`source`·`status` |
| Persistent local state | versioned schema·validation·migration·저장 실패/quota/손상 처리 |
| Ephemeral UI | modal·popover·current drag; 영속 store 금지 |
| Form state | 제출 전 입력과 validation |

- 영속 데이터에는 `schemaVersion`, 생성/수정 시각, migration 함수, 검증 schema, 손상 격리, backup 전후 checksum 또는 동등 무결성 검증을 둔다.
- 서로 다른 상태를 하나의 거대한 store에 넣지 않는다.

## TypeScript·데이터 계약

- TypeScript `strict`를 쓰고 `any`는 금지/국소 격리하며 외부 입력은 runtime schema·상태는 discriminated union으로 검증한다.
- `px`·`ms`·`id`·`count` 단위 혼동을 막고 exhaustive checking과 API/storage 단일 계약 타입 생성을 한다.
- controlled/uncontrolled 계약을 명확히 하고 `forwardRef`/imperative API는 실제 focus/canvas에서만, 접근성 이름·상태는 props 계약에 넣는다.
## CSS·성능·접근성

- design token CSS variables와 중앙 z-index scale(원본 수치 미지정)을 사용하며 inline style 하드코딩을 최소화한다.
- cascade layer, logical property, `clamp`, `minmax`, `subgrid`를 상황에 맞게 사용한다.
- route/feature code splitting, 큰 chart/export lazy load, 이미지 dimensions를 기본으로 하고 font subset/preload·긴 목록 virtualization은 측정 뒤 최소 적용한다.
- `pointermove`·`resize`는 throttle/`requestAnimationFrame`, 비싼 계산은 profiler 확인 뒤 memoize하며 실제 사용자 p75 Web Vitals를 route·device class·release별로 수집한다.
- 목표: LCP 2.5s 이하, INP 200ms 이하, CLS 0.1 이하; p75 field data를 우선한다.
- semantic HTML·visible focus·keyboard-only·screen reader·색 대비·reduced motion을 확인하고, axe `critical`·`serious`는 0이어야 한다.
- 자동 검사는 수동 키보드/스크린리더를 대체하지 않으며 문자열 분산을 금지하고 KO/EN 키 동일성·`Intl` 처리를 적용한다.
# 금지 사항

- 기능보다 큰 WebGL 히어로를 만들지 않는다.
- 스크롤을 가로채는 장면 전환·비표준 스크롤·과도한 parallax를 쓰지 않는다.
- 긴 로딩 인트로·cursor follower·제품 무관 3D 장식·저대비 초소형 텍스트를 쓰지 않는다.
- 모바일 핵심 기능을 없애거나 hover에만 의존하지 않는다.
- tooltip에 필수 조작·오류 해결을 숨기지 않는다.
- `0/0`, 0, 빈 문자열로 선택 전·데이터 없음·오류를 위장하지 않는다.
- business rule을 display component에 숨기지 않는다.
- canary/preview를 운영 핵심 흐름에 넣거나 기능 변경과 framework major upgrade를 같은 PR에 넣지 않는다.
- 표준 API 지원 확인 없이 의존성을 추가하거나 fallback 없이 채택하지 않는다.
- 실제 두 곳 이상의 같은 계약 확인 전 공통 코드를 추출하지 않고 secret·token·복구 키·원문 답변·민감 데이터를 log/telemetry에 기록하지 않는다.
- 모션 때문에 콘텐츠 순서·URL·focus·scroll restoration을 희생하지 않는다.
# 빠른 점검

- [ ] spacing/radius/type/control 값이 토큰 표와 일치하고 본문·주요 컨트롤이 14px 이상인가?
- [ ] 화면당 Primary 1개, 강한 accent 최대 2개이며 상태가 `empty/error/stale`까지 명시됐는가?
- [ ] 320×568, 390×844, 768×1024, 1280×720, 200% zoom에서 핵심 흐름과 focus가 유지되는가?
- [ ] workspace가 640px 미만이 되면 패널을 tab/drawer로 전환하고 가로 스크롤이 없는가?
- [ ] keyboard, `Escape`, modal focus trap/restore, mobile 대체 조작이 동작하는가?
- [ ] 모션 duration·reduced-motion·fallback이 규칙에 맞고 300ms 미만 로딩에 spinner가 없는가?
- [ ] URL/server/persistent/ephemeral/form state와 API/storage schema 계약이 분리됐는가?
- [ ] LCP 2.5s·INP 200ms·CLS 0.1 목표, axe critical/serious 0, p75 수집을 확인했는가?
