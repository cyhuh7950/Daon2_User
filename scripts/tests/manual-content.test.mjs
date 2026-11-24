import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const privateNetworkEvidence = new URL("docs/03_evidence/release_1/R1-M8-10-WINDOWS-OFFLINE-STUDIO-01/phase-c3-manual/browser-network.jsonl", root);
const privateEvidenceManifest = new URL("docs/03_evidence/release_1/R1-M8-10-WINDOWS-OFFLINE-STUDIO-01/phase-c3-manual/manifest.json", root);
// 2.0.0부터 한 권이다(WO-UM1). 시작 안내·지식 가이드는 은퇴했다.
const docs = [["daon-user-manual", "Daon 사용자 설명서"]];
const retired = ["daon-getting-started", "daon-knowledge-llm-guide"];

test("S33 두 설명서는 게시본의 상세 절차와 최신 Provider 권한·호환 방식·Auto 설명을 함께 보존한다", async (t) => {
  for (const id of ["daon-user-manual"]) await t.test(id, async () => {
    for (const file of [`docs/manual/${id}/index.md`, `apps/web/public/manual/${id}.md`]) {
      const markdown = await readFile(new URL(file, root), "utf8");
      for (const required of [
        /OpenAI 호환.*Chat Completions/su,
        /Anthropic 호환.*Messages/su,
        /Media Bridge.*CUSTOM/su,
        /공용.*관리자 Key/su,
        /비공용.*본인.*개인 Key/su,
        /시스템 Key.*fallback.*없/u,
        /라우터 Auto 사용/u,
        /openrouter\/auto/u,
        /논리 모델/u,
        /기본 모델 저장/u,
        /키 교체.*Endpoint.*worker/su,
        /이관.*환경변수/su,
      ]) assert.match(markdown, required, file);
      assert.doesNotMatch(markdown, /현재 관리자 비밀번호|시스템 범위의 연결별 키 하나를 모든 Workspace가 공유/u);
    }
  });
});

test("S33 사용자 설명서는 조직 정책 잠금과 License의 사용자·Notebook 한도 및 서버 적용 권한을 보존한다", async () => {
  for (const file of ["docs/manual/daon-user-manual/index.md", "apps/web/public/manual/daon-user-manual.md"]) {
    const markdown = await readFile(new URL(file, root), "utf8");
    assert.match(markdown, /Workspace에서는 조직의 외부 전송 정책을 읽기 전용/u);
    assert.match(markdown, /\/settings\/organization/u);
    assert.match(markdown, /ETag/u);
    assert.match(markdown, /사용자 수.*Notebook 수/su);
    assert.match(markdown, /기본값은 사용자 1명, Notebook 1개, LLM 사용 가능/u);
    assert.match(markdown, /can_apply=true/u);
    assert.match(markdown, /Step-up 후 검증·적용/u);
    assert.doesNotMatch(markdown, /라이선스 등록·교체·적용은 시스템 관리자만/u);
  }
});

test("S33 지식 원칙 일곱 줄과 근거 용어 여섯 정의는 부록 B 용어집에 보존한다", async (t) => {
  for (const file of ["docs/manual/daon-user-manual/index.md", "apps/web/public/manual/daon-user-manual.md"]) await t.test(file, async () => {
    const markdown = await readFile(new URL(file, root), "utf8");
    const glossaryStart = markdown.indexOf("### 부록 B 용어집\n");
    assert.ok(glossaryStart >= 0, `${file}: 부록 B 용어집`);
    const rest = markdown.slice(glossaryStart + 1);
    const next = rest.search(/\n#{2,3} /u);
    const bullets = rest.slice(0, next < 0 ? undefined : next).split("\n").filter((line) => line.startsWith("- "));
    assert.deepEqual(bullets.slice(0, 7), [
      "- 질문에 사용할 Source를 사용자가 명시적으로 선택합니다.",
      "- 근거 질문은 Citation을 원문과 함께 검토합니다.",
      "- Provider 연결과 실제 질문 실행 지원을 구분합니다.",
      "- 외부 전송은 조직 정책을 통과한 경우에만 수행합니다.",
      "- 모델과 설정을 자동으로 임의 변경하지 않습니다.",
      "- 미지원 형식이나 기능은 성공을 가장하지 않고 안전하게 중단합니다.",
      "- Version, Run과 산출물의 계보를 보존합니다.",
    ]);
    assert.deepEqual(bullets.slice(7, 13), [
      "- Raw Source: 사용자가 직접 등록한 파일이나 텍스트",
      "- Daon 승인 지식: Daon 2, Daon 2.5, Daon 3에서 생산·등록된 지식 패키지",
      "- 연결형 Source: MCP나 Connector를 통해 참조하는 외부 Source",
      "- Source Version: 특정 시점 Source의 변경 불가능한 Version",
      "- Evidence: 질문 처리에 실제 사용된 근거 조각",
      "- Citation: 답변에서 Evidence 위치를 가리키는 참조",
    ]);
  });
});

// WO-N1 단계 1(NB1-M): 답변 과정 보기·메모를 소스로 쓰기 절이 원본과 공개 사본에 모두 있어야 한다.
test("N1 단계 1 두 절(2-13 답변 과정 보기, 2-14 메모를 소스로 쓰기)은 원본·공개 사본에 필수 내용과 함께 있다", async (t) => {
  for (const file of ["docs/manual/daon-user-manual/index.md", "apps/web/public/manual/daon-user-manual.md"]) await t.test(file, async () => {
    const markdown = await readFile(new URL(file, root), "utf8");
    const section = (heading) => {
      const start = markdown.indexOf(`\n${heading}\n`);
      assert.ok(start >= 0, `${file}: ${heading}`);
      const rest = markdown.slice(start + 1);
      const next = rest.slice(1).search(/\n#{2,3} /u);
      return rest.slice(0, next < 0 ? undefined : next + 1);
    };
    const process = section("### 2-13 답변 과정 보기");
    for (const required of [
      /\*\*답변 과정\*\*/u,
      /\*\*질문 범위\*\*.*\*\*근거 찾기\*\*.*\*\*외부 전송\*\*.*\*\*모델\*\*.*\*\*검증\*\*/su,
      /근거 이름.*누르면.*소스.*열립니다/su,
      /\*\*검증\*\* 단계에 \*\*확인 필요\*\*/u,
      /오류 카드 안에.*\*\*외부 전송\*\* 단계에 \*\*확인 필요\*\*/su,
      /\*\*과정 기록 없음\*\*/u,
      /다시 열어도.*그대로/su,
      /모델의 내부 생각.*프롬프트 원문.*비밀값.*보이지 않습니다/su,
      /images\/2-13-answer-process\.png/u,
      /시험 화면\(하네스\)에서 예시 자료로 촬영/u,
    ]) assert.match(process, required, `2-13 ${required}`);
    const memo = section("### 2-14 메모를 소스로 쓰기");
    for (const required of [
      /\*\*소스로 사용\*\*/u,
      /\*\*메모\*\* 표시가 붙은 소스/u,
      /\*\*소스에 반영\*\*.*새 버전/su,
      /\*\*소스와 같음\*\*/u,
      /\*\*소스가 변경됨\*\*/u,
      /메모를 지워도 소스는.*\*\*원본 메모 없음\*\*/su,
      /32 KiB/u,
      /첫 버전을 아직 처리/u,
      /보기 권한만 있으면.*보이지 않습니다/su,
      /images\/2-14-memo-source\.png/u,
      /images\/2-14-memo-source-list\.png/u,
      /시험 화면\(하네스\)에서 예시 자료로 촬영/u,
    ]) assert.match(memo, required, `2-14 ${required}`);
    assert.match(markdown, /\| 답변이 어떤 자료·판정·모델을 거쳤는지 보기 \| 2-13 \|/u, "부록 C 2-13");
    assert.match(markdown, /\| 메모를 소스로 쓰기, 고친 메모를 소스에 반영 \| 2-14 \|/u, "부록 C 2-14");
  });
});

// WO-N1 단계 2(NB2-M): 질문 도구 켜고 끄기·노트북 개요와 추천 질문 절이 원본과 공개 사본에 모두 있어야 한다.
test("N1 단계 2 두 절(2-15 질문 도구 켜고 끄기, 2-16 노트북 개요와 추천 질문)은 원본·공개 사본에 필수 내용과 함께 있다", async (t) => {
  for (const file of ["docs/manual/daon-user-manual/index.md", "apps/web/public/manual/daon-user-manual.md"]) await t.test(file, async () => {
    const markdown = await readFile(new URL(file, root), "utf8");
    const section = (heading) => {
      const start = markdown.indexOf(`\n${heading}\n`);
      assert.ok(start >= 0, `${file}: ${heading}`);
      const rest = markdown.slice(start + 1);
      const next = rest.slice(1).search(/\n#{2,3} /u);
      return rest.slice(0, next < 0 ? undefined : next + 1);
    };
    const tools = section("### 2-15 질문 도구 켜고 끄기");
    for (const required of [
      /모델 선택 옆 \*\*도구\*\* 버튼/u,
      /숫자 배지.*켜진 도구 수/su,
      /\*\*승인 지식\*\*.*지식 연결/su,
      /즉시 저장/u,
      /노트북별로 기억/u,
      /승인 지식 범위가 선택되지 않았습니다.*연결이 아직 준비되지 않았습니다.*관리자가 끈 연결입니다/su,
      /소스만으로 답합니다/u,
      /서버에 저장된 선택으로 판단.*호출되지 않습니다/su,
      /웹 검색 도구는 없습니다/u,
      /Citation 칩 앞에.*\*\*승인 지식\*\*.*\*\*문서 근거\*\*.*\*\*법령\*\*.*소스 이름/su,
      /\*\*답변 과정\*\*.*\*\*질문 범위\*\*/su,
      /images\/2-15-question-tools\.png/u,
      /시험 화면\(하네스\)에서 예시 자료로 촬영/u,
    ]) assert.match(tools, required, `2-15 ${required}`);
    const overview = section("### 2-16 노트북 개요와 추천 질문");
    for (const required of [
      /준비된 소스가 처음 생기면.*자동으로 만들어집니다/su,
      /요약 한 문단.*인용 칩/su,
      /\*\*추천 질문\*\* 세 개/u,
      /개요를 만드는 중입니다/u,
      /입력 칸에 채워집니다.*자동으로 보내지 않/su,
      /소스가 바뀌었습니다/u,
      /\*\*다시 만들기\*\*.*누를 때만 새로 만들/su,
      /편집할 수 있는 사용자만/u,
      /외부 전송 정책으로 개요를 만들 수 없습니다.*시작 제안/su,
      /\*\*다시 시도\*\*/u,
      /\*\*개요 접기\*\*/u,
      /images\/2-16-notebook-overview\.png/u,
      /images\/2-16-notebook-overview-stale\.png/u,
      /시험 화면\(하네스\)에서 예시 자료로 촬영/u,
    ]) assert.match(overview, required, `2-16 ${required}`);
    assert.match(markdown, /\| 질문할 때 승인 지식·지식 연결 켜고 끄기 \| 2-15 \|/u, "부록 C 2-15");
    assert.match(markdown, /\| 노트북 요약과 추천 질문 보기, 개요 다시 만들기 \| 2-16 \|/u, "부록 C 2-16");
  });
});

// WO-N1 단계 3(NB3-M): 만들기 전에 구성 확인(슬라이드·동영상)·소스 묶음 절이 원본과 공개 사본에 모두 있어야 한다.
test("N1 단계 3 두 절(2-17 만들기 전에 구성 확인, 2-18 소스 묶음)은 원본·공개 사본에 필수 내용과 함께 있다", async (t) => {
  for (const file of ["docs/manual/daon-user-manual/index.md", "apps/web/public/manual/daon-user-manual.md"]) await t.test(file, async () => {
    const markdown = await readFile(new URL(file, root), "utf8");
    const section = (heading) => {
      const start = markdown.indexOf(`\n${heading}\n`);
      assert.ok(start >= 0, `${file}: ${heading}`);
      const rest = markdown.slice(start + 1);
      const next = rest.slice(1).search(/\n#{2,3} /u);
      return rest.slice(0, next < 0 ? undefined : next + 1);
    };
    const outline = section("### 2-17 만들기 전에 구성 확인(슬라이드·동영상)");
    for (const required of [
      /\*\*슬라이드 자료\*\*.*\*\*동영상 개요\*\*/su,
      /\*\*만들기 전에 구성 확인\*\*을 체크/u,
      /\*\*구성 확인 필요\*\*/u,
      /\*\*구성 검토 중\*\*/u,
      /제목과 \*\*요지\*\*/u,
      /\*\*내레이션\*\*.*\*\*글머리\*\*/su,
      /\*\*위로\*\*·\*\*아래로\*\*/u,
      /장 추가 버튼\(동영상은 장면 추가 버튼\)/u,
      /\*\*이대로 만들기\*\*/u,
      /\*\*확정한 구성으로 생성 중…\*\*/u,
      /최대 30/u,
      /최대 20/u,
      /최대 100자/u,
      /확정하기 전에는 음성·영상을 만들지 않습니다/u,
      /\*\*취소\*\*를 누릅니다\. 만들지 않고 목록으로 돌아가며, 카드는 \*\*구성 확인 필요\*\*로 남아/u,
      /카드 ⋮ → \*\*삭제\*\*/u,
      /장면별 근거가 표시되지 않습니다/u,
      /구성 목록이 올바르지 않습니다/u,
      /images\/2-17-outline-settings\.png/u,
      /images\/2-17-outline-cards\.png/u,
      /images\/2-17-outline-review-slides\.png/u,
      /images\/2-17-outline-review-video\.png/u,
      /시험 화면\(하네스\)에서 예시 자료로 촬영/u,
    ]) assert.match(outline, required, `2-17 ${required}`);
    const groups = section("### 2-18 소스 묶음");
    for (const required of [
      /\*\*묶음 만들기\*\*/u,
      /접히고, 다시 누르면 펴집니다/u,
      /모두 켜짐.*일부만 켜짐.*모두 꺼짐/su,
      /\*\*묶음으로 이동\*\*/u,
      /\*\*묶음 밖으로\*\*/u,
      /\*\*이름 바꾸기\*\*.*\*\*묶음 삭제\*\*/su,
      /소스는 \*\*묶음 없음\*\*으로 옮겨질 뿐 그대로 남습니다/u,
      /노트북을 쓰는 사람 모두에게 같게 보입니다/u,
      /하나씩 체크한 것과 똑같/u,
      /최대 8개/u,
      /앞의 8개를 사용합니다/u,
      /보기 권한이면 \*\*묶음 만들기\*\*, 묶음 ⋮, \*\*묶음으로 이동\*\* 버튼이 보이지 않습니다/u,
      /노트북당 최대 50개/u,
      /images\/2-18-source-groups\.png/u,
      /images\/2-18-source-groups-move\.png/u,
      /images\/2-18-source-groups-menu\.png/u,
      /시험 화면\(하네스\)에서 예시 자료로 촬영/u,
    ]) assert.match(groups, required, `2-18 ${required}`);
    assert.match(markdown, /\| 슬라이드·동영상 만들기 전에 장·장면 목록 고치기 \| 2-17 \|/u, "부록 C 2-17");
    assert.match(markdown, /\| 소스를 묶음으로 정리, 묶음째 체크 \| 2-18 \|/u, "부록 C 2-18");
  });
});

test("한국어 Manual 정본은 1부 첫 업무 흐름과 공개 범위를 명시하고 내부 정보를 쓰지 않는다", async () => {
  for (const [id, title] of docs) {
    const markdown = await readFile(new URL(`docs/manual/${id}/index.md`, root), "utf8");
    assert.ok(markdown.startsWith(`# ${title}\n`));
    assert.match(markdown, /공개 범위|로그인 후 조직 전용/u);
    assert.doesNotMatch(markdown, /(?:localhost|127\.0\.0\.1|postgres(?:ql)?:\/\/|\/home\/ubuntu|DAON_[A-Z0-9_]*(?:KEY|TOKEN|SECRET)|BEGIN (?:RSA )?PRIVATE KEY|sinsan\.kr)/u);
    const flow = markdown.slice(markdown.indexOf("## 1부"), markdown.indexOf("## 2부"));
    for (const step of ["노트북", "Source", "질문", "근거", "스튜디오", "문서 작성", "내려받"]) assert.match(flow, new RegExp(step, "u"));
  }
});

test("은퇴한 두 설명서는 원본·dist·공개 사본 어디에도 남지 않는다", () => {
  for (const id of retired) {
    for (const file of [`docs/manual/${id}/index.md`, `docs/manual/dist/${id}.docx`, `docs/manual/dist/${id}.pdf`,
      `apps/web/public/manual/${id}.md`, `apps/web/public/manual/${id}.docx`, `apps/web/public/manual/${id}.pdf`]) {
      assert.equal(existsSync(new URL(file, root)), false, file);
    }
  }
});

test("기존 사용자 매뉴얼은 보호된 초기 관리자와 사용자 관리·콘솔 복구 절차를 제공한다", async () => {
  const userManual = await readFile(new URL("docs/manual/daon-user-manual/index.md", root), "utf8");
  for (const markdown of [userManual]) {
    for (const required of [
      /로그인 ID.*admin/u,
      /이메일.*없/u,
      /(?:최초 시작|최초).*console reset|console reset.*직후|서버 콘솔.*초기화.*직후/su,
      /(?:최초 시작|최초|서버 콘솔.*초기화).*직후에만 `admin\/admin`/su,
      /\/password-change/u,
      /Notebook.*보이지 않/u,
      /삭제.*중지.*(?:할 수 없|불가)/u,
      /시스템 관리자(?:에게)?만.*`사용자 관리`/u,
      /사용자 검색/u,
      /등록 이메일 주소 전체/u,
      /로그인 ID.*사용자 ID.*이메일.*검색/su,
      /이메일 미등록.*`이메일 없음`/su,
      /이메일 인증 대기.*상태 변경.*(?:할 수 없|불가)/su,
      /상태 필터/u,
      /중지/u,
      /재활성화/u,
      /보호됨/u,
      /일반 사용자.*\/admin.*403/u,
      /보호(?:된)? admin.*중지 요청.*HTTP 409.*`PROTECTED_ADMIN_ACCOUNT`/su,
      /python -m daon2_user_api\.admin_cli reset-initial-password/u,
      /INITIAL_ADMIN_PASSWORD_RESET/u,
      /runtime 실패.*`INITIAL_ADMIN_PASSWORD_RESET_FAILED:<오류 코드>`.*(?:exit|종료 코드) 1/isu,
      /잘못된 인자.*usage.*(?:exit|종료 코드) 2/su,
      /비밀번호 변경 성공.*모든 기존 Session.*refresh family.*폐기.*`admin\/admin`.*즉시 무효/su,
      /Workspace.*Notebook.*Source.*Studio/su,
    ]) assert.match(markdown, required);
    assert.doesNotMatch(markdown, /보호(?:된)? admin.*(?:모든 )?상태 변경 요청.*HTTP 409/su);
    // 2026-11-16 조직 가입·관리 화면을 설정 메뉴에 연결하면서 설명서에 절을 둔다(이전에는 미공개 화면이라 금지했다).
    for (const required of [/### 2-12 조직 가입/u, /### 3-10 조직 관리/u, /\/organization-admin/u, /설정.{0,12}조직 가입/su, /초대코드.*직접 전달/su]) assert.match(markdown, required);
    assert.doesNotMatch(markdown, /(?:[A-Za-z]:\\|\/srv\/|\/opt\/|\/var\/www\/|DAON_CLOUD_DATABASE_DSN\s*=|postgres(?:ql)?:\/\/|argon2(?:id)?\$|Bearer\s+[A-Za-z0-9._~-]+)/u);
  }
  assert.match(userManual, /Workspace 관리자.*Workspace 내부.*(?:정책|멤버 권한)/su);
  assert.match(userManual, /Workspace 관리자 역할만으로는.*`\/admin`.*(?:사용할 수 없|접근할 수 없)/su);
  assert.match(userManual, /시스템 관리자.*전체 계정.*검색.*중지.*재활성화/su);
  assert.match(userManual, /공동 작업자를 초대하거나.*Workspace 권한.*(?:변경|편집).*사용자 화면.*(?:없|제공하지 않)/su);
});

test("정본·dist·Web public copies는 한 권×3형식과 그림에서 byte-identical하다", async () => {
  for (const [id] of docs) {
    const [sourceMarkdown, publicMarkdown] = await Promise.all([
      readFile(new URL(`docs/manual/${id}/index.md`, root)),
      readFile(new URL(`apps/web/public/manual/${id}.md`, root)),
    ]);
    assert.deepEqual(publicMarkdown, sourceMarkdown, `${id}.md public copy must equal source bytes`);
    for (const extension of ["docx", "pdf"]) {
      const [dist, published] = await Promise.all([
        readFile(new URL(`docs/manual/dist/${id}.${extension}`, root)),
        readFile(new URL(`apps/web/public/manual/${id}.${extension}`, root)),
      ]);
      assert.deepEqual(published, dist, `${id}.${extension} public copy must equal dist bytes`);
    }
    const { readdir } = await import("node:fs/promises");
    const sourceImages = (await readdir(new URL(`docs/manual/${id}/images/`, root))).filter((name) => /^[a-z0-9-]+\.png$/u.test(name)).sort();
    const publicImages = (await readdir(new URL("apps/web/public/manual/images/", root))).sort();
    assert.deepEqual(publicImages, sourceImages);
    for (const name of sourceImages) {
      assert.deepEqual(await readFile(new URL(`apps/web/public/manual/images/${name}`, root)),
        await readFile(new URL(`docs/manual/${id}/images/${name}`, root)), name);
    }
  }
});

test("Release/Web manifest는 source·dist·public 실제 bytes와 deterministic hash를 결속한다", async () => {
  const [releaseText, webText] = await Promise.all([
    readFile(new URL("docs/manual/release-manifest.json", root), "utf8"),
    readFile(new URL("apps/web/public/manual/manifest.json", root), "utf8"),
  ]);
  assert.equal(webText, releaseText);
  const manifest = JSON.parse(releaseText);
  assert.equal(manifest.schema_version, 1);
  assert.equal(manifest.language, "ko-KR");
  assert.equal(manifest.documents.length, 1);
  assert.equal(manifest.release_version, "2.0.0");
  for (const [id] of docs) {
    const document = manifest.documents.find((entry) => entry.document_id === id);
    assert.ok(document);
    assert.equal(document.version, manifest.release_version);
    assert.match(document.auth_scope, /^(?:public|authenticated|public_and_authenticated)$/u);
    assert.deepEqual(Object.keys(document.assets).sort(), ["docx", "markdown", "pdf"]);
    for (const [kind, asset] of Object.entries(document.assets)) {
      assert.ok(Number.isInteger(asset.bytes) && asset.bytes > 0);
      assert.match(asset.sha256, /^[0-9a-f]{64}$/u);
      assert.match(asset.href, /^\/manual\/[a-z0-9-]+\.(?:md|docx|pdf)$/u);
      const publicBytes = await readFile(new URL(`apps/web/public${asset.href}`, root));
      const canonicalBytes = kind === "markdown"
        ? await readFile(new URL(`docs/manual/${id}/index.md`, root))
        : await readFile(new URL(`docs/manual/dist/${id}.${kind}`, root));
      assert.deepEqual(publicBytes, canonicalBytes);
      assert.equal(asset.bytes, canonicalBytes.byteLength);
      assert.equal(asset.sha256, createHash("sha256").update(canonicalBytes).digest("hex"));
    }
  }
});

test("Evidence manifest의 Network 계수는 실제 JSONL row와 unique path를 결속한다", {
  skip: !existsSync(privateNetworkEvidence) || !existsSync(privateEvidenceManifest),
}, async () => {
  const [networkText, evidenceText] = await Promise.all([
    readFile(privateNetworkEvidence, "utf8"),
    readFile(privateEvidenceManifest, "utf8"),
  ]);
  const rows = networkText.trim().split(/\r?\n/u).map((line) => JSON.parse(line));
  const uniquePaths = new Set(rows.map((row) => row.path));
  const evidence = JSON.parse(evidenceText);
  assert.equal(evidence.network.captured_requests, rows.length);
  assert.equal(evidence.network.unique_request_paths, uniquePaths.size);
  assert.equal(rows.length, 11);
  assert.equal(uniquePaths.size, 4);
});
