# Web GPT 실행 계약

실제 ChatGPT UI 제출, 계정 식별, 공용 pacing 또는 로컬 Workspace MCP가 필요한
경우에만 읽는다. 프롬프트 설계는 `context-and-prompting.md`가 담당한다.

## 계정과 워크스페이스

개인 계정 별칭과 워크스페이스는
`~/.ai-control-center/guidance/coordination.toml`에서 읽는다. 화면의 표시명만으로
계정을 추측하거나 조용히 전환하지 않는다.

기존 대화가 필요하면 해당 계정에 매핑된 정확한 surface만 사용한다.

- 기본은 로그인된 Codex Desktop 내장 Browser다.
- 등록 CDP Chrome이 명시된 경우에만 해당 slot의 task-owned target을 lease한다.
- 확장 설치·활성·연결이 필요한 경로는 지정된 프로필에서 먼저 검증한다.
- 다른 Chrome, Whale, 계정 또는 워크스페이스로 조용히 우회하지 않는다.

## 새 대화와 로컬 작업공간

새 대화는 내장 Browser에서 만든다. Web ChatGPT를 Codex Desktop 모델 provider로
변환하는 DOM/Responses 브리지는 사용하지 않는다.

로컬 프로젝트를 읽거나 수정해야 하면 ChatGPT Business의 `AICC 원격 작업공간 MCP`
앱을 선택한다. 도구는 다음 경로로 실행된다.

```text
ChatGPT Web -> OpenAI Secure MCP Tunnel -> AICC 원격 작업공간 MCP -> 등록 워크스페이스
```

먼저 `aicc_workspace_list`, `aicc_workspace_open`을 사용하고 반환된 lease를 후속
도구에 그대로 전달한다. 임의 절대 경로를 열거나 다른 프로젝트로 경계를 넓히지
않는다. 명령 세션은 Tunnel 또는 Mac 재시작 뒤 복구되지 않으므로 새 명령으로
명시적으로 다시 시작한다.

Browser Use, Chrome 제어와 Computer Use는 Workspace MCP 도구가 아니다. 현재
Codex task가 별도 네이티브 도구로 제공할 때만 AICC 브라우저 lease와 확인 정책에
따라 사용한다. ChatGPT Web이 이 로컬 UI 권한을 자동으로 가진다고 주장하지 않는다.

## 제출 pacing

같은 계정·워크스페이스의 제출은 직렬화하고, 전송 전 현재 응답이 끝났는지
확인한다. 차단이나 rate limit 신호가 있으면 즉시 간격을 늘리고 재시도를 중단한다.
프롬프트·답변·URL·쿠키·토큰을 pacing 기록에 남기지 않는다.

## 내장 Browser 조작

최신 화면 근거와 안정적인 locator를 사용한다. 전송 후 입력창이 비워지고 새 응답
turn이 생겼는지 확인한다. 완료는 streaming 종료와 응답 텍스트 안정성을 함께 본다.
차단·로그인·CAPTCHA는 사람 확인이 필요한 상태로 처리하고 우회하지 않는다.

사용자의 키보드 포커스를 빼앗는 탭 활성화나 전면 Computer Use를 기본값으로
사용하지 않는다. task-owned 탭만 이름 변경·정리한다.

## 장시간 작업

ChatGPT 자체의 저장 대화, Project, 예약/에이전트 기능이 현재 계정에 제공되면 그
네이티브 기능을 사용한다. 로컬 Agent Stack runner나 숨겨진 브라우저 프로필을
다시 만들지 않는다. 네트워크 단절 동안 서버 측 작업이 계속되었다고 로컬에서
확인할 수 없으면 `UNKNOWN`으로 두고, 연결 복구 뒤 같은 대화의 실제 상태를 확인한다.
