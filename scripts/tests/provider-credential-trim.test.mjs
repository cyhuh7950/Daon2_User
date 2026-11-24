// 붙여 넣은 Provider Key의 앞뒤 공백 때문에 서버가 "Key가 필요합니다"(PROVIDER_CREDENTIAL_REQUIRED)로 거절하던 문제.
// 화면은 Key를 보낼 때 앞뒤 공백을 지운 값만 보낸다. 서버의 공백 거절(보호)은 그대로 둔다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { requestCredential } from "../../apps/web/lib/provider-credential.js";

const source = await readFile(new URL("../../apps/web/components/provider-settings-workspace.jsx", import.meta.url), "utf8");

test("Key 앞뒤 공백·줄바꿈·탭을 지운다", () => {
  assert.equal(requestCredential("  sk-test-123 "), "sk-test-123");
  assert.equal(requestCredential("sk-test-123\n"), "sk-test-123");
  assert.equal(requestCredential("\tsk-test-123\r\n"), "sk-test-123");
  assert.equal(requestCredential("sk-test-123"), "sk-test-123");
});

test("가운데 공백은 바꾸지 않는다(Key 값 자체를 고치지 않음)", () => {
  assert.equal(requestCredential(" ab cd "), "ab cd");
});

test("비었거나 공백뿐이면 빈 문자열, 문자열이 아니면 빈 문자열", () => {
  assert.equal(requestCredential("   "), "");
  assert.equal(requestCredential(""), "");
  assert.equal(requestCredential(undefined), "");
  assert.equal(requestCredential(null), "");
});

test("설정 화면은 Key를 공백을 지운 값으로만 보낸다", () => {
  assert.match(source, /from "\.\.\/lib\/provider-credential\.js"/u);
  // 공백을 지우지 않은 원래 입력값을 요청 본문에 그대로 싣지 않는다.
  assert.doesNotMatch(source, /\{ credential \}/u, "원래 입력값 credential을 그대로 보냄");
  assert.doesNotMatch(source, /\{ test_credential: credential \}/u, "원래 입력값을 test_credential로 그대로 보냄");
  assert.doesNotMatch(source, /credential: ownPersonalCredential,/u, "원래 개인 Key 입력값을 그대로 보냄");
});

test("Key 교체 요청도 공백을 지운 Key만 보낸다(속성 줄임표기 credential, 금지)", () => {
  assert.doesNotMatch(source, /^\s+credential,\s*$/mu, "Key 원래 입력값을 줄임표기로 그대로 보냄");
});

test("개인 연결이 모델 확인을 통과해 저장되면 '시험 통과하지 않음'이 아니라 통과·Key 미저장을 알린다", () => {
  assert.match(source, /const personalProbed = /u);
  assert.match(source, /모델 확인을 통과했고 연결을 저장했습니다\. 개인 연결이라 시험 Key는 저장하지 않았습니다/u);
});
