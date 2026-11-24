// Provider 연결 시험·저장이 상위 Provider 거부로 실패하면, 어느 모델이 무슨 이유로 거부됐는지 오류 문구에 덧붙인다.
// 서버는 error.details.provider에 안전한 값(model_id, upstream_status, upstream_code·type·param)만 싣는다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { providerDiagnosticText } from "../../apps/web/lib/provider-diagnostic.js";

const workspace = await readFile(new URL("../../apps/web/components/provider-settings-workspace.jsx", import.meta.url), "utf8");
const client = await readFile(new URL("../../apps/web/lib/provider-settings-api.js", import.meta.url), "utf8");

test("실패한 모델과 상위 응답 상태·code를 한 줄로 보여 준다", () => {
  const error = { code: "PROVIDER_CONNECTION_FAILED", details: { provider: {
    model_id: "gpt-6.2-sol", upstream_status: 404, upstream_code: "model_not_found", upstream_type: "invalid_request_error",
  } } };
  assert.equal(providerDiagnosticText(error), " 실패한 모델: gpt-6.2-sol · Provider 응답: HTTP 404 model_not_found");
});

test("code가 없으면 param·type 순으로 사유를 고른다", () => {
  assert.equal(providerDiagnosticText({ details: { provider: { model_id: "m1", upstream_status: 400, upstream_param: "max_tokens" } } }),
    " 실패한 모델: m1 · Provider 응답: HTTP 400 max_tokens");
  assert.equal(providerDiagnosticText({ details: { provider: { upstream_status: 400, upstream_type: "invalid_request_error" } } }),
    " Provider 응답: HTTP 400 invalid_request_error");
});

test("모델만 있으면 모델만, 아무것도 없거나 안전하지 않으면 빈 문자열", () => {
  assert.equal(providerDiagnosticText({ details: { provider: { model_id: "m1" } } }), " 실패한 모델: m1");
  assert.equal(providerDiagnosticText({}), "");
  assert.equal(providerDiagnosticText(null), "");
  assert.equal(providerDiagnosticText({ details: { provider: { model_id: "<script>", upstream_status: "404", upstream_code: "a b" } } }), "");
});

test("API 클라이언트는 오류 details를 넘기고, 시험·저장 실패 문구 모두 진단을 덧붙인다", () => {
  assert.match(client, /error\.details = /u);
  assert.match(workspace, /from "\.\.\/lib\/provider-diagnostic\.js"/u);
  const uses = workspace.match(/providerDiagnosticText\(error\)/gu) ?? [];
  assert.ok(uses.length >= 2, `진단 사용 ${uses.length}곳`);
});
