# 현재 운영 상태와 사용법

이 문서는 AICC 통합 작업이 끝난 뒤의 실제 운영 구조, 사용 방법과 기존 결정의
결론을 한곳에 정리한 정본이다. 개인 계정 이름, 조직 ID, Tunnel key, 브라우저
프로필 내용은 저장소에 기록하지 않고 private coordination과 각 도구의 소유자 전용
상태에서 관리한다.

## 2026-08-06 검증 스냅샷

- AICC 상태: 9/9 ready
- AICC 정본 스킬: 16개, Codex agent: 1개
- Workspace MCP: 등록 Git 워크스페이스 38개, Secure Tunnel ready
- Codex Desktop 기본 경로: OCX `127.0.0.1:10100`
- AICC 로컬 대시보드: `127.0.0.1:4381`
- 폐기 포트 `17841`, `4317`, `8787`, `8795`: listener 없음
- 기본 HTTP/HTTPS/HTML 브라우저: CDP Whale 9335
- ChatGPT Chrome Extension: private coordination이 지정한 9223 프로필 한 곳만 유지
- GitHub CI: Linux, macOS, Windows의 Node 20/22와 public-safety 모두 통과
- OCX live model API: `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`만 반환하며
  `webgpt/*`는 0개

숫자와 실행 상태는 시간이 지나면 달라질 수 있다. 현재 상태는 다음 명령으로 다시
확인한다.

```bash
aicc status --json
aicc cli status
aicc agents status
aicc guidance check
aicc workspace status
ocx status
ocx health
```

## 최종 구조

```text
Codex Desktop -> OCX 10100 -> OpenAI/Kiro 등 선택 provider
               \-> ocx restore 후 Native Codex

ChatGPT Web -> OpenAI Secure MCP Tunnel -> AICC Workspace MCP (STDIO)
                                         -> 등록된 Git 워크스페이스 한 곳

Codex/Web 조사 -> 내장 Browser 또는 등록 CDP Chrome의 task-owned target
```

세 경로의 역할은 다음처럼 구분한다.

| 경로 | 용도 | 다른 경로 장애의 영향 |
|---|---|---|
| OCX | Codex Desktop 기본 모델 라우팅 | Workspace MCP와 무관 |
| Native Codex | OCX 장애 시 공식 endpoint 복구 | Workspace MCP와 무관 |
| AICC Workspace MCP | Web ChatGPT의 등록 로컬 프로젝트 읽기·편집·명령 | OCX와 무관 |

Web ChatGPT를 Codex 모델 provider로 보이게 하던 브리지와 커스텀 모델 목록은
폐기했다. 따라서 Web ChatGPT는 Codex 모델 선택기에 나타나지 않으며, OCX가
중단돼도 Workspace MCP는 독립적으로 동작한다.

과거 `webgpt/webgpt-saved-*`, `webgpt/webgpt-temporary-*`가 보이는 화면은 현재
OCX 응답이나 정본 catalog가 아니라 재시작 전 클라이언트가 들고 있던 모델 목록이다.
활성 작업을 끝낸 뒤 Codex 앱을 완전히 다시 열면 현재 catalog를 다시 읽는다. 이
목록을 AICC 이름으로 바꿔 재등록하지 않는다.

AICC 소스를 `~/.codex` 안으로 옮기거나 agent home을 AICC로 바꾸지 않았다. 제품
소스와 배포 정본은 일반 Git 워크스페이스에 두고, 인증·task DB·생성된 스킬은 각
하네스의 네이티브 home에 남기는 편이 업데이트, 복구와 계정 격리에 안전하기
때문이다.

## 일상 사용법

### 1. AICC 상태와 관리 화면

```bash
aicc open
aicc status --json
```

`aicc open`은 loopback 전용 관리 화면을 연다. 이 화면은 외부 인터넷에 공개하지
않는다. 계정·OCX 변경은 `aicc action preview`로 영향과 복구 방법을 확인한 뒤
일회용 확인 토큰으로 실행한다.

### 2. Codex Desktop 사용

평소에는 Codex Desktop이 OCX 10100을 사용한다. 모델 선택기에 보이는 OpenAI/Kiro
모델은 OCX catalog에서 제공되며, Web ChatGPT 모델은 없다.

OCX 장애로 Native Codex가 필요하면 실행 중인 task가 없는 안전한 시점에 다음을
수행한다.

```bash
ocx restore
```

그 뒤 Codex Desktop을 완전히 종료하고 다시 연다. OCX로 돌아갈 때는 10100 health를
먼저 확인하고 다음을 실행한 뒤 Desktop을 다시 연다.

```bash
ocx restore back
```

두 명령은 현재 task를 끊을 수 있으므로 에이전트가 활성 대화 중 자동 실행하지
않는다. 모델 선택기는 endpoint 전환기가 아니므로 가짜 `Native/...` 모델을 추가하지
않는다.

### 3. Web ChatGPT로 로컬 프로젝트 편집

ChatGPT Business에서 게시된 `AICC Workspace` 앱을 선택하고 다음 순서로 요청한다.

1. `aicc_workspace_list`로 등록 워크스페이스를 확인한다.
2. `aicc_workspace_open`으로 하나의 별칭을 열어 만료되는 lease를 받는다.
3. 읽기·검색·패치·명령·변경 검토 도구를 사용한다.
4. 새 작업이나 만료 뒤에는 워크스페이스를 다시 연다.

현재 Business에 게시된 앱은 아래 기본 10개 도구의 고정 스냅샷을 사용한다. 소스에는
Codex 작업 위임 5개를 더해 총 15개가 구현되어 있으며, 관리자 재게시 뒤에만 Web
ChatGPT에서 새 도구가 보인다.

| 도구 | 역할 |
|---|---|
| `aicc_workspace_list` | 등록 별칭 목록 |
| `aicc_workspace_open` | 한 워크스페이스 lease 발급 |
| `aicc_workspace_read` | 범위 안 파일 읽기 |
| `aicc_workspace_search` | `rg` 기반 검색 |
| `aicc_workspace_apply_patch` | 패치 적용 |
| `aicc_workspace_exec` | 샌드박스 명령 실행 |
| `aicc_workspace_write_stdin` | 실행 프로세스 입력·폴링 |
| `aicc_workspace_changes` | Git 변경 검토 |
| `aicc_skill_inventory` | AICC 정본 스킬 목록 |
| `aicc_skill_read` | 선택 스킬 지침 읽기 |
| `aicc_codex_task_list` | 선택 워크스페이스의 Codex 작업 목록 |
| `aicc_codex_task_read` | 안전하게 축약된 대화·상태 읽기 |
| `aicc_codex_task_create` | workspace-write Codex 작업 시작 |
| `aicc_codex_task_message` | 기존 Codex 작업에 후속 요청 |
| `aicc_codex_task_archive` | 완료 작업을 삭제 없이 보관 |

Codex 작업 위임은 Web GPT를 Codex 모델로 바꾸지 않는다. 별도 로컬 Codex `exec`
세션을 같은 `$CODEX_HOME`에 만들고, 조회·보관에는 일회성 app-server STDIO를 쓴다.
작업 프로세스는 MCP 요청 프로세스와 분리되어 요청 연결이 끝나도 계속되며, 작업은
Codex Desktop 목록에서 같은 로컬 세션으로 확인할 수 있다. 삭제와 무제한 Mac 권한은
노출하지 않는다.

임의 절대 경로, 선택 워크스페이스 밖 경로, 심볼릭 링크 탈출, 비밀 파일과 Git 내부
메타데이터는 차단한다. 쓰기와 명령은 lease가 필요하고 macOS 명령은 seatbelt
샌드박스에서 실행한다.

브라우저 창은 열어 둘 필요가 없다. Mac이 켜져 있고 로그인 세션, 인터넷,
`com.agenticlab.aicc-workspace-tunnel` LaunchAgent가 살아 있으면 백그라운드에서
동작한다. Mac이 꺼지거나 인터넷이 끊기면 로컬 편집은 불가능하다. 네트워크가
복구되면 Tunnel은 다시 연결되지만, 끊어진 순간의 모델 생성이나 실행 명령이
정확히 그 지점에서 자동 재개된다고 보장하지는 않는다. 상태를 다시 확인하고
해당 단계만 재시도한다.

### 4. Web GPT 조사와 기존 대화

Web GPT는 별도 데스크톱 브리지 이름이 아니라 일반 ChatGPT Web을 조사·검토
협업자로 사용하는 운영 방식이다.

- 기존 대화가 필요 없으면 검증된 Codex 내장 Browser에서 task-owned 새 대화를 쓴다.
- 기존 대화가 필요하면 private coordination이 지정한 계정·워크스페이스·CDP 경로를
  그대로 사용한다.
- 보통 `높음`, 복잡한 작업은 `매우 높음`을 사용한다.
- `Pro`는 사용자가 명시적으로 승인한 경우에만 선택한다.
- 임시/저장과 연속 대화는 ChatGPT Web 자체 기능을 사용한다.

같은 ChatGPT 대화는 정상적으로 연속 사용되며, 과거 브리지처럼 Codex 전체 문맥을
매 turn 새 대화에 긴 프롬프트로 재전송하지 않는다. 여러 Web ChatGPT 대화가 같은
MCP를 동시에 사용할 수 있지만 같은 파일을 동시에 수정하면 일반 Git 작업과 같은
충돌이 생길 수 있으므로 작업공간과 파일 소유권을 분리한다.

## 초기 개선안의 문제 처리 결과

| 기존 문제·우려 | 처리 결과 |
|---|---|
| DOM 자동화 실수, 여러 브라우저와 CPU/RAM 누수 | 모델 브리지와 별도 Web GPT 앱을 제거했다. 일반 ChatGPT Web과 필요할 때만 임대한 브라우저 target을 사용한다. 과거 브리지의 누수 경로는 없어졌지만 OCX·Codex·브라우저 자체 자원 사용까지 0이 되는 것은 아니다. |
| 매 turn 전체 컨텍스트 재전송과 빠른 한도 소진 | 브리지 전송 계층을 제거했다. ChatGPT는 자기 대화를 연속 사용하고 Codex는 자기 task 문맥을 관리한다. |
| 임시/저장/effort 조합이 모델 목록을 크게 차지함 | 중복 커스텀 모델을 모두 제거하고 ChatGPT Web의 네이티브 선택을 사용한다. |
| 병렬 Web GPT 작업 불안정 | 여러 ChatGPT 대화는 가능하되, 로컬 쓰기는 워크스페이스와 파일 소유권을 분리한다. |
| DevSpace 또는 별도 외부 서버 의존성 | 채택하지 않았다. OpenAI Secure MCP Tunnel이 직접 STDIO 서버를 실행하는 AICC 소유 구현을 사용한다. |
| 알 수 없는 외부 DB·프록시로 로컬 데이터 전송 우려 | AICC Workspace MCP에는 제3자 DB나 공개 reverse proxy가 없다. 도구 결과는 선택한 ChatGPT 대화로 반환된다. OCX 모델 요청은 사용자가 선택한 provider로 전달되는 것이 본래 기능이다. |
| 사용자가 같은 Web 대화를 열면 자동화가 충돌할 우려 | DOM 모델 브리지가 없어졌으므로 그 충돌 경로도 없다. task-owned 브라우저 target 원칙은 일반 Web 작업에만 남는다. |
| 인터넷 단절 중 작업 후 자동 재개 | 순수 Web 추론은 ChatGPT 대화에서 계속할 수 있지만 로컬 도구 호출은 Mac 연결이 돌아올 때까지 불가능하다. durable 작업 큐나 in-flight 자동 재개는 구현하지 않았고, 복구 뒤 실패한 단계만 재시도한다. |
| 모든 워크스페이스에 모든 권한 부여 | 38개 Git 워크스페이스를 등록했지만 무제한 권한은 주지 않았다. 별칭, lease, 경로 검사와 샌드박스를 유지한다. |

## 기존 질문과 결정의 답

| 질문 | 현재 답 |
|---|---|
| Web GPT가 Codex 모델 목록에 떠야 하나? | 아니다. 모델 provider 브리지를 폐기했고 일반 ChatGPT Web으로 사용한다. |
| Web GPT와 OCX는 독립적인가? | 그렇다. Web의 로컬 편집은 Workspace MCP, Codex 모델은 OCX가 담당한다. |
| Native Codex와 OCX를 모델별로 동시에 고를 수 있나? | Desktop 선택기는 endpoint를 바꾸지 못한다. 기본은 OCX이고 Native는 profile 또는 `ocx restore` 복구 경로다. |
| Web ChatGPT로 로컬 편집하려면 MCP가 필요한가? | 그렇다. Web ChatGPT가 등록 로컬 파일을 읽고 쓰는 경로가 Workspace MCP다. Codex Desktop 자체 편집에는 필요 없다. |
| MCP는 읽기 전용인가? | 아니다. lease 안에서 패치와 샌드박스 명령 실행을 지원한다. |
| 외부에서도 내 Mac을 제어할 수 있나? | ChatGPT의 AICC Workspace 앱을 통해 등록 워크스페이스만 가능하다. AICC 대시보드는 외부 공개하지 않는다. |
| 브라우저를 켜야 하나? | Workspace MCP에는 필요 없다. Mac, 로그인 세션, Tunnel과 인터넷은 필요하다. |
| Web GPT가 Browser/Chrome/Computer Use를 쓸 수 있나? | AICC MCP가 이 호스트 UI 기능을 터널링하지는 않는다. ChatGPT의 네이티브 Computer Use/Chrome 기능은 해당 ChatGPT 계정과 표면에서 별도로 사용한다. 위임된 standalone Codex 작업에서는 세 기능이 모두 unavailable임을 smoke로 확인했다. |
| Web GPT가 로컬 스킬을 쓸 수 있나? | AICC 정본 스킬은 직접 읽을 수 있다. Codex 작업으로 위임하면 그 작업이 `$CODEX_HOME`의 지침·스킬·MCP를 자기 하네스 규칙에 따라 로드한다. 숨은 시스템 지침이나 호스트 전용 도구 정의를 ChatGPT 대화에 통째로 복제하지 않는다. |
| Web GPT가 터미널·프로그램을 실행할 수 있나? | 선택 워크스페이스 안에서 허용된 샌드박스 명령은 가능하다. Mac 전체 제어는 불가능하다. |
| 웹 검색·크롤링·PDF 생성이 가능한가? | ChatGPT 자체 웹 기능과 선택 워크스페이스의 코드·명령으로 수행할 수 있다. MCP 자체가 브라우저 자동화나 PDF 전용 도구를 제공하는 것은 아니다. |
| Codex Desktop task를 Web GPT가 생성·조회·관리할 수 있나? | 소스에는 목록·읽기·생성·후속 요청·보관 도구가 구현되어 있고 실제 OCX 경유 작업 완료를 검증했다. 현재 Business 앱에는 관리자 재게시 뒤 반영된다. |
| Codex 하위 에이전트를 Web GPT가 만들 수 있나? | Web GPT 자체의 복제본을 여는 기능은 아니다. 위임된 Codex 작업은 Codex의 subagent 기능을 요청할 수 있지만 비용·지연이 커서 기본 reasoning은 high이고 자동 병렬화는 사용하지 않는다. ChatGPT Work의 자체 subagent는 별도 호스팅 기능이다. |
| `AGENTS.md`가 Web GPT에 매번 전달되나? | 아니다. Codex는 자기 task에서 가까운 지침을 로드한다. Web ChatGPT는 필요한 파일을 MCP로 읽거나 제한된 컨텍스트 패킷으로 받아야 한다. |
| Web GPT 연결 task가 Codex 압축을 지원하나? | 전용 모델 브리지 task는 없다. 위임된 Codex 작업은 Codex의 네이티브 압축을 사용하고 ChatGPT 대화는 ChatGPT가 별도로 관리한다. |
| 임시/저장과 낮음~매우 높음을 Codex 모델창에서 조합하나? | 아니다. 중복 커스텀 모델을 제거했다. ChatGPT Web 화면에서 대화 모드와 effort를 선택한다. |
| Tunnel API key가 모델 API 과금을 발생시키나? | Workspace MCP는 OpenAI 모델 API를 호출하지 않는다. Tunnel 인증과 ChatGPT 모델 사용은 구분되며, ChatGPT 사용은 해당 워크스페이스 요금제 정책을 따른다. |
| `Waishnav/devspace`를 채택했나? | 런타임 의존성으로 채택하지 않았다. 범용 워크스페이스 제어 아이디어만 참고하고 AICC 소유의 경계형 MCP로 구현했다. |
| 에이전트 홈을 AICC로 옮겼나? | 아니다. AICC `guidance/`가 정본이고 Codex·Claude의 네이티브 홈에는 생성본만 배포한다. 인증과 task DB는 각 홈에 남긴다. |
| 자동 업데이트는 버튼 한 번인가? | 아니다. 인증·라우팅·보안 변경을 무검증 자동 덮어쓰기하지 않는다. Git 변경 확인, 테스트, 배포, CI 순서로 갱신한다. |

## 브라우저 경계

- 기본 웹 링크는 CDP Whale 9335로 연다.
- 일반 Web GPT는 계정·워크스페이스가 맞는 Codex 내장 Browser가 기본이다.
- 로그인 프로필이 필요한 자동화는 등록 CDP Chrome 9222/9223에서 task-owned target을
  짧게 lease한다.
- ChatGPT Chrome Extension은 private coordination이 지정한 한 프로필에만 둔다.
- 일반 Chrome, 다른 계정, Whale로 조용히 우회하지 않는다.
- 브라우저 프로필 DB, 쿠키, 비밀번호 저장소는 에이전트가 직접 읽지 않는다.

## 재부팅과 장애 경계

macOS 로그인 시 다음 구성요소가 자동 시작된다.

- AICC 대시보드 LaunchAgent
- AICC Workspace Secure Tunnel LaunchAgent
- OCX LaunchAgent

재부팅 뒤 `aicc status`, `aicc workspace status`, `ocx health`로 세 경로를 각각
확인한다. 한 경로의 장애를 다른 계정·provider·브라우저로 숨기지 않는다.

## 공개·개인 버전 경계

- `AICC` public: 재사용 가능한 코드, 문서, 테스트, 예제와 일반화된 `guidance/` 정본.
- `my-AICC` private: public AICC 버전 pin, 이 Mac의 비밀 없는 설치 manifest와 개인
  overlay. 다른 컴퓨터에서는 bootstrap으로 public 소스를 설치하고 계정은 다시
  로그인하거나 운영체제 비밀 저장소에서 주입한다.
- `auth.json`, 계정 DB, 세션 JSONL/SQLite, Tunnel key, API key, 쿠키, 브라우저
  프로필, 키체인은 private Git에도 올리지 않는다. private 저장소는 접근 통제일 뿐
  비밀 저장소가 아니기 때문이다.
- 절대 경로는 `${HOME}` 또는 설치 시 선택한 root로 치환하며, 개인 계정 alias는
  private overlay에서만 관리한다.

## 참고 upstream의 현재 지위

| 프로젝트 | 현재 지위 |
|---|---|
| OpenCodex(OCX) | Codex Desktop의 선택 provider 라우터. 고정 submodule과 로컬 패키지를 명시적으로 업데이트한다. |
| `codex-chatgpt-web` | 과거 DOM 모델 브리지의 참고 원본. 런타임·업데이트 대상에서 폐기했다. |
| CodexPro | 현재 AICC 런타임에서 사용하지 않으며 복구 대상도 아니다. |
| `Waishnav/devspace` | 워크스페이스 제어 아이디어만 비교 검토했고 의존성으로 채택하지 않았다. |

따라서 유지보수는 public AICC, OCX 고정 버전, 공식 Codex/ChatGPT MCP 문서를 각각
독립적으로 갱신한다. 폐기된 브리지의 새 릴리스를 AICC에 자동 병합하지 않는다.

## 업데이트와 문서 변경

- AICC 코드·문서·스킬·agent 정의의 정본은 이 저장소다.
- 지침·스킬은 `guidance/`를 수정하고 `aicc guidance deploy`, `check`를 거친다.
- Codex agent는 `guidance/agents/codex/`를 수정하고 `aicc agents deploy`, `check`를
  거친다.
- 생성된 `~/.codex/skills`, `~/.codex/agents`, Claude home은 직접 수정하지 않는다.
- 업데이트는 작은 범위 검토, 로컬 테스트, public 안전성 검사, public/private Git
  push, 다중 플랫폼 CI 순서로 진행한다.

구형 모델 브리지, 별도 Web GPT 앱, 과거 에이전트 스택, 폐기 provider·port·스킬은
복구 대상으로 취급하지 않는다. 새 코드나 문서에서 다시 참조하지 않는다.
