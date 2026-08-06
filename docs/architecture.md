# AICC 구조

```text
Codex Desktop -> Web GPT bridge 17841 -> ChatGPT Web (Web 모델 추론)
                 |                         |
                 |                         \-> Web GPT 작업 하네스 전용 Tunnel
                 |                             -> 현재 Codex 작업의 광고된 도구
                 \-> OCX 10100 (Web 외 모델)

Native Codex profile -> OpenAI 공식 Codex endpoint

외부 ChatGPT -> AICC 원격 작업공간 전용 Tunnel -> AICC 원격 작업공간 MCP (STDIO)
                                             -> 별칭으로 등록된 Git workspace
```

네 기능은 인증·추론·상태를 섞지 않는다. Workspace MCP는 OCX provider나 Codex
catalog를 수정하지 않고, OCX는 Tunnel profile과 ChatGPT connector를 수정하지
않는다. Web GPT 브리지는 Web 모델만 ChatGPT Web에서 추론하고 Web 외 모델은 기존
OCX upstream으로 전달한다. 다만 Codex Desktop은 한 번에 하나의 전역 API base를
사용하므로, 17841이 선택된 profile에서 브리지가 중지되면 모델 선택기 전체가
영향받을 수 있다. Native/OCX profile 전환은 실행 중 작업이 없는 시점에 한다.

Web GPT 작업 하네스 전용 Tunnel과 AICC 원격 작업공간 전용 Tunnel은 이름만 다른 동일
런타임이 아니다. 전자는 `codex-chatgpt-web mcp`를 실행해 현재 Codex turn broker에
연결하고, 후자는 AICC의 고정 `components/workspace-mcp/server.mjs`를 실행한다.
명령·수명주기·복구 책임이 다르므로 Tunnel ID와 profile을 공유하지 않는다.
대시보드와 로그인 시 자동 시작·상태 수집은 AICC가 하나로 통합 관리하지만 전송
Tunnel은 분리한다. 하나의 범용 MCP가 두 역할을 multiplex하는 구현은 기술적으로
가능하더라도, 외부 ChatGPT 고정 권한과 현재 Codex turn의 동적 권한을 같은 장애·
승인 경계에 놓게 되므로 채택하지 않는다.

AICC 원격 작업공간 MCP는 고정 도구만 게시한다. 파일과 명령은 `workspace_id + lease`로
하나의 등록 workspace에 묶이고, 경로·심볼릭 링크·민감 파일을 검사한다. 명령은
macOS seatbelt에서 실행하며 home의 다른 경로를 읽지 못하고 선택 workspace와
private runtime 경로에만 쓸 수 있다. 브라우저와 Computer Use는 이 MCP에 넣지
않는다. Codex Web GPT 모델에서는 현재 Codex 작업에 실제로 광고된 도구만 프로젝트
경계 allowlist를 통과해 사용할 수 있다. 외부 ChatGPT의 AICC Workspace 앱은
파일·터미널·AICC 스킬 도구만 제공한다.

정본은 AICC 저장소다. 인증, runtime key, Tunnel profile, workspace registry와
LaunchAgent는 `~/.ai-control-center` 및 사용자 LaunchAgents에 둔다. macOS 로그인
시 AICC 대시보드, Workspace Secure Tunnel, OCX와 설정 완료된 Codex Web GPT가 자동
시작된다. 한 경로의 장애를 다른 계정·provider·브라우저로 숨기지 않는다.

## 공개·개인 버전 경계

- `AICC` public: 재사용 가능한 코드, 문서, 테스트와 일반화된 `guidance/` 정본
- `my-AICC` private: public AICC 버전 pin, 비밀 없는 설치 manifest와 개인 overlay
- 인증 JSON, 계정 DB, task DB, Tunnel/API key, 쿠키, 브라우저 프로필과 키체인은
  private Git에도 올리지 않는다.
- 절대 경로는 `${HOME}` 또는 설치 시 선택한 root로 치환하고 개인 계정 alias는
  private overlay에서만 관리한다.

## 참고 upstream의 현재 지위

| 프로젝트 | 현재 지위 |
|---|---|
| OpenCodex(OCX) | Codex Desktop의 선택 provider 라우터 |
| `codex-chatgpt-web` | Codex Desktop의 Web 모델 브리지. AICC fork를 별도 릴리스하고 OCX upstream을 보존한다. |
| CodexPro | 현재 AICC 런타임에서 사용하지 않으며 복구 대상도 아님 |
| `Waishnav/devspace` | workspace 제어 아이디어만 비교했고 의존성으로 채택하지 않음 |
| Obsidian JSON Canvas | 구조 지도의 카드·연결선 표현과 공개 `.canvas` 내보내기 규격만 참고 |

`devspace`는 AICC나 `codex-chatgpt-web`에 서브모듈·패키지·실행 프로세스로 합쳐진
것이 아니다. 채택한 것은 범용 workspace 선택·경계·도구화라는 설계 아이디어이고,
실제 구현과 유지보수 책임은 AICC의 `components/workspace-mcp`에 있다.

대시보드 구조 지도는 브라우저에서 직접 렌더링하므로 Obsidian이나 커뮤니티
플러그인이 필요 없다. 같은 내용을 `public/aicc-architecture.canvas`로 제공해
Obsidian 내장 Canvas에서도 열 수 있다. Excalidraw와 Dataview는 각각 자유형 시각화와
Markdown 질의에는 유용하지만 AICC 실시간 상태판의 런타임 의존성으로 채택하지 않는다.

## 사용자에게 보이는 두 MCP 이름

| 표시 이름 | 어디서 시작하는가 | 범위 | 이전 이름 또는 실제 앱 이름 |
|---|---|---|---|
| Web GPT 작업 하네스 MCP | Codex Desktop에서 Web 모델을 선택 | 현재 Codex 작업의 동적 도구 | 이전 `Codex Native MCP`; 네이티브 Codex 모델과 무관 |
| AICC 원격 작업공간 MCP | 폰·웹 ChatGPT에서 앱을 선택 | 등록 Git 작업공간과 13개 고정 도구 | 현재 ChatGPT 앱 이름 `AICC Workspace` |

둘은 모델이 아니다. 전자는 Codex에서 시작된 Web GPT turn이 현재 Codex 도구를 다시
호출하는 경로이고, 후자는 ChatGPT에서 시작된 대화가 독립적으로 등록 작업공간을
호출하는 경로다. 운영 상태는 AICC 한 화면에서 보되 Tunnel ID와 권한은 공유하지 않는다.

구형 v1 브리지 설정, 과거 에이전트 스택, 폐기 provider·port·스킬은 복구 대상으로
취급하지 않는다. 현재 v2 Web GPT 앱, 17841 bridge와 3경로 복구 문서만 유지한다.
