# Windows-Mac 운영 정책

## 경계

- 소스와 문서는 Git 이력으로 교환한다.
- 장치명, SSH 별칭, 사용자 홈과 프로젝트 목록은
  `~/.ai-control-center/cross-device`의 개인 설정에만 둔다.
- 인증, 세션 DB, 브라우저 프로필, 개인키와 실행 기록은 Git에 넣지 않는다.
- 어느 장치의 dirty 작업도 최신이라고 추측하지 않는다.

## 안전 규칙

1. 양쪽 저장소 상태와 SSH 대상을 읽기 전용으로 확인한다.
2. Git은 fast-forward만 자동 허용하고 merge, reset, clean, force push를 하지 않는다.
3. 파일 복사는 항상 Plan 결과를 검토한 다음 Sync한다.
4. 실행 중 변하는 인증·DB·브라우저 자료는 관련 프로그램을 종료하거나 일관된
   스냅샷을 만든다.
5. 충돌 교체는 사용자가 방향을 정했을 때만 원본을 보존한 뒤 수행한다.
6. Windows 전용 기능은 실제 Windows 장비에서 확인하기 전까지 완료로 기록하지 않는다.

실행 명령은 [cross-device-sync.md](../runbooks/cross-device-sync.md)를 따른다.
