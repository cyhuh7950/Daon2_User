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
    assert.doesNotMatch(markdown, /##+ .*조직\s*(?:가입|관리|관리자)|설정.{0,30}조직\s*가입|\/organization(?:-admin|\/join)|(?:조직|organization).{0,50}(?:초대\s*코드|가입\s*신청|가입하기|관리\s*(?:화면|콘솔))/isu);
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
