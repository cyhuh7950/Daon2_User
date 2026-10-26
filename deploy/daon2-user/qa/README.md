# WSL QA 계정·로그인 E2E (daon2_user 스택)

비밀번호는 출력하지 않고 서버 파일(`~/deploy/daon2-user/secrets/qa_e2e_password`, mode 600)에만 둔다.

1. `seed_qa_account.py` — api 컨테이너 안에서 실행. 서버 콘솔 방식으로 `AdminUserService.create_user`를 호출해 QA 계정(`qa-e2e`)을 만든다. 초기 비밀번호는 컨테이너 `/tmp`에 쓰고 서버 secrets로 복사한 뒤 컨테이너에서 지운다.
2. `approve_qa_account.py` — 같은 방식으로 관리자 승인(`pending_approval` → `active`).
3. `e2e_login.py` — 서버 호스트에서 `127.0.0.1:3340`의 BFF를 호출: 로그인 → 강제 비밀번호 변경(Origin·Referer 필요) → 재로그인 → 세션·Notebook 목록·페이지 확인. 상태 코드와 키 이름만 출력한다.

초기 관리자(`admin`)는 API 시작 시 자동 생성되며 건드리지 않는다.
