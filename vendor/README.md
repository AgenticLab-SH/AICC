# 가져온 오픈소스

이 폴더에는 AI Control Center가 사용하는 외부 오픈소스 원본을 출처와 버전을
고정해 연결한다. OCX는 공식 저장소의 특정 커밋을 가리키는 Git submodule이고,
원본 기록은 `opencodex.UPSTREAM.md`에 둔다.

원본 코드는 가능한 한 직접 수정하지 않는다. AICC 전용 연결과 동작 변경은
`src/adapters` 또는 향후 `integrations`에서 구현한다.
