## Codex 전용

- 활성 `$CODEX_HOME`의 설정과 설치된 help/schema를 기준으로 하며 provider·인증은 승인 없이 바꾸지 않는다. 다중 계정 홈은 인증·DB와 렌더링된 `config.toml`을 분리하고 나머지 선언된 자산만 App home과 공유한다.
- 일반 웹 UI와 Web GPT는 로그인·워크스페이스가 맞으면 Codex Desktop 내장 Browser를 백그라운드 기본값으로 사용한다. 개인 계정·워크스페이스·CDP slot은 `~/.ai-control-center/guidance/coordination.toml`에서 확인하고 추측하지 않는다. 내장 Browser에 필요한 로그인이 없거나 재사용할 Chrome 프로필이 중요할 때만 등록 CDP Chrome의 task-owned target을 임대하며, 조작 직후 반환한다. 기존 사용자 브라우저는 명시 요청 또는 신뢰 가능한 독점 유휴 신호가 있을 때만 사용한다. 반환된 target만 조작하고 탭 활성화나 조용한 계정 전환을 하지 않는다. Web GPT는 보통 높음(high), 복잡한 작업은 매우 높음(xhigh)을 사용하며 사용자의 명시 동의 전에는 Pro를 선택·제출하지 않는다.
- Sites는 사용자가 명시하거나 소스 루트의 `.openai/hosting.json`과 현재 provider가 일치할 때만 사용한다. `dist`·`build` 안의 manifest는 선택 근거로 보지 않는다.
