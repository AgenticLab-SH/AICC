# 외부 소스 흡수와 유지보수

외부 저장소, 글, 공식 문서, UI 패턴을 참고해 AICC guidance에 반영할 때 한 원장에서
출처와 판정을 유지한다. 링크 보관과 채택은 별개다.

## 상태 흐름

```text
pending -> researching -> absorbed
                    |-> deferred
                    |-> rejected
                    |-> duplicate
                    `-> superseded
```

- `pending`: URL과 목적만 등록했다.
- `researching`: 원문, 공식성, 버전·날짜, 라이선스와 기존 정본 중복을 확인 중이다.
- `absorbed`: 실제 target과 우리 쪽 변경, 결합 대상, 검증이 기록됐다.
- `deferred`: 유용하지만 현재 요구·stack·권리 근거가 부족하다. 재검토 조건을 쓴다.
- `rejected`: 도입하지 않는다. 이유와 다시 볼 조건을 쓴다.
- `duplicate`: 기존 정본이 이미 같은 책임을 더 정확히 소유한다.
- `superseded`: 공식 지원이나 현재 구조가 이전 방식보다 정확하다.

## 기록 계약

`absorption-ledger.json`의 한 record는 경로와 분리된 안정 `id`, 정규 URL, 확인일,
license 증거, 판정, 실제 target, 결합 관계, 우리 고유 요소, 검증, upstream 확인일을
가진다. `UNKNOWN`은 조사했지만 아직 모르는 값이고 `NOT_APPLICABLE`은 적용되지 않는
값이다. 둘을 바꾸어 쓰지 않는다.

코드·문구·asset을 복사한 경우 source ref와 license 의무를 저장소의
`THIRD_PARTY_NOTICES` 또는 `*.UPSTREAM.md`에도 남긴다. 원리만 참고했다면
`kind: pattern`과 `local_elements`로 자체 구현을 구분한다. 중앙 원장은 각 제품의
attribution 정본을 대체하지 않는다.

개인·비공개·인증 URL, API 키, 계정·세션 정보, 사용자 홈 절대 경로는 tracked 원장에
넣지 않는다. 경로가 바뀌어도 작동하도록 target은 AICC root 상대 경로만 쓴다.

## 최신성·공식 지원과 중복

1. 공식 문서와 실제 설치 상태를 먼저 확인한다.
2. 기존 directive, skill, plugin, native capability가 같은 책임을 소유하는지 본다.
3. 공식 지원이 더 정확하면 이전 workaround를 `superseded`로 바꾸고 삭제 후보를 적는다.
4. `upstream_monitor.next_due`가 지나면 원문 ref·license·공식 지원·target 존재를 다시 본다.
5. 네트워크 접근성은 offline validator의 pass 조건으로 삼지 않는다.

GitHub source의 현재 HEAD는 다음 읽기 전용 검사로 비교한다. 이 검사는 원장을
자동 수정하지 않고 `current`, `update_available`, `unavailable`만 보고한다.

```bash
pwsh -NoProfile -File tools/platform/inspect/Inspect-GuidanceUpstreams.ps1 \
  -AiccRoot . -AsJson
```

`update_available`이면 변경 내용을 읽고 실제 흡수 대상과 충돌하는지 검토한 뒤
원장의 ref·판정·검증일을 함께 갱신한다. 네트워크 실패인 `unavailable`은 최신으로
간주하지 않는다.

## 완료 증거

`absorbed`는 문서에 적었다는 뜻이 아니다. 최소한 target 존재, 관련 정적 검사,
필요한 실제 흐름의 재실행 결과가 있어야 한다. stale PASS 파일이나 다른 브랜치의
결과를 현재 증거로 재사용하지 않는다.
