---
name: manage-codex-model-routes
description: "Safely inspect, update, switch, or recover this Mac's two Codex model paths: native Codex and the OpenCodex (OCX) proxy on 10100. Use for provider, catalog, port, route, OCX upgrade, startup repair, or disconnect recovery. Preserve active Codex tasks and non-target providers. Not for ordinary model use, quota-only reports, Web ChatGPT local editing, or general MCP servers."
---

# Codex 모델 경로 안전 관리

모델 경로는 두 개뿐이다. Web ChatGPT의 로컬 편집은 모델 provider가 아니라 별도
`AICC Workspace MCP`가 담당하므로 이 스킬에서 제3의 endpoint, provider 또는 모델
카탈로그를 만들거나 복구하지 않는다.

## 경로 계약

| 경로 | endpoint | 소유자 | 역할 |
|---|---|---|---|
| Native Codex | 공식 Codex endpoint | Codex | OCX 장애 시 독립 복구 경로 |
| OCX | `http://127.0.0.1:10100/v1` | OpenCodex | 기본 Desktop 경로와 provider 라우팅 |

기본 Codex Desktop은 OCX 10100을 사용한다. 무접두어 OpenAI 모델도 기본 Desktop에서는
OCX의 `openai` provider를 통과하므로 OCX 프로세스에 의존한다. 진짜 Native는
`codex-native.config.toml`을 사용하는 CLI profile 또는 Desktop 전체 복구로만 사용한다.
모델 목록에 가짜 Native 항목을 삽입하지 않는다.

## 활성 작업 보호

1. 가장 가까운 저장소 지시와 Git 상태를 확인한다.
2. 비밀을 가리고 다음을 확인한다.
   - 현재 Codex `openai_base_url`, model catalog와 profile
   - `ocx status`, `ocx health`, `ocx system status --json`의 활성 turn 수
   - 10100 `/healthz`, provider 목록과 선택 provider
3. 설정, catalog와 서비스 상태를 소유자 전용 복구 폴더에 백업한다.
4. 현재 작업이 10100을 사용하거나 OCX 활성 turn 수가 0보다 크면 `ocx stop`, `restart`,
   `restore`, `restore back`, `sync --restart-codex`, 서비스 재설치를 실행하지 않는다.
5. provider나 custom model만 바꾸는 경우 OCX의 live 관리 CLI/API를 우선하고, 비대상
   provider와 default provider가 그대로인지 검증한다.
6. 변경 뒤 10100 health, 현재 provider, catalog 정합성과 작은 read-only 요청을 확인한다.
   필요한 재시작은 활성 turn이 0이 된 뒤에만 수행한다.

## Native 복구

OCX 장애 시 Desktop 전체를 Native로 돌리는 표준 명령은 `ocx restore`다. 실행 중인
Codex task에서는 직접 실행하지 말고 사용자가 안전한 새 시점에 수행하도록 안내한다.
설정 복구 뒤에는 Desktop을 완전히 종료하고 다시 열어야 기존 프로세스가 들고 있던
설정이 사라진다.

OCX로 돌아갈 때는 먼저 10100 health를 확인하고 `ocx restore back`을 실행한 뒤 Desktop을
다시 연다. `restore`와 `restore back` 모두 현재 대화를 끊을 수 있으므로 에이전트가 활성
task 안에서 자동 실행하지 않는다.

## 독립 profile

Codex profile은 `$CODEX_HOME/<name>.config.toml` 레이어다.

- `codex-native.config.toml`: 공식 endpoint와 Native 모델
- 기본 `config.toml`: 10100과 OCX catalog

profile을 변경하기 전에 설치된 Codex help/schema를 확인하고 `codex debug models -p
codex-native` 또는 작은 read-only smoke로 실제 덮어쓰기를 검증한다. 현재 Codex Desktop의
모델 선택기는 모델별 endpoint 전환기가 아니므로 Native가 선택 항목으로 보인다고 주장하지
않는다.

## AICC Workspace MCP와의 경계

ChatGPT Business에서 로컬 파일·명령·AICC 스킬을 사용하는 경로는 다음과 같다.

```text
ChatGPT Web -> OpenAI Secure MCP Tunnel -> AICC Workspace MCP -> 등록 워크스페이스
```

이 경로는 OCX 10100과 독립적이다. Tunnel이나 Workspace MCP를 관리할 때 OCX 설정과
catalog를 바꾸지 않는다. 반대로 OCX를 관리할 때 Tunnel profile, runtime key, ChatGPT
connector를 바꾸지 않는다.

## 실패와 롤백

- health 실패를 다른 provider, 계정 또는 profile로 조용히 우회하지 않는다.
- 변경한 한 경로만 백업에서 복원하고 비대상 provider는 그대로 둔다.
- provider 제거 전에 해당 provider의 활성 요청이 없는지 확인한다.
- 활성 task가 있는 상태에서 재시작만 남으면 중단 이유와 안전한 다음 시점을 보고한다.
