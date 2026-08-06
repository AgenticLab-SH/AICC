---
name: high-risk-change
description: Use only before changes where a misunderstood requirement is expensive to undo, such as authentication, authorization, payments, security boundaries, database schema and migrations, deployment and infrastructure, large refactors, or work spanning multiple writers or repositories. Not for ordinary feature work, single-file fixes, tests, formatting, docs, or anything already covered by normal implementation review.
---

# 고위험 변경

되돌리기 비용이 큰 변경에만 짧은 실행 계약을 먼저 만든다. 일반 수정에는 발동하지 않는다.

## 대상

- 인증·인가·결제·보안 경계
- DB 스키마와 마이그레이션
- 배포·인프라 정의
- 대규모 리팩터링
- 여러 writer 또는 여러 저장소가 동시에 바뀌는 작업

## 흐름

1. **의도와 성공 조건**: 무엇이 끝난 상태인지 한두 문장으로 고정한다.
2. **미결정 사항**: 답이 구현 방향을 실제로 바꾸는 것만 질문한다. 나머지는 안전한 가정을 명시하고 진행한다.
3. **실행 계약**: 변경할 대상, 건드리지 않을 대상, 검증 방법, 실패 시 복구 방법을 짧게 적는다.
4. **구현**: 계약 범위 안에서만 변경한다.
5. **증거**: 실행한 테스트, diff, 실제 실행 결과를 제시한다.
6. **규칙 반영**: 앞으로도 유지될 결정만 해당 `AGENTS.md`에 남긴다.

## 복구

광범위한 변경 전에는 복구점을 만든다. 마이그레이션은 롤백 경로와 재실행 안전성을 함께 확인한다. 운영 데이터·비가역 작업은 명시적 승인 범위 안에서만 수행한다.

## 금지

긴 계획서, 단계별 반복 보고서, 매번 같은 체크리스트를 만들지 않는다. 계약은 실행을 좁히기 위한 것이고, 문서를 늘리기 위한 것이 아니다.
