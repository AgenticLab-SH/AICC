# Windows-Mac 왕복 Git 운영 정책

## 목표

Windows와 macOS가 같은 private GitHub 정본을 표준 `origin` 원격으로 사용한다. 공개 저장소와 private 정본을 함께 쓰는 예외 프로젝트만 설정에서 별도 원격을 명시한다.

## 로컬 설정

`Manage-CrossDeviceGit.ps1 -Action Configure`는 다음을 설정한다.

- 기본 push 원격: 프로젝트 설정의 정본 원격(`origin`이 기본값)
- 현재 브랜치 pull/push 원격: 같은 정본 원격
- pull 정책: fast-forward only
- 다른 원격: 자동 변경하지 않음

작업 전에 `-Action Status`를 실행한다. dirty tree, ahead/behind를 먼저 확인하며 자동 merge·reset·clean은 하지 않는다.

## 커밋 분류

직접 `git commit` 대신 staged 변경에 대해 다음 명령을 사용한다.

```powershell
pwsh -NoProfile -File <aicc>/tools/platform/git/Manage-CrossDeviceGit.ps1 `
  -Action Commit -Repository . -Scope portable -Message "설명" -TestedOn both
```

제목 접두사:

- `portable:` Windows와 macOS 공통 변경
- `win:` Windows/x64 전용 변경
- `mac:` macOS/arm64 전용 변경

각 커밋에는 `Source-Device`, `Tested-On`, `Cross-Device-Impact` trailer가 추가된다. 도구는 파일을 자동 stage하지 않으므로 사용자가 검토한 staged 파일만 커밋된다.

## 로컬 변경기록

각 장치는 AICC 개인 상태의 비추적 ledger에 자기 기록만 추가한다.

- `~/.ai-control-center/cross-device/ledgers/git/windows.jsonl`
- `~/.ai-control-center/cross-device/ledgers/git/macos.jsonl`

공유 이력은 Git commit trailer가 정본이다. 장치별 ledger는 진단과 최근 작업 추적용이다.

## 플랫폼 파일 경계

- 공통 코드에는 저장소 상대경로와 홈 기준 설정을 사용한다.
- OS 전용 구현은 가능하면 `platform/windows`, `platform/macos` 또는 명시적인 OS 분기 파일로 분리한다.
- `.venv`, `node_modules`, build/cache, 브라우저 프로필, 인증·세션 자료는 Git에 넣지 않는다.
- Windows COM·증권사 실행부는 Windows 전용으로 유지하고 Mac 성공으로 기록하지 않는다.
