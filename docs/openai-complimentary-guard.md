# OpenAI 무료 토큰 guard

## 무엇을 해결하나

OpenAI의 API 입력·출력 공유 인센티브를 켠 프로젝트에서 AICC를 통과한 요청만 로컬로
즉시 세고, 현재 공식 화면에 표시된 두 일일 풀의 95%에서 새 요청을 차단한다. 무료 대상이
아닌 모델은 기본 차단한다.

| UTC 일일 풀 | 공식 한도 | AICC 하드 한도 |
| --- | ---: | ---: |
| 고성능 모델 | 250,000 token | 237,500 token |
| 경량 모델 | 2,500,000 token | 2,375,000 token |

한도와 대상 모델은 2026-08-06 Personal 조직의 공식 설정 화면과
[OpenAI 도움말](https://help.openai.com/en/articles/10306912-sharing-feedback-evals-and-api-data-with-openai)을
기준으로 확인했다. 정책이 바뀌면 코드와 이 문서를 함께 갱신해야 한다.

## 사용법

API key는 macOS Keychain의 `OpenAI API` / `personal-default` 항목에서 읽고 화면·원장·로그에
쓰지 않는다. 입력은 shell history와 process list에 남지 않도록 stdin으로 보낸다.

```bash
aicc openai usage
aicc openai usage --json
cd /path/to/git-project
aicc openai project status
printf '요약해줘' | aicc openai estimate --model gpt-5.4-mini --max-output 512
printf '요약해줘' | aicc openai ask --model gpt-5.4-mini --max-output 512
```

원장은 `~/.ai-control-center/openai-usage/usage.json`에 사용자 전용 권한으로 저장한다.
프롬프트, 응답, API key는 저장하지 않고 모델별 요청 수와 input/cached/output token만
저장한다. UTC 00:00에 새 일자로 자동 전환한다.

## 로컬 프로젝트 예산

OpenAI의 `Default project`와 로컬 Git 프로젝트는 다른 개념이다. OpenAI key는 계속
하나의 Default project에 속하지만, AICC는 호출한 작업 디렉터리의 Git remote를 hash해
로컬 프로젝트별로 사용량을 나눈다. URL, 절대경로와 remote 본문은 원장에 저장하지 않는다.

프로젝트 기본 한도는 전역 95% 하드 한도의 10%다.

| 풀 | 프로젝트 기본 일일 한도 |
| --- | ---: |
| 고성능 | 23,750 token |
| 경량 | 237,500 token |

필요성이 검증된 프로젝트만 전역 하드 한도 안에서 조정한다.

```bash
aicc openai project set \
  --frontier-limit 40000 \
  --efficient-limit 400000
```

`--project 이름`을 주면 Git remote가 없는 일회성 작업도 안정적인 별칭으로 묶을 수 있다.
프로젝트 정책은 `~/.ai-control-center/openai-usage/projects.json`에 사용자 전용 권한으로
저장한다.

## 프로젝트 연결 계약

- 결정적 로컬 코드로 충분하면 API를 호출하지 않는다.
- 기본 모델은 경량 풀에서 고르고, 호출 전 `estimate`로 입력 상한과 출력 예약량을 확인한다.
- 로컬 Node/Python backend는 `aicc openai ask --json`을 subprocess로 실행하고 stdin으로
  입력한다. 실행 `cwd`를 해당 Git 프로젝트 루트로 둔다.
- `OPENAI_API_KEY`를 프로젝트 `.env`, 브라우저 bundle, Cloudflare Pages 정적 자산,
  로그나 Git에 복사하지 않는다.
- 공개 배포 서버는 사용자의 Mac에 있는 AICC를 호출할 수 없다. 서버 호출이 필요하면
  별도 인증·secret·rate limit·비용 승인 경계를 설계한다.
- AICC 오류나 한도 차단을 정상 실패로 처리하고 deterministic fallback을 둔다.

## 표시를 읽는 법

- 풀 게이지는 같은 무료 한도를 공유하는 모델들의 실제 input+output token 합계다.
- 프로젝트 표는 Git 프로젝트별 실제 사용량과 기본/사용자 한도를 보여준다.
- 모델 행은 해당 모델의 input, cached input, output과 표준 요금 환산 추정치를 나눈다.
- 요금 환산은 비용 청구액이 아니라 절감 규모를 이해하기 위한 날짜가 있는 가격 snapshot이다.
- OpenAI가 한 요청 전체를 무료 한도 초과로 판단할 수 있으므로 AICC는 요청 전 입력의 보수적
  상한과 `max_output_tokens`를 예약하고 5% 여유를 둔다.

## 정확성 경계

로컬 원장은 `aicc openai ask`를 통과한 요청만 포함한다. 다른 프로그램이나 OpenAI
Playground에서 같은 프로젝트/API key를 쓴 사용량은 알 수 없다. 공식 조직 전체 집계에는
별도의 Admin API key로 Usage/Costs API를 읽는 동기화가 필요하며, 그 집계도 실시간이라고
가정하면 안 된다. Admin key는 일반 호출 key보다 권한이 크므로 현재 기본 구성에서는 만들거나
저장하지 않는다.

데이터 공유 동의는 계정 소유자가 약관과 입력 데이터 권리를 직접 확인해 완료해야 한다.
기밀, 개인정보, 건강정보, 아동 데이터, 권리를 보유하지 않은 콘텐츠는 보내지 않는다.
