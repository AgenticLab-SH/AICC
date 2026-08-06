# 외부 오픈소스 업데이트 절차

## OCX

1. 현재 `vendor/opencodex.UPSTREAM.md`와 submodule 커밋을 확인한다.
2. 새 공식 태그를 임시 폴더에 얕게 가져온다.
3. 라이선스, 의존성, 명령, 관리 API, 설정 형식의 변경을 비교한다.
4. AICC의 OCX 연결 테스트와 OCX 자체 검증 명령을 실행한다.
5. 계정 정보가 없는 격리 환경에서 시작, 상태, 모델 조회, 중지와 기본 GPT
   복구를 확인한다.
6. 실제 사용자 환경 적용 전에는 현재 vendor 폴더와 실행 버전으로 돌아갈 수
   있는 복구점을 만든다.
7. 검증된 경우에만 submodule 포인터와 `opencodex.UPSTREAM.md`를 함께 갱신한다.

외부 원본을 갱신하는 작업은 설치된 실행본이나 `~/.opencodex` 설정을 자동으로
바꾸지 않는다. 실행본 전환은 별도 승인과 실제 smoke를 거친다.

## OpenAI tunnel-client와 MCP SDK

1. 현재 private runtime binary의 버전과 SHA-256을 기록한다.
2. 공식 release와 SDK 변경 내역에서 profile, runtime key, STDIO transport와 도구
   schema 호환성을 확인한다.
3. 격리된 임시 profile에서 Workspace MCP tool list, healthz와 readyz를 검증한다.
4. launchd 원본은 유지한 채 새 binary로 bounded restart를 수행한다.
5. 실제 ChatGPT connector 호출을 확인한 뒤에만 이전 binary를 제거한다.
