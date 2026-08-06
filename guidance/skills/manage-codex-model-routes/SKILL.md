---
name: manage-codex-model-routes
description: "Safely inspect, install, switch, or recover this Mac's three Codex model paths: native Codex, the AICC Codex Web GPT bridge on 17841, and OpenCodex (OCX) on 10100. Use for provider, catalog, port, Web GPT model picker, OCX upgrade, startup repair, or disconnect recovery. Preserve active Codex tasks and non-target routes. Not for ordinary model use, quota-only reports, AICC Workspace publishing, or general MCP servers."
---

# Codex 모델 경로 안전 관리

## 경로 계약

| 경로 | endpoint | 추론 소유자 | 역할 |
|---|---|---|---|
| Native Codex | 공식 Codex endpoint | OpenAI Codex | OCX·Web GPT와 독립된 복구 profile |
| Codex Web GPT | `http://127.0.0.1:17841/v1` | ChatGPT Web | `chatgpt-web/*` 모델과 현재 Codex 도구 하네스 |
| OCX | `http://127.0.0.1:10100/v1` | 선택한 OCX provider | Web GPT가 아닌 Desktop 모델의 upstream |

Codex 프로세스 하나는 `openai_base_url` 하나만 사용한다. 통합 모델 선택기가 필요할 때
Desktop의 앞단은 17841이고, 브리지는 요청 모델을 기준으로 다음처럼 분기한다.

```text
chatgpt-web/* -> ChatGPT Web 브라우저 추론
그 밖의 모델 -> OCX 10100으로 원문 전달
codex-native profile -> 공식 Codex endpoint 직결
```

Web GPT 요청은 OCX 모델 추론을 호출하지 않는다. OCX가 중지돼도 Web GPT 분기는 계속
동작해야 한다. 다만 17841 자체가 중지되면 그 endpoint를 사용하는 Desktop 요청 전체가
실패하므로 로그인 자동 실행과 런처 supervisor를 유지한다.

## 활성 작업 보호

1. 현재 Codex `openai_base_url`, route journal, Web GPT config, OCX catalog를 비밀 없이 확인한다.
2. 17841 `/healthz`의 `active_http_turns`, `active_browser_turns`와 10100 health·활성 turn을 확인한다.
3. 설정과 catalog를 소유자 전용 복구 폴더에 백업한다.
4. 활성 turn이 있는 경로는 stop, restart, restore, route 교체 또는 서비스 재설치를 하지 않는다.
5. Web GPT만 변경할 때 OCX 프로세스·provider·계정을 바꾸지 않는다. OCX만 변경할 때 Web GPT
   로그인·Tunnel·브라우저 profile을 바꾸지 않는다.
6. 변경 뒤 두 loopback health, 모델 catalog 병합, route journal과 작은 read-only 요청을 확인한다.

## Web GPT 모델 계약

- 표시 이름은 `Web / 임시|저장 / 낮음|중간|높음|매우 높음`을 사용한다.
- Pro 권한이 검증된 경우에만 `Web / 임시|저장 / Pro`를 추가한다.
- 매우 높음은 Pro 전용이 아니다.
- 임시·저장과 추론 수준은 하나의 모델 slug에 함께 고정한다.
- `full` 모드에서는 현재 Codex turn이 광고한 Browser·Chrome·Computer Use·MCP·터미널 도구를
  outer Codex 도구 gateway로 호출한다. 추론은 계속 ChatGPT Web만 담당한다.
- Web GPT는 현재 Codex 작업의 검증된 workspace 경계를 넘지 못하게 축소한다.

## Native 복구

Native는 `codex-native.config.toml` profile로 항상 보존한다. 먼저 설치된 Codex help/schema와
작은 read-only smoke로 profile을 검증한다. Desktop 모델 선택기는 endpoint 전환기가 아니므로
Native를 가짜 모델 항목으로 주입하지 않는다.

Desktop 전체를 OCX 경유에서 Native로 복구하는 `ocx restore`, 돌아가는 `ocx restore back`,
`ocx sync --restart-codex`는 현재 대화를 끊을 수 있다. 활성 작업 안에서 자동 실행하지 말고
안전한 재시작 시점에만 사용한다.

## AICC Workspace와의 경계

외부 ChatGPT에서 등록 프로젝트를 직접 다루는 경로는 모델 provider가 아니다.

```text
ChatGPT Web -> Secure MCP Tunnel -> AICC Workspace -> 등록 워크스페이스
```

이 경로의 게시·Tunnel·도구 snapshot을 바꿀 때 17841 또는 10100 모델 route를 바꾸지 않는다.
반대로 모델 route를 관리할 때 AICC Workspace 앱 게시 상태를 바꾸지 않는다.

## 실패와 롤백

- 실패를 다른 provider·계정·profile로 조용히 우회하지 않는다.
- 변경한 경로만 journal 또는 백업에서 복원한다.
- 브리지와 OCX를 동시에 재시작하지 않는다.
- 활성 작업 때문에 재시작만 남으면 정확한 남은 단계와 안전한 실행 시점을 보고한다.
