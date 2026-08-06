# Mac 기준 Windows 맞추기

`00-career`처럼 Git에 모두 넣기 어려운 개인·대용량 파일을 Mac 기준으로 Windows의 같은 상대경로에 반영하는 로컬 웹 GUI다. 외부 서버가 아니라 각 장치의 `127.0.0.1`에서만 열린다.

## 안전 모델

- Mac 파일의 상대경로를 그대로 Windows `00-career` 루트 아래에 적용한다.
- Mac에만 있는 파일은 Windows의 같은 위치에 생성한다.
- 양쪽 내용이 다르면 Windows 원본을 `.cross-device-conflicts/<timestamp>/`에 보존한 뒤 Mac판을 반영한다.
- Windows에만 있는 파일은 삭제하지 않고 Mac으로 가져오지도 않는다.
- 수정시각만으로 동일하다고 가정하지 않고 Plan에서 체크섬을 비교한다.
- 읽기 전용 Plan이 성공해야 실제 `Sync` 버튼이 활성화된다.
- 다른 파일을 삭제하거나 자동 병합하지 않는다.
- 지정 루트의 `.git`, 숨김 파일, 런타임, 캐시, 모델, DB, 브라우저 프로필, 자동 백업, 임시 폴더를 이름이나 종류 때문에 제외하지 않는다.
- 실행 중 파일이나 읽기 오류를 조용히 건너뛰지 않으며, 완전한 inventory를 만들 수 없으면 동기화를 실패 처리한다.

## 실행

macOS:

```bash
pwsh -NoProfile -File <aicc>/tools/platform/sync/cross-device-sync-gui/Open-CrossDeviceSyncGui.ps1 -ScanNow
```

Windows PowerShell 7:

```powershell
pwsh -NoProfile -File "<aicc>\tools\platform\sync\cross-device-sync-gui\Open-CrossDeviceSyncGui.ps1" -ScanNow
```

양쪽 모두 `~/.ai-control-center/cross-device/sync.json`을 읽는다. SSH 별칭과 개인
경로는 공개 소스가 아니라 이 파일에서 관리한다.

## 화면 흐름

1. 양쪽 파일 검사
2. `안전 Plan 실행`
3. 실행 기록 검토
4. `검토한 Plan대로 Windows 맞추기`

동기화 엔진은 `../Sync-CrossDeviceFilesOverSsh.ps1`, 기록은
`~/.ai-control-center/cross-device/ledgers/`를 사용한다.

기존 파일별 양방향 Tk 화면 코드는 `cross_device_sync_gui.py`에 남아 있지만 기본 실행에서는 사용하지 않는다. 기본 진입점은 `cross_device_sync_web.py`다.
