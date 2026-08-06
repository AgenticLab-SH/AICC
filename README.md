# AI Control Center

AI Control Center(AICC)는 GPT 계정, Codex/OCX 모델 경로, ChatGPT의 로컬
워크스페이스 연결, 브라우저 세션과 공용 에이전트 지침을 한 로컬 화면과 명령으로
관리합니다. 소스는 공유할 수 있지만 인증, 계정, 브라우저 프로필과 개인 경로는
각 Mac의 소유자 전용 상태에만 둡니다.

## 최종 구조

```text
Codex Desktop -> Web GPT bridge 17841 -> ChatGPT Web (Web 모델 추론)
                 |                         |
                 |                         \-> Web GPT 작업 하네스 전용 Tunnel
                 |                             -> 현재 Codex 작업의 도구 하네스
                 \-> OCX 10100 (Web 외 모델 전달)

Native Codex profile -> OpenAI 공식 Codex 경로 (복구·독립 사용)

외부 ChatGPT -> AICC 원격 작업공간 전용 Tunnel -> AICC 원격 작업공간 MCP
                                             -> 등록 Git 워크스페이스
```

Codex Desktop에서는 `Web / 임시|저장 / 낮음~매우 높음` 모델을 선택해 ChatGPT
Web을 추론 백엔드로 쓸 수 있습니다. Web 모델의 추론은 OCX나 로컬 Codex 모델
토큰을 사용하지 않습니다. 브라우저 전용 모드는 문맥·이미지만 전달하고, 별도 MCP
설정을 마친 전체 하네스 모드에서만 현재 Codex 작업의 파일·터미널·승인·도구를
사용합니다. 이 전용 Tunnel은 외부 ChatGPT용 `AICC 원격 작업공간 MCP` Tunnel과 다른
런타임입니다. 두 경로를 한 Tunnel ID로 재사용하지 않습니다. 외부 ChatGPT에서
로컬을 편집하는 별도 경로는 `AICC 원격 작업공간 MCP`가 담당하며 Codex 작업을
생성하거나 OCX를 호출하지 않습니다.

현재 검증 상태, 일상 사용법과 기존 질문의 최종 답은
[현재 운영 상태와 사용법](docs/current-state-and-usage.md)에 정리되어 있습니다.

Workspace MCP는 별도 HTTP 포트나 공개 reverse proxy를 열지 않습니다. 공식
Tunnel이 고정 STDIO 서버를 실행하며, 임의 절대 경로 대신 AICC에 등록된
워크스페이스 별칭만 받습니다. 파일·명령은 선택 워크스페이스 안으로 제한되고,
명령은 macOS `sandbox-exec`에서 실행됩니다.

## 설치

필수 조건은 Git, Node.js 20 이상, Python 3.11 이상입니다. macOS의 Workspace
MCP에는 PowerShell 7, `rg`, `sandbox-exec`가 필요합니다.

```bash
git clone --recurse-submodules https://github.com/AgenticLab-SH/AICC.git
cd AICC
./install.sh
aicc setup
aicc open
```

Windows에서는 `./install.ps1`을 사용합니다. 전역 링크가 필요 없으면 `--no-link`
옵션을 사용하고 `./bin/aicc`로 실행합니다.

## 주요 명령

```bash
aicc                         # 검색 가능한 터미널 메뉴
aicc open                    # 로컬 관리 웹앱
aicc status --json           # 전체 상태
aicc account                 # GPT 계정 관리
aicc account ocx list --json # OCX 계정 풀
aicc cli status              # Codex/Claude/OCX 확인
aicc agents status           # Codex 하위 에이전트 정합성
aicc agents plan             # 에이전트 배포 미리보기
aicc agents deploy           # AICC 정본 배포
aicc workspace configure     # 모든 Git 워크스페이스 별칭 등록
aicc workspace status        # STDIO 서버와 Secure Tunnel 상태
aicc web-gpt status --json   # Web 모델·전체 하네스·전용 Tunnel 상태
aicc web-gpt doctor --json   # Codex Web GPT 자체 진단
aicc web-gpt open-connectors # ChatGPT 커넥터 설정 열기
aicc guidance check          # 지침·스킬 정합성
aicc action list             # 확인 가능한 변경 작업
aicc openai usage            # 로컬 무료 토큰 guard 원장
aicc openai provider         # API 전체 상태·기본 모델·허용 정책
aicc openai models           # 공식 무료 모델·가격·실호출 확인 상태
aicc openai project status   # 현재 Git 프로젝트 예산과 사용량
aicc openai monitor status   # 60초 감시·선제 정지·공식 화면 관측 상태
aicc openai catalog check    # OpenAI 도움말·개발자 catalog 변경 감지
```

`cm`은 기존 자동화용 `aicc account` 호환 별칭입니다.

변경 작업은 미리보기와 한 번만 유효한 확인 토큰을 사용합니다.

```bash
aicc action preview ocx.sync
aicc action preview account.switch --selector 2
aicc action execute --confirmation '<확인 토큰>'
```

활성 Codex 작업 중에는 `ocx restore`, `ocx restore back`, `ocx stop`, OCX 재시작,
`sync --restart-codex`를 실행하지 않습니다. Native 복구와 OCX 복귀 절차는
`manage-codex-model-routes` 스킬이 담당합니다.

OpenAI API 공유 인센티브를 사용할 때는 프롬프트를 명령행 인자로 남기지 않고 stdin으로
전달합니다. AICC는 현재 계정 화면에서 무료 대상으로 확인된 모델만 허용합니다. 로컬 원장이
80%에서 경고하고 90%에서 provider를 선제 정지하며, 각 UTC 일일 풀의 95%는 독립 하드
차단선으로 남깁니다. 현재 Git 프로젝트는 remote URL의 비밀 없는 hash로 자동 식별하고
기본적으로 각 하드 한도의 10%까지만 사용합니다.

```bash
printf '짧게 답해줘' | aicc openai estimate --max-output 256
printf '짧게 답해줘' | aicc openai ask --max-output 256
```

프로젝트는 API key를 복사하지 않고 로컬 backend에서 `aicc`를 subprocess로 실행합니다.
사용자는 AICC 웹에서 OpenAI API 전체 상태, 모델별 호출 허용, 에이전트 자동 선택 허용과
기본 모델을 관리합니다. 공식 무료 모델 목록과 실제 계정 접근 여부는 분리하며, 개별
“연결 확인”은 비민감 고정 문장으로 최소 요청을 보내 검증합니다.
4381 Dashboard LaunchAgent는 원장을 60초마다 평가하고 공식 catalog를 6시간마다 읽기 전용
검사합니다. Codex agent home에는 API key 환경변수 전달 제외와 직접 `api.openai.com` 호출
차단 hook을 적용할 수 있으며, 사람이나 별도 앱의 의도적 직접 호출까지 통제한다고 주장하지
않습니다.
정적 브라우저 앱은 키나 localhost API를 직접 사용하지 않습니다. 배포 서버에서 호출해야
한다면 별도의 서버 secret·인증·비용 정책을 먼저 설계해야 합니다.

이 원장은 AICC를 통과한 요청만 즉시 집계합니다. 조직 전체의 권위 있는 사용량과 비용은
Admin API key가 필요한 OpenAI Usage/Costs API의 영역이며 반영이 지연될 수 있습니다.
설정·민감정보 경계와 모델별 표시 방식은
[OpenAI 무료 토큰 guard](docs/openai-complimentary-guard.md)를 참고하십시오.

## 상태 위치

- 정본 소스: 이 저장소
- 개인 AICC 상태: `~/.ai-control-center`
- Workspace MCP: `~/.ai-control-center/workspace-mcp`
- Codex 인증·task: `~/.codex`
- OCX 인증·provider: `~/.opencodex`
- 생성된 Codex/Claude 지침: 각 agent home

정본 지침, 스킬과 Codex agent 정의는 `guidance/`에서만 수정합니다. 생성된
`~/.codex/skills`, `~/.codex/agents`를 직접 편집하지 않습니다.

## 포함 구성요소

- Account Manager: `components/account-manager`
- AICC 원격 작업공간 MCP: `components/workspace-mcp`
- Codex Web GPT 모델 브리지: 별도 `codex-chatgpt-web` 저장소와 설치 앱
- OpenCodex(OCX): `vendor/opencodex` 고정 submodule
- 브라우저·런처·운영 도구: `tools/platform`
- 지침·스킬·Codex agents 정본: `guidance`

개인 컴퓨터 간 설치 manifest와 비밀 없는 overlay는 private `my-AICC` 저장소에서
관리합니다. 인증 토큰, 세션 DB, Tunnel key, 쿠키와 브라우저 프로필은 private
Git에도 저장하지 않고 각 컴퓨터에서 다시 로그인하거나 운영체제 비밀 저장소로
주입합니다.

## 검증

```bash
npm run check
npm test
npm run test:workspace-mcp
npm run test:account-manager
npm run test:guidance
npm run test:browser
npm run verify:mac
```

보안 문제는 공개 이슈에 비밀을 쓰지 말고 GitHub private vulnerability reporting으로
제보하십시오.
