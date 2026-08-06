# 명시적 Web GPT 다중 조사

사용자가 여러 Web GPT, 다중 조사, fan-out 조사를 명시한 경우에만 사용한다. 일반
조사에서 solver 수를 관성적으로 늘리거나 별도 Multi-GPT CLI를 실행하지 않는다.

## 분할

1. 부모가 하나의 decision question과 종료 조건을 고정한다.
2. solver마다 겹치지 않는 질문 또는 source scope를 하나씩 배정한다.
3. 같은 URL과 같은 질문을 여러 대화에 반복 제출하지 않는다.
4. solver는 구현 파일을 쓰지 않는다. 최종 정본 writer는 하나만 둔다.
5. 기본 2~3개 solver로 시작하고, 새 관점이 실제로 필요할 때만 늘린다.

각 대화에는 전체 로컬 맥락이 아니라 공통 header와 자기 질문만 보낸다.

```json
{
  "research_id": "stable-short-id",
  "goal": "최종 결정 한 문장",
  "shared_facts": ["직접 확인한 사실만"],
  "boundaries": ["금지 작업과 범위"],
  "solver": { "id": "s1", "question": "겹치지 않는 질문", "source_scope": ["공식 원문 범위"] },
  "output": ["claim", "evidence", "counterexample", "unknowns", "recommendation"]
}
```

## 회수

응답 전체를 다음 대화에 전달하지 않는다. 각 solver에서 JSONL 한 줄만 회수한다.

```json
{"solver_id":"s1","claim":"","evidence":[{"url":"","as_of":"YYYY-MM-DD","supports":""}],"counterexample":"","unknowns":[],"recommendation":""}
```

부모 또는 단일 merger에는 solver record와 충돌표만 전달한다. merger는 합의 수를
진실로 취급하지 않고 공식 원문, 로컬 증거, 반례를 기준으로 `adopt`, `defer`,
`reject`, `UNKNOWN`을 판정한다.

## 종료

- 모든 필수 질문에 공식 또는 직접 근거가 있다.
- 새 solver가 추가할 독립 관점이 없다.
- 충돌이 남으면 억지 합의 대신 `UNKNOWN`과 다음 검증을 남긴다.
- 응답 제한, 로그인, CAPTCHA, rate limit이 나타나면 우회하거나 다른 계정으로
  조용히 전환하지 않는다.
