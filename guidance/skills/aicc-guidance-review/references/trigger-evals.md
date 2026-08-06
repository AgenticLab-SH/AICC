# Skill trigger 평가

새 skill과 description 변경은 최소 다음 사례를 기록한다.

## Positive

- 사용자가 skill 이름을 명시한 경우
- description의 핵심 사용자 목표를 자연어로 요청한 경우
- 구체적인 대상 파일·surface가 달라도 같은 반복 workflow가 필요한 경우

## Near-miss negative

- 키워드는 겹치지만 다른 기존 skill이 정확히 소유하는 요청
- 네이티브 기능 또는 일반 코드 작업으로 충분한 요청
- 단순 조회·일회성 질문·routine deploy처럼 workflow 판단이 필요 없는 요청
- 위험 단어가 있지만 실제 고위험 변경은 아닌 요청

## 충돌 검토

1. active AICC guidance, system, installed plugin skill의 name과 description을 현재 상태에서
   수집한다. cache만 있는 plugin은 제외한다.
2. 후보 description의 각 동사를 기존 description과 비교한다.
3. 겹치는 요청마다 어느 skill이 선택되어야 하는지 한 문장 경계를 쓴다.
4. 두 skill이 동시에 필요하면 순서와 handoff를 명시한다.
5. false positive가 넓은 governance skill은 처음에
   `policy.allow_implicit_invocation: false`를 사용한다.

## `aicc-guidance-review` 예시

Positive:

- "두 브라우저 스킬을 합쳐야 하는지 AICC 지침 변경 검토를 해줘."
- "이 규칙을 AGENTS, config, validator 중 어디에 둘지 감사해줘."
- "새 skill description이 기존 plugin skill과 충돌하는지 검토해줘."

Negative:

- "이 Python 버그를 고쳐줘."
- "어느 브라우저 계정을 사용할지 골라줘."
- "현재 active skill을 그대로 배포해줘."
- "OpenAI 문서에서 업로드 제한만 찾아줘."
- "Web GPT에 이 파일을 보내 검토해줘."
