// 답변 과정 블록(answer_process.v1, WO-N1 N1-1). 서버 services/api/src/daon2_user_api/answer_process.py와 같은 허용 목록이다.
// 시스템이 한 일(범위·근거 찾기·외부 전송 판정·모델·검증)만 이름·개수·코드로 담는다.

export const MAX_SELECTED_EVIDENCE = 20;
const MAX_KNOWLEDGE_PACKAGES = 20;
const MAX_TOOLS = 20;
const MAX_TEXT = 200;
const ORIGINS = new Set(["raw_source", "daon_knowledge", "mcp_daon_rag", "mcp_law", "notebook_source"]);
const DECISIONS = new Set(["allowed", "blocked", "not_needed"]);
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/u;
const POLICY_REF = /^[0-9a-f]{12}$/u;
const REASONING = /^[A-Za-z0-9_-]{1,32}$/u;
const CONTROL = /[\u0000-\u001f\u007f]/u;
const FORBIDDEN = [
  /:\/\/|\bwww\./iu,
  /(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])/u,
  /(?:\b[0-9a-f]{1,4}:){3,}[0-9a-f]{0,4}|[0-9a-f]{0,4}::[0-9a-f]{0,4}/iu,
  /[^\s@]+@[^\s@]+\.[^\s@]+/u,
  /\blocalhost\b|\b(?:[a-z0-9-]+\.)+(?:com|net|org|kr|io|ai|dev|app|cloud|local|internal|lan|co|biz|info|me|xyz|site|corp|intra|svc|cluster|home)\b/iu,
  /(?<![A-Za-z0-9])(?:sk|pk|rk)-[A-Za-z0-9]/iu,
  /\bBearer\s|\bgh[pousr]_[A-Za-z0-9]|\bxox[abpr]-|\bAKIA[0-9A-Z]{8,}|\beyJ[A-Za-z0-9_-]{8,}/u,
  /[A-Za-z0-9+/_=-]{40,}/u,
];

const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const fail = () => { throw new Error("ANSWER_PROCESS_INVALID"); };

function exact(value, keys) {
  if (!isRecord(value)) fail();
  const actual = Object.keys(value);
  if (actual.length !== keys.length || !keys.every((key) => Object.hasOwn(value, key))) fail();
  return value;
}

export function isSafeProcessText(value, limit = MAX_TEXT) {
  return typeof value === "string" && value.length >= 1 && value.length <= limit && !CONTROL.test(value)
    && !FORBIDDEN.some((pattern) => pattern.test(value));
}

const count = (value, maximum = 100_000) => (Number.isSafeInteger(value) && value >= 0 && value <= maximum ? value : fail());
const flag = (value) => (typeof value === "boolean" ? value : fail());
const text = (value) => (isSafeProcessText(value) ? value : fail());
const optionalText = (value) => (value === null ? null : text(value));
const optionalId = (value) => (value === null ? null : typeof value === "string" && SAFE_ID.test(value) ? value : fail());

/** 허용 목록 밖 키, 주소·IP·호스트·이메일·토큰 모양 문자열이 있으면 Error("ANSWER_PROCESS_INVALID"). */
export function validateAnswerProcess(value) {
  const top = exact(value, ["version", "scope", "evidence", "egress", "model", "verification"]);
  if (top.version !== 1) fail();
  const scope = exact(top.scope, ["source_count", "knowledge_packages", "tools"]);
  if (!Array.isArray(scope.knowledge_packages) || scope.knowledge_packages.length > MAX_KNOWLEDGE_PACKAGES) fail();
  if (scope.tools !== null && (!Array.isArray(scope.tools) || scope.tools.length > MAX_TOOLS
    || !scope.tools.every((item) => isSafeProcessText(item, 120)))) fail();
  const cleanScope = {
    source_count: count(scope.source_count, 1000),
    knowledge_packages: scope.knowledge_packages.map((item) => ({ name: text(exact(item, ["name"]).name) })),
    tools: scope.tools === null ? null : [...scope.tools],
  };
  let cleanEvidence = null;
  if (top.evidence !== null) {
    const evidence = exact(top.evidence, ["searched", "selected"]);
    if (!Array.isArray(evidence.selected) || evidence.selected.length > MAX_SELECTED_EVIDENCE) fail();
    cleanEvidence = {
      searched: count(evidence.searched),
      selected: evidence.selected.map((raw) => {
        const item = exact(raw, ["title", "page", "origin", "source_id", "source_version_id"]);
        if (item.page !== null && (!Number.isSafeInteger(item.page) || item.page < 1)) fail();
        if (!ORIGINS.has(item.origin)) fail();
        return { title: optionalText(item.title), page: item.page, origin: item.origin,
          source_id: optionalId(item.source_id), source_version_id: optionalId(item.source_version_id) };
      }),
    };
  }
  const egress = exact(top.egress, ["decision", "masked", "redacted", "policy_ref"]);
  if (!DECISIONS.has(egress.decision)) fail();
  if (egress.policy_ref !== null && (typeof egress.policy_ref !== "string" || !POLICY_REF.test(egress.policy_ref))) fail();
  const cleanEgress = { decision: egress.decision, masked: flag(egress.masked), redacted: flag(egress.redacted), policy_ref: egress.policy_ref };
  let cleanModel = null;
  if (top.model !== null) {
    const model = exact(top.model, ["connection", "model", "reasoning"]);
    if (model.reasoning !== null && (typeof model.reasoning !== "string" || !REASONING.test(model.reasoning))) fail();
    cleanModel = { connection: optionalText(model.connection), model: optionalText(model.model), reasoning: model.reasoning };
  }
  let cleanVerification = null;
  if (top.verification !== null) {
    const verification = exact(top.verification, ["citations", "valid", "insufficient", "retried"]);
    cleanVerification = { citations: count(verification.citations, 1000), valid: flag(verification.valid),
      insufficient: flag(verification.insufficient), retried: flag(verification.retried) };
  }
  return { version: 1, scope: cleanScope, evidence: cleanEvidence, egress: cleanEgress, model: cleanModel, verification: cleanVerification };
}

/** 검사에 실패하면 null(과정 기록 없음). 답변 자체는 거부하지 않는다. */
export function safeAnswerProcess(value) {
  if (value === undefined || value === null) return null;
  try { return validateAnswerProcess(value); } catch { return null; }
}

/**
 * 답변 객체에서 process를 떼어 검사한 뒤, 열거되지 않는 읽기 전용 속성 `process`로 다시 붙인다.
 * 기존 화면 투영(projectSafeQuestionAnswer)의 정확 키 검사는 그대로 통과하고, 화면은 `answer.process`로 읽는다.
 */
export function withAnswerProcess(answer) {
  if (!isRecord(answer)) return answer;
  const { process, ...rest } = answer;
  Object.defineProperty(rest, "process", { value: safeAnswerProcess(process), enumerable: false, writable: false, configurable: false });
  return rest;
}
