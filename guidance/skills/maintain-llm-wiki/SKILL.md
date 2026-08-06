---
name: maintain-llm-wiki
description: Build, explain, capture into, review, refresh, or reorganize a local Markdown/Obsidian LLM Wiki from a project folder, repository, URL, or user note. Use when the user asks to 위키화, 옵시디언에 기록, 지식 볼트에 추가, 프로젝트 문서화, 초안 승격, 출처 갱신, or make an LLM Wiki easier for Korean users.
---

# LLM Wiki 관리

Markdown 볼트를 사람이 읽기 쉽고 에이전트가 갱신하기 안전한 지식 정본으로 유지한다.
기본 언어는 한국어다. Obsidian은 선택형 뷰어이고 파일 형식은 일반 Markdown이다.

## 볼트 선택

1. 사용자가 볼트 경로를 지정했으면 그 경로만 사용한다.
2. 현재 프로젝트 안에서 `.obsidian`과 `00_Meta/00_Vault_Home.md`가 함께 있는 볼트를 찾는다.
3. 없으면 AICC에 등록된 workspace나 기존 로컬 지식 볼트를 읽기 전용으로 찾는다.
4. 후보가 둘 이상이면 조용히 합치지 않는다. 변경 전 선택 근거를 알린다.

가장 가까운 `Vault_Conventions`, `Update_Workflow`, 템플릿과 검사 스크립트를 먼저
읽는다. 새 구조를 만들기 전에 기존 MOC와 `_inbox`를 재사용한다.

## 요청별 동작

- **빠른 메모**: 적합한 도메인의 `_inbox/`에 사용자의 문장을 보존하고, 추정으로
  사실을 보충하지 않는다. 사용자가 직접 쓴 메모는 LLM 생성 초안으로 위장하지 않는다.
- **프로젝트 위키화**: README·설계·운영 문서·주요 코드 경계를 inventory하고
  비밀·개인 데이터·인증·세션·캐시·빌드 결과를 제외한다. 출처 URL 또는 Git revision을
  기록하고 생성물은 검토 전 영역에서 시작한다.
- **URL·외부 자료 흡수**: source URL, 확인일, revision/hash, 권리 상태를 먼저
  기록한다. 원문을 대량 복제하지 않고 사실·추론·적용 제안을 분리한다.
- **검토·승격**: 원문과 대조한 채택 내용만 `knowledge/` 또는 `playbooks/`로 다시
  작성한다. pending 초안의 이름만 바꿔 정식 지식으로 만들지 않는다.
- **갱신·재조사**: 구조 변경, 사실 갱신, 재조사, 범위 확장, 보관을 한 커밋에
  섞지 않는다. 변경된 주장과 출처만 갱신한다.
- **설명**: 경로, 저장 방식, Obsidian에서 여는 법, Git 백업 여부와 자동화 여부를
  실제 상태로 답한다. daemon이나 자동 감시가 없으면 스스로 동작한다고 말하지 않는다.

## 프로젝트 위키화 출력

다음 최소 결과를 만든다.

1. 프로젝트 한 줄 정의와 범위
2. 시스템 지도와 핵심 진입점
3. 실행·검증·배포 playbook
4. 중요한 결정과 이유
5. 데이터·비밀·권리 경계
6. 출처와 revision
7. UNKNOWN과 다음 검토일

사용자가 기존 악보·문서·노트를 주면 이를 사실의 자동 정답으로 취급하지 않고
보정 힌트 또는 출처로 연결한다.

## 안전과 완료

- 대량 변경 전 Git 상태와 복구점을 확인한다. 관련 없는 dirty 변경을 보존한다.
- 절대경로, API key, 토큰, 계정 DB, 브라우저 profile, 원문 개인자료를 커밋하지 않는다.
- 수동 Markdown은 허용한다. 적합한 `_inbox/`에 새 파일을 만들고 YAML과 링크를
  최소로 채운 뒤, 나중에 Codex에게 “이 메모 정리해줘”라고 요청할 수 있다.
- 마지막에 볼트 검사기를 실행하고 유령 링크·메타데이터 문제·due 항목을 보고한다.
- GitHub push는 사용자가 요청한 경우에만 private 원격과 포함 파일을 확인해 수행한다.

## 바로 쓸 프롬프트

- `이 프로젝트 폴더를 한국어 LLM 위키로 만들어줘. 비밀과 빌드 결과는 제외하고 출처와 커밋을 남겨.`
- `이 내용을 빠른 메모로 보관하고, 어느 도메인에 넣었는지 알려줘.`
- `pending 초안을 원문과 대조해서 채택할 것만 정식 지식으로 승격해줘.`
- `재조사 기한이 지난 노트만 공식 출처로 갱신해줘.`
