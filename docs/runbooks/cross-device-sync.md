# Windows-Mac 동기화

AICC는 실행 코드를 공개 저장소에 두고 장치명, SSH 별칭, 프로젝트 경로와 실행
기록은 `~/.ai-control-center/cross-device`에 둔다.

## 개인 설정

- `repositories.json`: `dev_root`, 원격 이름, 관리할 저장소 목록
- `sync.json`: Mac/Windows SSH 별칭과 동기화 프로필
- `ledgers/`: 장치별 Git 및 파일 동기화 기록

예시는 개인 홈이나 장치명을 저장소에 고정하지 않는다. 두 JSON 파일은 설치 시
사용자가 직접 만들거나 자신의 에이전트가 현재 장치 상태를 확인해 생성한다.

## Git 상태와 동기화

```powershell
pwsh -NoProfile -File <aicc>/tools/platform/git/Manage-CrossDeviceGit.ps1 `
  -Action Status -Repository <repository>

pwsh -NoProfile -File <aicc>/tools/platform/git/Manage-AllCrossDeviceGit.ps1 `
  -Action Status
```

도구는 자동 stage, merge, reset 또는 clean을 하지 않는다. 양쪽 이력이 갈라졌거나
incoming 파일과 dirty 경로가 겹치면 중단한다. `Commit`은 사용자가 미리 stage한
파일만 처리한다.

## 파일 Plan과 Sync

```powershell
pwsh -NoProfile -File <aicc>/tools/platform/sync/Sync-CrossDeviceFilesOverSsh.ps1 `
  -Action Plan -Direction WindowsToMac `
  -WindowsPath 'C:\absolute\source' -MacPath '/absolute/destination'
```

출력의 장치, 방향, 원본과 대상을 확인한 뒤 같은 인수로 `-Action Sync`를 사용한다.
기본 `ConflictMode=Stop`과 no-delete를 유지한다. 사용자가 어느 쪽을 정본으로 쓸지
명시한 충돌만 `PreserveAndReplace`로 처리하며 대상 원본을 먼저 보존한다.

GUI가 필요하면 다음을 실행한다.

```powershell
pwsh -NoProfile -File <aicc>/tools/platform/sync/cross-device-sync-gui/Open-CrossDeviceSyncGui.ps1 -ScanNow
```

GUI도 `sync.json`을 읽고 성공한 Plan 뒤에만 Sync를 허용한다.

## Codex 세션 JSONL

`Sync-CodexSessionsOverSsh.ps1`은 Windows에서 실행하는 과거 JSONL 전용 도구다.
인증, SQLite, history, logs와 cache는 복사하지 않으며 Codex home 전체 백업을
뜻하지 않는다. 같은 Codex home을 두 장치가 동시에 쓰게 하지 않는다.

## 중단 조건

- 원격, 브랜치, SSH 정체성 또는 대상 경로를 검증하지 못함
- 양쪽 Git 이력이 갈라짐
- incoming 경로와 로컬 dirty 경로가 겹침
- 실행 중인 DB·인증·프로필의 일관된 복사본을 만들 수 없음
- 원본 inventory가 Plan 또는 사후 검증에서 누락됨

이 경우 다른 장치, 계정, 경로나 원격으로 조용히 바꾸지 않는다.
