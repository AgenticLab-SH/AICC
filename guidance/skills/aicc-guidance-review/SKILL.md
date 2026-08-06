---
name: aicc-guidance-review
description: Review a proposed AICC guidance ecosystem change that would add, remove, merge, rename, broaden, or relocate a skill, AGENTS.md directive, config rule, validator, MCP integration, plugin, hook, automation, or deployment target. Decide source-of-truth placement, trigger collisions, native-feature duplication, deterministic checks, rollout, and rollback. Use only for explicit AICC guidance governance or ecosystem-change review; not for ordinary coding, running an existing skill, routine deployment, browser/account selection, or simple factual lookup.
---

# AICC 지침 변경 검토

AICC guidance의 반복적인 생태계 변경 판단을 감사한다. 모든 에이전트 작업을 대신하는
관리 계층이 아니라, 제안된 변경을 가장 작은 정당한 위치와 범위로 줄이는 명시
호출형 review다.

## 검토 계약

1. 가장 가까운 `AGENTS.md`와 정본 저장소 지시를 먼저 읽는다. 생성된 agent home,
   plugin cache, 인증·세션·계정 DB, 브라우저 프로필을 정본으로 취급하지 않는다.
2. 사용자의 변경안, 현재 diff, active skill inventory, 배포 정책, 관련 validator를
   확보한다. 외부 소스 흡수라면 `references/source-intake.md`와
   `references/absorption-ledger.json`을 함께 확인한다. 기존 사용자 변경과 이번
   변경을 구분한다.
3. 결정 가능한 검사부터 실행한다. 파일·schema·hash·manifest·중복·배포 tree는
   validator의 결과로 판단하고, 의미적 중복이나 유용성은 validator가 증명했다고
   말하지 않는다.
4. `references/placement-rules.md`로 prompt/chat, `AGENTS.md`, config, skill,
   validator/script, MCP, plugin, hook, automation 중 정본 위치를 고른다.
5. 새 skill 또는 description 변경이면 `references/trigger-evals.md`에 따라 positive,
   near-miss negative, 기존 skill과의 충돌 사례를 검토한다. skill 생성·수정에는
   `skill-creator`를 함께 사용한다.
6. 네이티브 기능이나 기존 surface로 충분한지 반대 검토한다. 유지할 이유가
   반복 로컬 지식, 결정적 도구, 외부 protocol, 실제 안전 경계 중 어디에 있는지
   명시하지 못하면 새 skill을 만들지 않는다.
7. 공식 문서의 현재성이 중요한 판단은 공식 원문을 먼저 확인한다. 여러 surface와
   긴 자료를 비교하는 독립 비판이 실질적으로 유용할 때만 `use-web-gpt`를 사용해
   반례·누락·대안을 받는다. Web GPT 결과는 증거가 아니며 로컬 상태와 공식
   원문으로 다시 검증한다.
8. `keep`, `revise`, `merge`, `retire`, `defer` 중 하나를 결정하고 최소 변경,
   검증 gate, rollback을 제시한다. 구현 요청이면 정본만 수정한 뒤 bounded
   Codex/Claude 배포와 재검증까지 수행한다. 정본은 `guidance/skills`와
   `guidance/directives/fragments`이며 생성된 홈은 직접 편집하지 않는다.
9. 외부 소스를 실제로 흡수·보류·거절·대체했다면 같은 변경에서 원장의 판정,
   target, 결합 관계, 우리 쪽 변경, 검증과 다음 확인일을 갱신한다. `UNKNOWN`을
   빈 값이나 확인 완료로 바꾸지 않는다.

## 경계

- 기존 skill 실행, 평범한 코드 수정, 브라우저 선택, 계정 전환, 단순 배포만을 위해
  이 스킬을 사용하지 않는다.
- plugin cache 디렉터리 존재를 설치 증거로 쓰지 않는다. 지원되는 CLI/API의 현재
  installed/enabled 상태를 조회한다.
- MCP는 살아 있는 외부 시스템 연결에, skill은 반복 workflow와 판단에 사용한다.
  plugin은 공유·설치 가능한 배포 단위 또는 skill+connector 묶음이 필요할 때만 쓴다.
- 검사기 안에 바뀌기 쉬운 의미 정책을 계속 하드코딩하지 않는다. 반복 가능한
  기계 규칙만 코드화하고 판단 기준은 짧은 policy/reference에 둔다.
- 검사 통과는 source의 유용성·법적 적합성·최신성을 증명하지 않는다. 중요한
  완료 판정은 같은 명령과 실제 사용자 흐름을 다시 실행할 수 있는 증거를 요구한다.
- 인증·provider·결제·원격 삭제·보안 경계 변경은 `high-risk-change`의 복구·승인
  계약도 적용한다.

## 결과 형식

다음을 간결하게 남긴다.

- **판정**: keep/revise/merge/retire/defer와 핵심 이유
- **근거**: 로컬 파일·현재 CLI/API·공식 원문, 확인 시각
- **배치**: 선택 surface와 거절한 대안
- **충돌**: 기존 trigger/workflow와 positive·negative 평가 결과
- **변경**: 최소 파일과 정본 경로
- **검증**: 실행한 gate, 실패·미확인 항목, 배포 전후 tree 일치
- **롤백**: 복구점과 되돌릴 정확한 범위

실행하지 않은 플랫폼·배포·브라우저 결과를 완료로 보고하지 않는다.
