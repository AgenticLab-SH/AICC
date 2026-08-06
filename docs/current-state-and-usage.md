# 현재 운영 상태와 사용법

이 문서는 AICC의 실제 운영 경계와 사용법을 기록한다. 숫자와 프로세스 상태는
시간이 지나면 달라질 수 있으므로 아래 스냅샷과 실시간 상태를 구분한다. 계정 ID,
Tunnel key, 브라우저 프로필과 인증 자료는 저장소에 기록하지 않는다.

## 2026-08-06 검증 스냅샷

- AICC 대시보드 `127.0.0.1:4381`: 10개 구성요소 모두 ready
- OCX `127.0.0.1:10100`: health 정상, 기존 Codex 작업 유지 중
- AICC 원격 작업공간 MCP: Git 워크스페이스 39개, Secure Tunnel healthy/ready
- Business 앱 `AICC Workspace`: 13개 action으로 새로 고침 완료
- 지침: AICC 정본과 Codex·Claude 배포본 일치, Codex agent는 `luna_worker` 1개
- 브라우저: 기본 HTTP/HTTPS는 CDP Whale 9335, 브라우저 정책 20/20 통과
- Web GPT 앱: v2.0.0-aicc.1, 전용 프로필 로그인·17841 bridge와 Codex 모델 route
  활성화 완료. 2026-08-06에 Pro를 제외한 임시·저장 × 낮음·중간·높음·매우 높음
  8개 조합을 실제 ephemeral Codex turn으로 모두 검증했다. 임시 4개는 병렬 실행에서
  각 25.27~25.38초, 저장 4개는 15.69~28.93초였고 모두 요청한 `정상` 응답으로
  종료했다. 이 측정값은 네트워크와 ChatGPT UI 상태에 따라 달라질 수 있다.

| 대화 방식 | 낮음 | 중간 | 높음 | 매우 높음 |
|---|---:|---:|---:|---:|
| 임시 | 25.28초 | 25.27초 | 25.38초 | 25.38초 |
| 저장 | 28.93초 | 15.69초 | 28.86초 | 25.39초 |

8개 모두 같은 최소 프롬프트와 `정상`만 출력하는 응답 계약을 사용했고 도구는
광고하지 않은 추론 smoke였다. 따라서 이 결과는 Web GPT 추론 경로 8/8 성공의
증거다. 이어서 Full 하네스와 `Web GPT 작업 하네스` ChatGPT 커넥터를 연결한 뒤
격리 프로젝트에서 `Web / 임시 / 높음`으로 실제 파일 패치, 터미널 명령과 테스트를
검증했다. `src/status.js`를 Web 모델이 직접 수정했고 `npm test` 1/1 통과까지
85.08초가 걸렸다. 이 시험에서는 OCX나 네이티브 모델 추론을 사용하지 않았다.
- OpenAI Tunnel은 역할별로 분리한다. `AICC 원격 작업공간 MCP`는 외부 ChatGPT용이고,
  `Web GPT 작업 하네스 MCP`는 Codex Desktop Web 모델의 전체 하네스용이다. 기존 Workspace
  Tunnel을 전체 하네스에 재사용하지 않는다.
- 전체 하네스의 실시간 완료 여부는 스냅샷 문구가 아니라
  `aicc web-gpt status --json`의 `harnessReady`와 `aicc web-gpt doctor --json`으로
  판정한다. 현재 커넥터 이름은 `Web GPT 작업 하네스`이며
  `connectorVerification=verified`까지 확인했다. 새 ChatGPT 세션에서 앱 연결
  확인이 다시 보이면 해당 세션에만 명시적으로 허용한다.

실시간 상태는 다음 명령으로 다시 확인한다.

```bash
aicc status --json
aicc workspace status
aicc guidance check
aicc web-gpt status --json
aicc web-gpt doctor --json
ocx status
ocx health
curl -fsS http://127.0.0.1:17841/healthz
```

## 세 가지 Codex 모델 경로와 외부 Workspace 경로

```text
Codex Desktop -> Web GPT bridge 17841 -> ChatGPT Web (Web 모델 추론)
                 |                         \-> Web GPT 작업 하네스 전용 Tunnel
                 |                             -> 현재 Codex 작업 도구
                 \-> OCX 10100 (Web 외 모델 전달)

Native Codex profile -> OpenAI 공식 Codex endpoint

외부 ChatGPT -> AICC 원격 작업공간 전용 Tunnel -> AICC 원격 작업공간 MCP (STDIO)
                                             -> 등록 Git workspace
```

| 경로 | 역할 | 추론 비용·상태 |
|---|---|---|
| Web GPT 17841 | Codex 모델 선택기에서 ChatGPT Web 사용 | Web 모델 추론은 로그인한 ChatGPT Web만 사용한다. OCX 모델 추론은 호출하지 않는다. 전체 하네스는 별도 Web GPT 작업 하네스 Tunnel을 쓴다. |
| OCX 10100 | OpenAI/Kiro 등 기존 Codex 모델 라우팅 | OCX 계정·provider·quota를 사용한다. |
| Native Codex | 공식 Codex endpoint 복구 경로 | OCX와 Web GPT를 거치지 않는다. |
| AICC 원격 작업공간 | 폰·웹 ChatGPT에서 등록 로컬 프로젝트 편집 | 별도 Tunnel을 쓴다. 모델 API를 호출하지 않는다. ChatGPT가 모델이고 MCP는 로컬 도구 경로다. |

인증과 런타임은 분리하지만 Codex Desktop 설정에는 한 시점에 하나의 전역
`openai_base_url`만 적용된다. Web GPT를 활성화하면 17841이 앞단에서 Web 모델을
처리하고 Web 외 모델을 기존 10100으로 전달한다. 따라서 17841 프로세스가 죽은
상태에서는 같은 Desktop profile의 다른 모델도 연결 실패할 수 있다. 복구 profile은
준비해 두되 활성 작업 중 `ocx restore`, route 교체나 Codex 재시작은 하지 않는다.

## AICC 대시보드

```bash
aicc open
aicc status --json
```

대시보드는 loopback에만 열리며 외부에 공개하지 않는다. 계정, OCX, Native,
Web GPT, Workspace MCP, 브라우저와 지침 상태를 한 화면에서 읽는다. 위험한 변경은
`aicc action preview`의 영향과 복구 방법을 확인한 뒤 일회용 확인 토큰으로 실행한다.
`구조 지도`에서는 네 실행 경로, 두 Tunnel의 역할 차이, 실제 채택한 upstream과
아이디어만 참고한 소스를 분리해 볼 수 있다. `Obsidian Canvas 받기`로 공개 JSON
Canvas 파일을 내려받을 수 있으며 Obsidian 플러그인 설치는 필요 없다.

## Codex Desktop에서 Web GPT 사용

설정과 로그인이 끝나면 모델 선택기에 다음 8개 비-Pro 모델이 나타난다.

- `Web / 임시 / 낮음|중간|높음|매우 높음`
- `Web / 저장 / 낮음|중간|높음|매우 높음`

계정에 Pro가 실제로 노출되고 사용자가 명시 승인한 경우에만 임시·저장 Pro를
추가한다. `매우 높음`은 Pro 전용이 아니다. 브라우저 전용 모드에서도 현재 Codex
대화 문맥과 이미지는 전달되지만 로컬 파일, 터미널과 Codex 도구 호출은 노출되지
않는다. 별도 `Web GPT 작업 하네스` Tunnel과 ChatGPT 커넥터를 구성해 전체 하네스
모드로 전환한 뒤에만
Codex Desktop이 현재 프로젝트, 파일 패치, 터미널, 승인과 도구 호출을 담당하고 모델
추론만 ChatGPT Web에서 수행한다.

현재 v2 전송 방식은 **Codex turn마다 새 ChatGPT 대화**를 열고, 해당 Codex 작업의
누적·압축된 문맥을 다시 전달한다. 저장 모드는 각 turn의 대화가 ChatGPT 기록에
남고 임시 모드는 남지 않는다. 같은 ChatGPT URL을 계속 쓰는 진짜 연속 대화는 아직
구현하지 않았다. 이 방식은 tab 누수와 중단 복구는 단순하지만 장기 작업에서 문맥
재전송 비용이 있다. Codex 네이티브 압축은 지원하며 동시 turn은 최대 5개로 제한한다.

`AGENTS.md`, 시스템·개발자 지침, 이전 대화와 사용자 요청은 Codex가 만든 context
packet 안에서 필요한 범위로 매 turn 전달된다. 숨은 인증 자료나 임의의 agent home
전체를 복사하지 않는다. 압축 뒤에는 Codex가 보존한 요약 문맥이 전달된다.

### 전체 하네스 모드에서 Web 모델이 쓸 수 있는 기능

- 현재 Codex 작업이 광고한 파일·터미널·MCP·skills 도구
- allowlist에 포함된 Web 검색, Browser, Chrome, Computer Use, 이미지 생성과 정확히
  지정된 Codex task 관리 도구
- 프로젝트 경계 안의 코드 실행, 크롤링과 PDF 생성

도구 이름이 allowlist에 있어도 현재 Codex 표면에 실제로 설치·광고되지 않으면 쓸
수 없다. raw Node REPL처럼 프로젝트 경계를 우회할 수 있는 도구는 노출하지 않는다.
Web GPT가 직접 하위 Web GPT를 자동 생성하는 기능은 기본값이 아니며, 느린 다중
에이전트를 자동 실행하지 않는다.

전체 하네스에서 로컬 도구를 실행해도 추론 주체는 ChatGPT Web 하나다. Codex
Desktop은 현재 프로젝트 경계, 도구 스키마, 승인 UI와 실행 결과 전달을 담당할 뿐
별도의 Codex/OCX 모델 응답을 생성하지 않는다. 따라서 Web 모델이 AICC 저장소를
현재 프로젝트로 연 작업에서는 AICC MCP 소스도 읽고 패치하고 테스트할 수 있다.
반대로 다른 프로젝트 작업에서 임의 절대 경로로 AICC에 탈출하는 것은 허용하지
않는다.

## 외부 ChatGPT에서 AICC Workspace 사용

폰이나 다른 컴퓨터의 ChatGPT에서 같은 Business workspace의 `AICC Workspace` 앱을
선택하면 이 Mac의 등록 프로젝트를 다룰 수 있다. 브라우저를 켜 둘 필요는 없지만
Mac이 켜져 있고 로그인 세션, 인터넷, 로컬 MCP와 Secure Tunnel LaunchAgent가
살아 있어야 한다. Mac이 꺼졌거나 네트워크가 끊기면 로컬 도구 호출은 실패한다.

1. `aicc_workspace_list`로 등록 별칭 확인
2. `aicc_workspace_open`으로 한 workspace의 만료 lease 발급
3. 읽기·검색·패치·명령·변경 검토
4. 새 작업이나 lease 만료 뒤 다시 open

현재 action 13개는 다음과 같다.

| 구분 | 도구 |
|---|---|
| 선택·정보 | `aicc_workspace_list`, `aicc_workspace_open`, `aicc_workspace_info` |
| 읽기·검색 | `aicc_workspace_read`, `aicc_workspace_read_many`, `aicc_workspace_search` |
| 쓰기·실행 | `aicc_workspace_apply_patch`, `aicc_workspace_exec`, `aicc_workspace_write_stdin`, `aicc_workspace_process_stop` |
| 검토·지침 | `aicc_workspace_changes`, `aicc_skill_inventory`, `aicc_skill_read` |

이 앱은 Codex task 생성·조회·위임 도구를 제공하지 않는다. 추론은 해당 ChatGPT
대화가 하고, MCP는 등록 workspace 안의 파일·터미널·AICC 정본 스킬만 제공한다.
임의 절대 경로, workspace 탈출, 심볼릭 링크 탈출, 민감 파일과 Git 내부 메타데이터는
차단하고 쓰기·명령에는 lease와 macOS seatbelt sandbox를 적용한다.

네트워크 복구 뒤 Tunnel은 자동 재연결되지만, 끊어질 때 진행 중이던 모델 생성이나
명령이 정확히 중단 지점부터 재개된다고 보장하지는 않는다. 상태를 확인하고 실패한
단계만 다시 실행한다.

## Native Codex와 OCX 복구

Native와 OCX는 모델 이름으로 endpoint를 동시에 고르는 구조가 아니다. 실행 중인
작업이 없는 안전한 시점에 준비된 profile/복구 명령으로 전역 route를 바꾸고 Codex
Desktop을 다시 열어야 한다. 활성 작업 중에는 다음 명령을 자동 실행하지 않는다.

```bash
ocx restore       # Native 복구
ocx restore back  # OCX 복귀 전 10100 health 확인 필요
```

Web GPT setup은 기존 loopback upstream과 catalog를 읽어 10100 OCX route를 자동
보존하도록 구현했다. route 작업은 `manage-codex-model-routes` 스킬을 따른다.

## 브라우저 경계

- 기본 HTTP/HTTPS/HTML handler는 `com.aicc.whale.cdp.9335`다.
- 일반 Chrome·Whale Dock 런처는 각각 비-CDP vendor 창만 전면 활성화한다.
- CDP Chrome 9222/9223과 Whale 9335는 서로 다른 app identity·profile·port를 쓴다.
- 로그인 자동화는 private coordination이 지정한 slot의 task-owned target만 잠시
  임대하고 반환한다.
- ChatGPT Chrome Extension은 private coordination이 지정한 한 profile에만 둔다.
- 브라우저 profile, cookie와 인증 자료는 public/private Git에 넣지 않는다.

## 참고 프로젝트와 유지보수

| 프로젝트 | 판단 |
|---|---|
| OpenCodex(OCX) | 실제 Codex 모델 라우터로 유지 |
| `codex-chatgpt-web` | AICC fork v2를 Web 모델 브리지로 유지 |
| CodexPro | 현재 런타임에서 미사용, 복구 대상 아님 |
| `Waishnav/devspace` | 범용 workspace 아이디어만 참고, 의존성 미채택 |

`devspace`는 현재 설치·실행·서브모듈 의존성이 아니다. workspace 제어 아이디어만
검토했고, 필요한 기능은 AICC 소유의 `components/workspace-mcp`로 다시 구현했다.
`codex-chatgpt-web`과 코드로 융합된 것도 아니다.

따라서 DevSpace release를 자동 반영하거나 보안 업데이트 대상으로 추적하지 않는다.
새 기능을 비교할 제품 조사 때만 선택적으로 다시 검토한다. 실제 업데이트 추적 대상은
실행 코드인 `codex-chatgpt-web`, OpenCodex, `openai/tunnel-client`, MCP SDK다.

AICC `guidance/`가 지침·스킬·agent의 정본이며 Codex·Claude home에는 생성본만
배포한다. 인증, task DB와 런타임 cache는 각 제품의 native home에 둔다. public
`AICC`에는 재사용 가능한 코드·문서·테스트를, private `my-AICC`에는 비밀 없는 장치
manifest와 overlay만 둔다. private Git에도 token, cookie, 계정 DB, Tunnel key와
브라우저 profile은 올리지 않는다.

업데이트는 upstream 확인 → 작은 diff 검토 → 로컬 테스트 → public 안전성 검사 →
의도한 commit/push → 정확한 CI 확인 순서로 한다. 보안·인증·route 변경을 GitHub의
최신 소스로 자동 덮어쓰는 무검증 원클릭 업데이트는 제공하지 않는다.
