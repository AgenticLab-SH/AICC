# CDP 브라우저 슬롯 이식 설치 (macOS / Windows)

등록된 CDP 슬롯(Chrome 9222, Chrome 9223, Whale 9335)을 새 Mac 또는 Windows
장치에서 재구성하는 절차다. 이 저장소 체크아웃만으로 런처·아이콘·포트 배지
확장이 모두 갖춰진다. 브라우저 프로필과 로그인 세션은 포함되지 않으며, 장치별로
새로 생성하거나 별도 승인된 세션 이전 절차를 따른다.

## 전제

- 정식 서명된 벤더 브라우저가 설치되어 있어야 한다.
  - Chrome 슬롯: macOS `/Applications/Google Chrome.app`,
    Windows `C:\Program Files\Google\Chrome\Application\chrome.exe`
  - Whale 슬롯: NAVER Whale 정식 설치본
- PowerShell 7 이상과 Node.js가 필요하다. 배지 설치기는 Node의 내장 WebSocket을
  사용한다.
- Chrome for Testing은 사용하지 않는다.

## 1. 저장소 체크아웃

```bash
git clone https://github.com/AgenticLab-SH/ai-control-center.git
```

체크아웃 루트를 이후 단계에서 `<aicc>`로 표기한다. 설치 위치는 자유지만 개인
프로필과 설정은 항상 `~/.ai-control-center`에 둔다.

## 2. 슬롯 프로필 루트 확인

프로필은 반드시 기본 브라우저 사용자 루트가 아닌 전용 non-default 루트를 쓴다.
Chrome 136 이후 기본 사용자 루트에 대한 원격 디버깅은 차단된다.

| 슬롯 | macOS | Windows |
| --- | --- | --- |
| Chrome 9222 | `~/.ai-control-center/browser-profiles/chrome/9222/UserData` | `%USERPROFILE%\.ai-control-center\browser-profiles\chrome\9222\UserData` |
| Chrome 9223 | `~/.ai-control-center/browser-profiles/chrome/9223/UserData` | `%USERPROFILE%\.ai-control-center\browser-profiles\chrome\9223\UserData` |
| Whale 9335 | `~/.ai-control-center/browser-profiles/whale/9335/UserData` | `%USERPROFILE%\.ai-control-center\browser-profiles\whale\9335\UserData` |

Chrome 슬롯의 프로필 디렉터리 이름은 `Default`, Whale은 `Profile 1`이다.

## 3. 런처 설치

macOS:

```bash
pwsh -NoProfile -File "<aicc>/tools/platform/web-automation/Install-SeparatedBrowserAppsOnMac.ps1" -Replace
pwsh -NoProfile -File "<aicc>/tools/platform/web-automation/Install-ImportedBrowserAppsOnMac.ps1" -CdpWhaleOnly
```

`~/Applications` 아래에 `CDP Chrome 9222.app`, `CDP Chrome 9223.app`,
`CDP Whale.app`이 생성된다. 세 앱 모두 벤더 엔진을 복제하거나
재서명하지 않는 경량 상주 런처이며, 포트·프로필·실행 경로가 모두 일치할 때만
기존 창을 활성화한다. Dock 등록이 필요하면 `-RegisterDock`을 추가한다.

macOS에서는 인증과 Keychain 접근을 보존하기 위해 CDP Whale 창도 원본
`/Applications/Whale.app` 엔진이 소유한다. 따라서 NAVER Whale 타일에도 창 실행
표시가 보일 수 있지만, `CDP Whale.app` 타일은 실행 중 계속 남아 `35` 상태 배지를
표시하고 클릭하면 검증된 9335 프로필 창만 활성화한다. Dock 그룹을 강제로 나누려고
Whale 앱 전체를 복제하거나 재서명하면 로그인 저장소와 업데이트 경계가 달라질 수
있으므로 허용하지 않는다.

Windows:

```powershell
pwsh -NoProfile -File "<aicc>\tools\platform\web-automation\Install-SeparatedBrowserAppsOnWindows.ps1"
```

`%USERPROFILE%\.ai-control-center\browser-launchers`에 슬롯별 실행 파일을 빌드하고,
`시작 메뉴 > AI Control Center`에 아이콘이 연결된
바로가기를 만든다. 바로가기를 만들지 않으려면 `-NoShortcuts`, 특정 슬롯만
처리하려면 `-OnlyPorts @('9222')`를 쓴다. 기존
`start_shared_chrome.ps1` / `start_shared_whale.ps1`도 그대로 사용할 수 있다.

### 아이콘 자산

아이콘은 저장소에 포함되어 있어 새 장치에서 따로 만들 필요가 없다.

| 용도 | 파일 |
| --- | --- |
| macOS 9222/9223 번들 아이콘 소스 | `tools/platform/app-icons/cdp_chrome_9222.png`, `cdp_chrome_9223.png` (1024px) |
| Windows 9222/9223 런처 아이콘 | `tools/platform/app-icons/cdp_chrome_9222.ico`, `cdp_chrome_9223.ico` (16~256px 6종) |
| Whale 9335 아이콘 | `tools/platform/app-icons/cdp_whale.ico`, `cdp_whale_cdp.ico` |

PNG 원본을 바꿨을 때만 macOS에서 `.ico`를 다시 생성하고 결과를 커밋한다.

```bash
pwsh -NoProfile -File "<aicc>/tools/platform/app-icons/Build-CdpSlotIcons.ps1"
```

## 4. 포트 배지 확장 설치

현재 Chrome은 `--load-extension` 실행 스위치를 제거했다. 배지는 슬롯이 열린 뒤
DevTools 프로토콜로 설치한다.

확장 소스는 `tools/platform/web-automation/extensions/aicc-cdp-port-badge`이고,
압축 해제 확장 ID는 그 절대경로에서 파생된다. AICC를 다른 경로에 두면 ID도 바뀌므로
ID를 고정값으로 가정하지 말고 설치기 출력의 `extension_id`를 근거로 삼는다.

```bash
pwsh -NoProfile -Command "& '<aicc>/tools/platform/web-automation/Install-CdpPortBadgeExtension.ps1' -OnlySlots @('9222','9223','9335')"
```

수동 설치가 필요하면 압축 파일이나 `manifest.json` 하나를 업로드하지 않는다.
`chrome://extensions`에서 개발자 모드를 켜고 **압축해제된 확장 프로그램 로드**를
누른 다음 아래 폴더 자체를 선택한다.

```text
<aicc>/tools/platform/web-automation/extensions/aicc-cdp-port-badge
```

설치 후 툴바의 배지 팝업에서 해당 슬롯을 한 번 선택한다. 다만 등록된 macOS
9222/9223 런처는 브라우저가 시작될 때 같은 폴더를 자동으로 로드하고 슬롯 값을
설정하므로, 정상 상태에서는 수동 설치가 필요하지 않다.

슬롯이 실행 중이어야 하며, 각 슬롯을 하나씩 처리하는 것이 안전하다. 설치기는
포트 소유 프로세스와 프로필 일치를 먼저 검증하고, 확장이 `storage` 권한만
사용하는지 확인한 뒤 배지 텍스트(`22`/`23`/`35`)까지 검증한다. 반복 실행해도
중복 설치되지 않는다. Whale이 `Extensions.loadUnpacked`를 제공하지 않는 버전이면
`badge_status=unsupported`를 보고한다. 이때도 포트·프로세스·프로필 검증은 필수다.

### 재시작 시 자동 복구

`Extensions.loadUnpacked`로 붙인 확장은 프로필에 기록되지 않는다. 따라서 브라우저
프로세스가 종료되면 배지도 함께 사라지고, 새 프로세스마다 다시 설치해야 한다.

Chrome 9222/9223 런처는 이를 자동으로 처리한다.

- 설치 여부를 브라우저 PID 기준으로 기록한다. 런처가 계속 살아 있어도 브라우저가
  교체되면 다시 설치한다.
- macOS 런처는 상태 폴링에서 새 PID를 감지하면 즉시 재설치한다. 사용자가 런처를
  다시 클릭할 필요가 없다.
- Windows 런처는 슬롯을 띄운 뒤 디버깅 포트가 응답할 때까지 기다렸다가 같은 Node
  설치기를 호출한다. AICC 위치가 기본값과 다르면 `AICC_ROOT`를 지정한다.

설치 실패는 슬롯 사용을 막지 않는다. 브라우저 창은 그대로 쓸 수 있고 다음 폴링이나
실행에서 재시도한다.

수동으로 확인할 때는 배지 확장 타겟이 살아 있는지 본다.

```bash
curl -s http://127.0.0.1:9223/json/list | rg -o 'chrome-extension://[a-p]{32}/service-worker'
```

## 5. 검증

```bash
pwsh -NoProfile -File "<aicc>/tools/platform/web-automation/Assert-CdpEndpointIdentity.ps1" -ExpectedBrowser chrome -Endpoint http://127.0.0.1:9222 -ExpectedProfileDir "$HOME/.ai-control-center/browser-profiles/chrome/9222/UserData" -AsJson
pwsh -NoProfile -File "<aicc>/tools/platform/test/Test-AiccBrowserPolicy.ps1" -AsJson
```

슬롯별로 리스너 PID, 프로세스, 프로필이 모두 일치해야 한다. 불일치 시 다른
브라우저나 프로필로 대체하지 않고 실패로 처리한다.

## 포함되지 않는 것

- 브라우저 프로필, 쿠키, 로그인 세션, 인증 자료
- 사용자별 `~/.ai-control-center/guidance/coordination.toml` 값.
- Windows DPAPI로 암호화된 가져온 프로필. 보존 자료로만 취급하며 live 경로로
  다시 연결하지 않는다.
