# AICC 구조

```text
                         +-> Native Codex (복구)
Codex Desktop -> OCX 10100 -> OpenAI/Kiro 등 provider

ChatGPT Web -> Secure MCP Tunnel -> AICC Workspace MCP (STDIO)
                                   -> 별칭으로 등록된 Git workspace
```

두 경로는 독립된 장애 영역이다. Workspace MCP는 OCX provider나 Codex catalog를
수정하지 않고, OCX는 Tunnel profile과 ChatGPT connector를 수정하지 않는다.

Workspace MCP는 고정 도구만 게시한다. 파일과 명령은 `workspace_id + lease`로
하나의 등록 workspace에 묶이고, 경로·심볼릭 링크·민감 파일을 검사한다. 명령은
macOS seatbelt에서 실행하며 home의 다른 경로를 읽지 못하고 선택 workspace와
private runtime 경로에만 쓸 수 있다. 브라우저와 Computer Use는 이 MCP에 넣지 않고
Codex 네이티브 도구와 별도 lease 정책으로 관리한다.

정본은 AICC 저장소다. 인증, runtime key, Tunnel profile, workspace registry와
launchd plist는 `~/.ai-control-center` 및 사용자 LaunchAgents에 둔다.
