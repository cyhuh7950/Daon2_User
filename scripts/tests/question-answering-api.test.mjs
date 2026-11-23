import assert from "node:assert/strict";
import test from "node:test";

import { askGroundedQuestion, authorizeGroundedQuestion, citationContentUrl } from "../../apps/web/lib/question-answering-api.js";

const citation = Object.freeze({
  citation_id: "citation-1",
  source_id: "source-1",
  source_version_id: "version-1",
  evidence_span_id: "span-1",
  page: 2,
  origin: "raw_source",
  context_item_id: "source-1",
  locator: { kind: "page", value: "2" },
});

const answerData = Object.freeze({
  run_id: "run-1",
  run_result_id: "result-1",
  answer: "검증된 근거 답변",
  insufficient: false,
  citations: [citation]
});

const enrichedAnswerData = Object.freeze({
  ...answerData,
  mode: "explicit_source_lookup",
  grounding: "source_backed",
  source_scope_summary: "선택한 Source 범위",
  mismatch: null,
  next_actions: [],
});

const envelope = (data = answerData) => ({
  data,
  meta: { trace_id: "trace-1", workspace_id: "workspace-1" }
});

const request = (payload) => askGroundedQuestion(
  "workspace-1",
  { notebookId: "notebook-1", sourceId: "source-1", sourceVersionId: "version-1", question: "근거는?" },
  { idempotencyKey: "question-1", fetchImpl: async () => Response.json(payload) }
);

test("S18 질문 추가 인증 helper는 동일 입력/key와 signal을 전달하고 취소 후 응답을 사용하지 않는다", async () => {
  const controller = new AbortController();
  let calls = 0;
  const input = { notebookId: "notebook-1", sourceId: "source-1", sourceVersionId: "version-1", question: "근거는?", password: "synthetic-password" };
  const options = { signal: controller.signal, idempotencyKey: "question-s18", fetchImpl: async (url, init) => {
    calls++;
    assert.equal(url, "/bff/api/workspaces/workspace-1/questions/authorization");
    assert.equal(init.signal, controller.signal); assert.equal(init.cache, "no-store"); assert.equal(init.credentials, "same-origin");
    assert.equal(init.headers["Idempotency-Key"], "question-s18");
    assert.deepEqual(JSON.parse(init.body), { notebook_id: "notebook-1", source_id: "source-1", source_version_id: "version-1", question: "근거는?", password: "synthetic-password" });
    return { ok: true, json: async () => { controller.abort(); return { data: { step_up_authorization_id: "grant-s18" } }; } };
  } };
  await assert.rejects(authorizeGroundedQuestion("workspace-1", input, options), { name: "AbortError" });
  assert.equal(calls, 1);
  await assert.rejects(authorizeGroundedQuestion("workspace-1", input, options), { name: "AbortError" });
  assert.equal(calls, 1, "이미 취소된 인증 요청은 전송하지 않는다");
});

test("S18 질문 추가 인증의 실제 opaque URL-safe token은 ID 접두어를 요구하지 않는다", async () => {
  const token = "_" + "a".repeat(63);
  const input = { notebookId: "notebook-1", question: "근거는?", password: "synthetic-password" };
  const grant = await authorizeGroundedQuestion("workspace-1", input, { idempotencyKey: "question-s18", fetchImpl: async () => Response.json({ data: { step_up_authorization_id: token } }) });
  await askGroundedQuestion("workspace-1", input, { idempotencyKey: "question-s18", stepUpAuthorizationId: grant.step_up_authorization_id,
    fetchImpl: async (_url, init) => { assert.equal(JSON.parse(init.body).step_up_authorization_id, token); return Response.json(envelope()); } });
});

test("S18 질문 helper는 현재 Notebook과 signal을 same-origin no-store fetch에 전달한다", async () => {
  const controller = new AbortController();
  const result = await askGroundedQuestion("workspace-1", {
    notebookId: "notebook-1", sourceId: "source-1", sourceVersionId: "version-1", question: "근거는?",
  }, { signal: controller.signal, idempotencyKey: "question-s18", fetchImpl: async (url, init) => {
    assert.equal(url, "/bff/api/workspaces/workspace-1/questions");
    assert.equal(init.method, "POST"); assert.equal(init.signal, controller.signal);
    assert.equal(init.credentials, "same-origin"); assert.equal(init.cache, "no-store");
    assert.equal(init.headers["Idempotency-Key"], "question-s18");
    assert.deepEqual(JSON.parse(init.body), { notebook_id: "notebook-1", source_id: "source-1", source_version_id: "version-1", question: "근거는?" });
    return Response.json(envelope());
  } });
  assert.deepEqual(result, answerData);
});

test("S18 질문 helper는 이미 취소된 요청을 전송하지 않는다", async () => {
  const controller = new AbortController(); controller.abort(); let calls = 0;
  await assert.rejects(askGroundedQuestion("workspace-1", { notebookId: "notebook-1", question: "안녕" }, {
    signal: controller.signal, idempotencyKey: "question-s18", fetchImpl: async () => { calls += 1; return Response.json(envelope()); },
  }), { name: "AbortError" });
  assert.equal(calls, 0);
});

test("S18 질문 helper는 fetch 직후 취소되면 JSON 파싱을 시작하지 않는다", async () => {
  const controller = new AbortController(); let parses = 0;
  await assert.rejects(askGroundedQuestion("workspace-1", { notebookId: "notebook-1", question: "안녕" }, {
    signal: controller.signal, idempotencyKey: "question-s18", fetchImpl: async () => {
      controller.abort(); const response = Response.json(envelope());
      response.json = async () => { parses += 1; return envelope(); }; return response;
    },
  }), { name: "AbortError" });
  assert.equal(parses, 0);
});

test("S18 질문 helper는 JSON 파싱 중 취소된 결과를 반환하지 않는다", async () => {
  const controller = new AbortController(); let resolveJson, started;
  const parsing = new Promise(resolve => { started = resolve; });
  const result = askGroundedQuestion("workspace-1", { notebookId: "notebook-1", question: "안녕" }, {
    signal: controller.signal, idempotencyKey: "question-s18", fetchImpl: async () => {
      const response = Response.json(envelope()); response.json = () => { started(); return new Promise(resolve => { resolveJson = resolve; }); }; return response;
    },
  });
  await parsing; controller.abort(); resolveJson(envelope());
  await assert.rejects(result, { name: "AbortError" });
});

test('PPTX question locator preserves scoped URL and rejects noncanonical ranges',async()=>{
 const locator={kind:'pptx_block',value:'{"block":"s:2:tb:3:r:1:c:2:p:1","start":0,"end":5}'};
 const item={...citation,page:1,locator};
 const answer=await request(envelope({...answerData,citations:[item]}));
 assert.deepEqual(answer.citations[0].locator,locator);
 assert.doesNotMatch(citationContentUrl('workspace-1',item,{notebookId:'notebook-1'}),/#page/u);
 await assert.rejects(()=>request(envelope({...answerData,citations:[{...item,locator:{...locator,value:locator.value.replace('s:2','s:17')}}]})),/QUESTION_RESPONSE_INVALID/);
});

test("sheet_cell question citation validates canonical bounds and preserves scoped URL", async () => {
  const cell = { ...citation, page: 1, locator: { kind: 'sheet_cell', value: '{"sheet":"납품 \\"계획\\"","range":"B2:C3"}' } };
  assert.deepEqual((await request(envelope({ ...answerData, citations: [cell] }))).citations, [cell]);
  assert.equal(citationContentUrl('workspace-1', cell, { notebookId: 'notebook-1' }), '/bff/api/workspaces/workspace-1/citations/citation-1/content?notebook_id=notebook-1');
  for (const value of ['{"sheet":"시트","range":"A1:Q16"}', '{"sheet":"시트","range":"XFE1"}', '{"sheet":"시트", "range":"A1"}', '{"sheet":"시트","range":"A1","extra":1}']) {
    await assert.rejects(request(envelope({ ...answerData, citations: [{ ...cell, locator: { kind: 'sheet_cell', value } }] })), /QUESTION_RESPONSE_INVALID/);
  }
});

test("Image Region Citation은 6개 정수·표시 크기 경계를 검증한다", async () => {
  const imageCitation = { ...citation, page: 1, locator: { kind: "image_region", value: "5,7,80,20,120,60" } };
  assert.deepEqual((await request(envelope({ ...answerData, citations: [imageCitation] }))).citations, [imageCitation]);
  assert.equal(citationContentUrl("workspace-1", imageCitation, { notebookId: "notebook-1" }), "/bff/api/workspaces/workspace-1/citations/citation-1/content?notebook_id=notebook-1");
  for (const value of ["-1,7,80,20,120,60", "5,7,0,20,120,60", "5,7,120,20,120,60", "5,7,80,20,120", "5.5,7,80,20,120,60", "05,7,80,20,120,60", "0,0,1,1,4097,4097"]) {
    await assert.rejects(request(envelope({ ...answerData, citations: [{ ...imageCitation, locator: { kind: "image_region", value } }] })), /QUESTION_RESPONSE_INVALID/);
  }
});

test("Question API는 exact outer/data와 Citation Safe DTO만 반환한다", async () => {
  assert.deepEqual(await request(envelope()), answerData);
  assert.equal(
    citationContentUrl("workspace-1", citation, { notebookId: "notebook-1" }),
    "/bff/api/workspaces/workspace-1/citations/citation-1/content?notebook_id=notebook-1#page=2"
  );
});

test("Question API는 승인된 작업지원 메타데이터를 additive로 수용한다", async () => {
  assert.deepEqual(await request(envelope(enrichedAnswerData)), enrichedAnswerData);
});

test("Daon Text Citation URL은 PDF page fragment를 강제하지 않는다", () => {
  assert.equal(
    citationContentUrl("workspace-1", {
      ...citation,
      origin: "daon_knowledge",
      context_item_id: "knowledge-package-1",
      locator: { kind: "section", value: "span-1" },
    }, { notebookId: "notebook-1" }),
    "/bff/api/workspaces/workspace-1/citations/citation-1/content?notebook_id=notebook-1",
  );
});

test("Question authorization은 same-origin exact body와 동일 Idempotency-Key만 사용한다", async () => {
  const calls = [];
  const data = await authorizeGroundedQuestion("workspace-1", {
    notebookId: "notebook-1", sourceId: "source-1", sourceVersionId: "version-1", question: "근거는?", password: "memory-only",
  }, { idempotencyKey: "question-auth-0001", fetchImpl: async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    return Response.json({ data: { step_up_authorization_id: "grant-1", expires_at: "2026-08-13T00:00:00Z", run_id: "run-1", request_fingerprint: `sha256:${"a".repeat(64)}` }, meta: { trace_id: "trace-1" } }, { status: 201 });
  } });
  assert.equal(data.step_up_authorization_id, "grant-1");
  assert.equal(calls[0].url, "/bff/api/workspaces/workspace-1/questions/authorization");
  assert.equal(calls[0].init.headers["Idempotency-Key"], "question-auth-0001");
  assert.deepEqual(Object.keys(calls[0].body).sort(), ["notebook_id", "password", "question", "source_id", "source_version_id"]);
});

test("DOCX Question client validates exact compact codepoint locator without invented page anchors", async()=>{
  const docx={...citation,page:1,locator:{kind:"docx_block",value:'{"block":"p:2","start":0,"end":1}'}};
  assert.deepEqual((await request(envelope({...answerData,citations:[docx]}))).citations[0],docx);
  assert.doesNotMatch(citationContentUrl("workspace-1",docx,{notebookId:"notebook-1"}),/#page/);
  for(const value of ['{"block":"p:2","start":true,"end":1}','{"block":"p:65","start":0,"end":1}','{"block":"p:2","start":0,"end":1,"extra":1}'])
    await assert.rejects(request(envelope({...answerData,citations:[{...docx,locator:{kind:"docx_block",value}}]})),/QUESTION_RESPONSE_INVALID/);
});

test("audio Question client preserves real time locator without PDF anchor",async()=>{
  const audio={...citation,page:1,locator:{kind:'audio_segment',value:'{"segment":"s:1","start_ms":0,"end_ms":1000,"start":0,"end":1}'}};
  assert.deepEqual((await request(envelope({...answerData,citations:[audio]}))).citations[0],audio);
  assert.doesNotMatch(citationContentUrl('workspace-1',audio,{notebookId:'notebook-1'}),/#page/);
  for(const value of ['{"segment":"s:65","start_ms":0,"end_ms":1000,"start":0,"end":1}',
      '{"segment":"s:1","start_ms":false,"end_ms":1000,"start":0,"end":1}'])
    await assert.rejects(request(envelope({...answerData,citations:[{...audio,locator:{kind:'audio_segment',value}}]})),/QUESTION_RESPONSE_INVALID/);
});

test("Question API는 승인 지식과 Raw Source를 하나의 exact Knowledge Context로 전송한다", async () => {
  const calls = [];
  const knowledgeContext = {
    mode: "mixed",
    resources: [
      { resourceKind: "knowledge_package", resourceId: "package-daon3" },
      { resourceKind: "source", resourceId: "source-1", versionId: "version-1" },
    ],
  };
  await askGroundedQuestion("workspace-1", {
    notebookId: "notebook-1", knowledgeContext, question: "종합해줘",
    stepUpAuthorizationId: "legacy-client-value-must-not-be-sent",
  }, {
    idempotencyKey: "question-mixed-0001",
    fetchImpl: async (url, init) => {
      calls.push({ url, body: JSON.parse(init.body) });
      return Response.json(envelope());
    },
  });
  assert.deepEqual(calls[0].body, {
    notebook_id: "notebook-1",
    question: "종합해줘",
    knowledge_context: {
      mode: "mixed",
      resources: [
        { resource_kind: "knowledge_package", resource_id: "package-daon3" },
        { resource_kind: "source", resource_id: "source-1", version_id: "version-1" },
      ],
    },
  });
  assert.equal("step_up_authorization_id" in calls[0].body, false);
});

test("Question API는 non-JSON gateway timeout과 upstream failure를 안전 오류로 보존한다", async () => {
  const execute = (status) => askGroundedQuestion(
    "workspace-1",
    { notebookId: "notebook-1", sourceId: "source-1", sourceVersionId: "version-1", question: "근거는?" },
    {
      idempotencyKey: "question-gateway-error",
      fetchImpl: async () => new Response("<html>gateway</html>", {
        status, headers: { "Content-Type": "text/html" },
      }),
    },
  );
  await assert.rejects(() => execute(504), { message: "GATEWAY_TIMEOUT" });
  await assert.rejects(() => execute(502), { message: "UPSTREAM_FAILURE" });
});

for (const [name, payload] of [
  ["citations 객체", envelope({ ...answerData, citations: { citation } })],
  ["invalid citation id", envelope({ ...answerData, citations: [{ ...citation, citation_id: "bad/id" }] })],
  ["invalid citation page", envelope({ ...answerData, citations: [{ ...citation, page: 0 }] })],
  ["invalid citation locator", envelope({ ...answerData, citations: [{ ...citation, locator: { kind: "page", value: "3" } }] })],
  ["unknown data field", envelope({ ...answerData, unexpected: true })],
  ["invalid conversation mode", envelope({ ...enrichedAnswerData, mode: "unknown_mode" })],
  ["mismatch without next action", envelope({
    ...enrichedAnswerData, grounding: "source_evidence_unavailable",
    mismatch: { code: "SOURCE_SCOPE_MISMATCH", detail: "범위 불일치" }, next_actions: [],
  })],
  ["unknown outer field", { ...envelope(), unexpected: true }]
]) {
  test(`Question API는 ${name} 응답을 QUESTION_RESPONSE_INVALID로 거부한다`, async () => {
    await assert.rejects(request(payload), { message: "QUESTION_RESPONSE_INVALID" });
  });
}

test("승인 지식 인용 종류는 질문 응답에서 허용되고 알 수 없는 종류는 거부된다", async () => {
  const answer = (origin) => {
    const external = { ...citation, citation_id: "extcit-1", origin, locator: { kind: "section", value: "span-1" } };
    return request(envelope({ ...answerData, citations: [external] }));
  };
  assert.equal((await answer("mcp_daon_rag")).citations[0].origin, "mcp_daon_rag");
  await assert.rejects(answer("mcp_unknown"));
});

test("문서명은 승인 지식 인용에만 허용된다", async () => {
  const answer = (extra) => request(envelope({ ...answerData, citations: [{ ...citation, citation_id: "extcit-1", origin: "mcp_daon_rag", locator: { kind: "section", value: "span-1" }, ...extra }] }));
  assert.equal((await answer({ document_name: "제안요청서.pdf" })).citations[0].document_name, "제안요청서.pdf");
  await assert.rejects(answer({ document_name: "" }));
  await assert.rejects(answer({ document_name: 3 }));
  await assert.rejects(answer({ document_name: "가".repeat(1025) }));
  await assert.rejects(answer({ origin: "raw_source", document_name: "제안요청서.pdf" }));
});

// ---- NB1-F1 답변 과정(process) ---------------------------------------------------------------
const answerProcess = Object.freeze({
  version: 1,
  scope: { source_count: 2, knowledge_packages: [{ name: "제안서 작업" }], tools: null },
  evidence: { searched: 24, selected: [{ title: "약관.txt", page: 3, origin: "raw_source", source_id: "source-1", source_version_id: "version-1" }] },
  egress: { decision: "allowed", masked: false, redacted: false, policy_ref: "3f2a9c1b0d4e" },
  model: { connection: "Media Bridge", model: "uss/solar-pro4", reasoning: null },
  verification: { citations: 3, valid: true, insufficient: false, retried: false },
});
const clone = (value) => JSON.parse(JSON.stringify(value));

test("NB1-F1 질문 응답의 process를 허용 목록 검사 후 결과의 process로 돌려준다(화면 정확 키 검사는 그대로)", async () => {
  const result = await request(envelope({ ...enrichedAnswerData, process: clone(answerProcess) }));
  assert.deepEqual(result.process, answerProcess);
  assert.deepEqual(Object.keys(result).sort(), Object.keys(enrichedAnswerData).sort(), "process는 열거되지 않아 기존 화면 투영의 정확 키 검사를 깨지 않는다");
  assert.deepEqual(result, enrichedAnswerData);
});

test("NB1-F1 process가 없거나 null인 과거 답변은 process=null", async () => {
  assert.equal((await request(envelope(enrichedAnswerData))).process, null);
  assert.equal((await request(envelope({ ...enrichedAnswerData, process: null }))).process, null);
});

test("NB1-F1 잘못된 process는 답변 전체를 거부하지 않고 process=null로 낮춘다", async () => {
  const cases = [
    { ...clone(answerProcess), prompt: "원문" },
    { ...clone(answerProcess), model: { connection: "http://10.0.0.1", model: "m", reasoning: null } },
    { ...clone(answerProcess), evidence: { searched: 1, selected: [{ ...answerProcess.evidence.selected[0], title: "sk-proj-abcdef123456" }] } },
    { ...clone(answerProcess), egress: { ...answerProcess.egress, decision: "denied" } },
    "process",
  ];
  for (const process of cases) {
    const result = await request(envelope({ ...enrichedAnswerData, process }));
    assert.equal(result.process, null);
    assert.equal(result.answer, enrichedAnswerData.answer);
  }
});

test("NB1-F1 외부 전송 차단 오류는 기존 코드로 실패하고 오류의 process에 blocked 블록을 싣는다", async () => {
  const blocked = { ...clone(answerProcess), verification: null, egress: { decision: "blocked", masked: false, redacted: false, policy_ref: null } };
  const failing = (details) => askGroundedQuestion(
    "workspace-1", { notebookId: "notebook-1", sourceId: "source-1", sourceVersionId: "version-1", question: "근거는?" },
    { idempotencyKey: "question-1", fetchImpl: async () => Response.json({ error: { code: "EGRESS_POLICY_DENIED", details } }, { status: 403 }) });
  await assert.rejects(failing({ process: blocked }), (error) => error.message === "EGRESS_POLICY_DENIED" && JSON.stringify(error.process) === JSON.stringify(blocked));
  await assert.rejects(failing({}), (error) => error.message === "EGRESS_POLICY_DENIED" && error.process === null);
  await assert.rejects(failing({ process: { ...blocked, extra: 1 } }), (error) => error.process === null);
});

test("NB1-F1 validateAnswerProcess는 서버와 같은 허용 목록·금지 문자열·최대 개수를 검사한다", async () => {
  const { validateAnswerProcess } = await import("../../apps/web/lib/answer-process.js");
  assert.deepEqual(validateAnswerProcess(clone(answerProcess)), answerProcess);
  const general = { ...clone(answerProcess), scope: { source_count: 0, knowledge_packages: [], tools: null }, evidence: null, model: null };
  assert.deepEqual(validateAnswerProcess(clone(general)), general);
  for (const text of ["http://10.0.0.1/v1", "10.0.0.1", "sk-proj-abcdef123456", "admin@example.com", "provider.internal", "fe80::1", "A".repeat(48)]) {
    assert.throws(() => validateAnswerProcess({ ...clone(answerProcess), model: { connection: text, model: "m", reasoning: null } }), /ANSWER_PROCESS_INVALID/u, text);
  }
  const many = { ...clone(answerProcess), evidence: { searched: 30, selected: Array.from({ length: 21 }, () => clone(answerProcess.evidence.selected[0])) } };
  assert.throws(() => validateAnswerProcess(many), /ANSWER_PROCESS_INVALID/u);
  assert.throws(() => validateAnswerProcess({ ...clone(answerProcess), version: 2 }), /ANSWER_PROCESS_INVALID/u);
});

test("NB1-F1 listChatTurns도 답변의 process를 같은 규칙으로 검사해 붙인다", async () => {
  const { listChatTurns } = await import("../../apps/web/lib/studio-v2-api.js");
  const turn = (process) => ({ run_id: "run-1", created_at: "2026-11-23T00:00:00+00:00", state: "completed", question: "근거는?",
    context_mode: "raw_only", unavailable: false, answer: { ...enrichedAnswerData, ...(process === undefined ? {} : { process }) } });
  const fetchImpl = async () => Response.json({ data: { turns: [turn(clone(answerProcess)), turn(undefined), turn({ ...clone(answerProcess), extra: 1 }),
    { run_id: "run-2", created_at: "2026-11-23T00:00:01+00:00", state: "failed", question: "q", context_mode: "raw_only", unavailable: false, answer: null }] },
    meta: { trace_id: "trace-1" } });
  const turns = await listChatTurns("workspace-1", { notebookId: "notebook-1", fetchImpl });
  assert.deepEqual(turns[0].answer.process, answerProcess);
  assert.deepEqual(Object.keys(turns[0].answer).sort(), Object.keys(enrichedAnswerData).sort());
  assert.equal(turns[1].answer.process, null);
  assert.equal(turns[2].answer.process, null);
  assert.equal(turns[3].answer, null);
});
