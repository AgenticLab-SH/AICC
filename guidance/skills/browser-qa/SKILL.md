---
name: browser-qa
description: Test a deployed site or local page with the current host's native Browser or Chrome capability and capture interaction, responsive-layout, console, network, and screenshot evidence. Use for browser verification after implementation; also use choose-browser-session when signed-in or existing browser state is required. Not for choosing accounts, editing site code, installing another browser harness, or running Web GPT jobs.
---

# 브라우저 QA

현재 호스트가 제공하는 네이티브 브라우저 기능으로 실제 동작을 확인한다. QA는
관찰과 증거 수집을 담당하며 코드 수정은 저장소 작업으로 처리한다.

## 실행 환경

1. 로그인이 필요 없으면 현재 호스트의 격리된 Browser 기능을 사용한다.
2. 기존 로그인·계정·워크스페이스·프로필이 필요하면 먼저
   `choose-browser-session`으로 세션을 선택하고 반환된 task-owned target만 쓴다.
3. API, connector, CLI가 같은 사실을 더 직접 검증하면 브라우저 UI보다 우선한다.
4. QA만을 위해 별도 브라우저 하네스, CDP 서버, 확장 또는 플러그인을 설치하지 않는다.

Codex에서는 내장 Browser를 기본으로 하고 기존 Chrome 상태가 필요할 때만 Chrome
기능을 사용한다. Claude에서는 Browser를 기본으로 하고 기존 사용자 로그인이 꼭
필요할 때만 Claude in Chrome을 사용한다. 현재 호스트에 없는 기능명이나 계정을
추측하지 않는다.

## 관찰 → 조작 → 재관찰

1. URL, 화면 구조, 로딩 상태를 먼저 관찰한다.
2. 클릭·입력·스크롤·폼 제출은 최소 동작으로 실행한다.
3. 이동·리로드·제출 뒤에는 화면 구조를 다시 읽고 이전 ref를 재사용하지 않는다.
4. 데스크톱과 모바일 크기에서 overflow, 잘림, hit target, 키보드 접근을 확인한다.
5. 로그인 QA에서는 선택 스킬의 identity, heartbeat, target, release 계약을 유지한다.

고정 좌표, 탭 위치, 긴 CSS selector, 사용자의 기존 활성 탭에 의존하지 않는다.

## 증거 수집

가능한 범위에서 다음을 남긴다.

- 재현 URL과 실행한 상호작용 순서
- 데스크톱·모바일의 최종 스크린샷
- 관련 console 오류와 실패한 network 요청
- 기대 결과와 실제 결과

호스트가 console 또는 network 관찰을 제공하지 않으면 설치로 우회하지 말고 그
항목을 미확인으로 표시한다. 완료 후 QA가 만든 탭·target만 닫거나 release하고
사용자 탭은 그대로 둔다.

## 웹 AI UI와 구분

웹 AI 조사·사고 작업은 `use-web-gpt`가 담당한다. 웹 AI UI 자동화 실패를 일반
사이트 QA 실패와 같은 원인으로 단정하지 않는다.
