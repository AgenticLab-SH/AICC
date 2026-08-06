---
name: use-aicc-openai-api
description: Safely decide, estimate, integrate, test, and monitor OpenAI API calls for a local project through AICC without distributing the API key. Use when a Codex-owned project needs LLM generation, extraction, classification, summarization, embeddings alternatives, an OpenAI model call, token budgeting, API capacity checks, or project-level cost and quota control.
---

# AICC 프로젝트 API 연결

프로젝트에 API key를 복사하지 않고 AICC를 로컬 gateway로 사용한다. AICC가 무료 대상
모델, 전역 95% 하드 정지, 프로젝트 일일 예산, Keychain과 사용량 원장을 소유한다.

## 판단

1. 결정적 코드, 기존 로컬 모델, 브라우저 내 처리로 요구를 충족할 수 있으면 API를
   추가하지 않는다.
2. API가 필요하면 전송할 데이터의 권리·민감도와 failure fallback을 먼저 정한다.
3. 기본 모델은 `gpt-5.4-mini`로 시작한다. 고성능 풀은 품질 차이를 실제 fixture로
   증명한 경우에만 사용한다.
4. 정적 프런트엔드에는 API key나 AICC localhost endpoint를 넣지 않는다. 로컬 backend,
   CLI 도구 또는 desktop companion만 AICC subprocess를 호출한다.
5. 공개 서버에서 호출해야 하면 AICC 로컬 키를 재사용하지 않는다. 별도 server secret,
   인증, rate limit, 비용 상한과 배포 승인을 먼저 설계한다.

## 연결 절차

프로젝트 Git 루트에서 실행한다. AICC는 Git remote의 비밀 없는 hash로 프로젝트를
자동 식별하므로 프로젝트를 옮겨도 같은 remote면 같은 원장을 쓴다.

```bash
aicc openai project status --json
printf '실제 입력' | aicc openai estimate \
  --model gpt-5.4-mini --max-output 512 --json
```

`estimate`가 허용한 뒤에만 실제 호출한다.

```bash
printf '실제 입력' | aicc openai ask \
  --model gpt-5.4-mini --max-output 512 --json
```

프로그램에서는 shell 문자열을 조립하지 말고 argument 배열과 stdin pipe를 사용한다.
subprocess `cwd`를 프로젝트 루트로 고정하고 JSON의 `ok`, `text`, `usage`, `project`를
검증한다. timeout, non-zero exit, 빈 응답과 한도 차단에는 deterministic fallback을 둔다.

## 예산

기본 프로젝트 한도는 두 전역 하드 한도의 10%다. 한도가 부족해도 조용히 다른 프로젝트
이름, API key, provider 또는 유료 모델로 우회하지 않는다. fixture 사용량과 예상 호출
빈도를 근거로 필요한 범위만 조정한다.

```bash
aicc openai project set \
  --frontier-limit 40000 \
  --efficient-limit 400000
```

Git remote가 없는 일회성 작업만 `--project 안전한-별칭`을 쓴다. 같은 작업을 여러 별칭으로
쪼개 한도를 우회하지 않는다.

## 데이터와 비밀 경계

- 이 무료 경로는 API 입력·출력 공유 인센티브다. 기밀, 개인정보, 건강정보, 아동 데이터,
  인증·세션, 권리 없는 원문을 보내지 않는다.
- `OPENAI_API_KEY`, Keychain 값, 프롬프트와 응답을 Git·로그·usage 원장에 저장하지 않는다.
- 입력은 command argument가 아니라 stdin으로 보낸다.
- AICC 대시보드는 AICC guard를 지난 호출만 센다. 다른 앱과 Playground의 사용량까지
  통제한다고 주장하지 않는다.

## 완료 검증

1. 대표 fixture로 `estimate`를 실행한다.
2. 민감하지 않은 최소 fixture 한 건을 실제 호출한다.
3. 결과 schema와 fallback을 자동 테스트한다.
4. `aicc openai project status --json`과 `aicc openai usage --json`에서 프로젝트·전역
   token이 함께 증가했는지 확인한다.
5. 저장소와 빌드 결과를 secret scanner로 확인한다.
6. 어떤 기능이 API에 의존하고 한도 초과 시 어떻게 동작하는지 프로젝트 문서에 남긴다.
