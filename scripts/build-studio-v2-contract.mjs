#!/usr/bin/env node
// Studio v2 OpenAPI 계약 생성기. 기존 v1 계약(openapi.json, 동결)은 건드리지 않는다.
//   node scripts/build-studio-v2-contract.mjs          생성 결과가 저장된 파일과 같은지 검사한다.
//   node scripts/build-studio-v2-contract.mjs --write  packages/contracts/openapi/v1/studio-v2.openapi.json 갱신
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const CONTRACT_PATH = path.join(root, "packages", "contracts", "openapi", "v1", "studio-v2.openapi.json");

export const ERROR_CODES = [
  "INVALID_REQUEST", "AUTHENTICATION_REQUIRED", "RESOURCE_UNAVAILABLE", "IDEMPOTENCY_CONFLICT", "EXPORT_FORMAT_UNSUPPORTED",
  "STUDIO_INPUT_INVALID", "STUDIO_SERVICE_UNAVAILABLE", "STUDIO_DATABASE_UNAVAILABLE", "STUDIO_NO_READY_SOURCE",
  "STUDIO_TYPE_UNAVAILABLE", "STUDIO_VERSION_CONFLICT", "STUDIO_VALIDATION_FAILED", "STUDIO_GENERATION_FAILED",
  "STUDIO_CANCELLED", "STUDIO_EXTERNAL_PROVIDER_UNSUPPORTED", "STUDIO_REVISION_TOO_LARGE", "STUDIO_SOURCE_TOO_LARGE",
  "NOTEBOOK_SCOPE_REQUIRED", "NOTEBOOK_SCOPE_MISMATCH", "OBJECT_STORAGE_UNAVAILABLE",
];
const ref = (name) => ({ $ref: `#/components/schemas/${name}` });
const exact = (properties, required = Object.keys(properties)) => ({ type: "object", additionalProperties: false, required, properties });
const id = { type: "string", pattern: "^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$" };
const time = { type: "string", format: "date-time" };
const nullable = (schema) => ({ ...schema, type: [schema.type, "null"] });
const TYPE_IDS = ["report", "data_table", "mind_map", "flashcards", "quiz", "slides", "infographic", "audio_overview", "video_overview", "memo", "authored_document"];
const STATUS = ["queued", "generating", "completed", "failed", "cancelled"];

const schemas = {
  StudioV2Error: exact({ error: exact({ code: { type: "string", enum: ERROR_CODES }, trace_id: { type: "string" }, retryable: { type: "boolean" } }, ["code"]) }, ["error"]),
  StudioV2Meta: { type: "object", properties: { trace_id: { type: "string" }, workspace_id: id, replayed: { type: "boolean" } }, additionalProperties: false },
  StudioV2Type: exact({
    type_id: { type: "string", enum: TYPE_IDS }, formats: { type: "array", items: { type: "string" } },
    presets: { type: "array", items: { type: "string" } }, export_formats: { type: "array", items: { type: "string" } },
    default_format: nullable({ type: "string" }), available: { type: "boolean" },
    reason: { type: "string", enum: ["STUDIO_TYPE_UNAVAILABLE"] }, settings_schema: { type: "object" },
  }, ["type_id", "formats", "presets", "export_formats", "default_format", "available", "settings_schema"]),
  StudioV2Types: exact({ types: { type: "array", items: ref("StudioV2Type") }, limits: { type: "object", additionalProperties: false, required: ["user_concurrency"], properties: { user_concurrency: { type: "integer", minimum: 1 } } } }),
  StudioV2CreateRequest: exact({
    type_id: { type: "string", enum: TYPE_IDS }, format_id: { type: "string", maxLength: 64 },
    settings: { type: "object" }, source_version_ids: { type: "array", maxItems: 64, items: id },
  }, ["type_id"]),
  StudioV2CreateReceipt: exact({ output_id: id, job_id: id, status: { type: "string", enum: STATUS } }),
  StudioV2Output: exact({
    output_id: id, type_id: { type: "string", enum: TYPE_IDS }, format_id: nullable({ type: "string" }),
    title: { type: "string", minLength: 1, maxLength: 160 }, status: { type: "string", enum: STATUS },
    error_code: nullable({ type: "string" }), source_count: { type: "integer", minimum: 0 },
    current_revision: { type: "integer", minimum: 0 }, created_at: time, updated_at: time, stale: { type: "boolean" },
  }),
  StudioV2OutputPage: exact({ items: { type: "array", maxItems: 50, items: ref("StudioV2Output") }, next_cursor: nullable({ type: "string" }) }),
  StudioV2Evidence: exact({
    ref_id: id, source_version_id: nullable(id), evidence_span_id: nullable(id), locator_kind: nullable({ type: "string" }),
    locator_value: nullable({ type: "string" }), origin: { type: "string", enum: ["notebook_source", "mcp_daon_rag", "mcp_daon", "mcp_law"] },
    has_snapshot: { type: "boolean" }, source_name: nullable({ type: "string" }),
  }, ["ref_id", "source_version_id", "evidence_span_id", "locator_kind", "locator_value", "origin", "has_snapshot"]),
  StudioV2OutputDetail: {
    allOf: [ref("StudioV2Output"), exact({
      settings: { type: "object" },
      revision: nullable({ type: "object" }), evidence: { type: "array", items: ref("StudioV2Evidence") },
      assets: { type: "array", items: exact({ kind: { type: "string" }, bytes: { type: "integer" }, revision_no: { type: "integer" } }) },
    }, ["settings", "revision", "evidence", "assets"])],
  },
  StudioV2RenameRequest: exact({ title: { type: "string", minLength: 1, maxLength: 160 } }),
  StudioV2RenameReceipt: exact({ output_id: id, title: { type: "string" }, updated_at: time }),
  StudioV2RevisionRequest: exact({ content: { type: "object" }, change_reason: { type: "string", maxLength: 200 } }, ["content"]),
  StudioV2RevisionReceipt: exact({ output_id: id, revision_no: { type: "integer", minimum: 1 } }),
  StudioV2RegenerateRequest: exact({ settings: { type: "object" } }, []),
  StudioV2CancelReceipt: exact({ output_id: id, cancel_requested: { type: "boolean" } }),
  StudioV2Provenance: exact({
    output_id: id, revision_no: { type: "integer" }, type_id: { type: "string" }, format_id: nullable({ type: "string" }),
    instruction: exact({ focus: { type: ["string", "null"] }, customization_applied: { type: "boolean" } }),
    settings: { type: "object" },
    sources: { type: "array", items: exact({ source_version_id: id, source_id: nullable(id), name: nullable({ type: "string" }), changed: { type: "boolean" } }) },
    evidence: { type: "array", items: ref("StudioV2Evidence") },
  }),
  StudioV2Sharing: exact({ scope: { type: "string", enum: ["notebook"] }, public_link: { type: "boolean", const: false }, notebook_id: id }),
  StudioV2LearningRequest: exact({ revision_no: { type: "integer", minimum: 1 }, kind: { type: "string", enum: ["flashcard", "quiz"] }, payload: { type: "object" } }),
  StudioV2LearningReceipt: exact({ attempt_id: id }),
  StudioV2LearningAttempt: exact({ attempt_id: id, revision_no: { type: "integer" }, kind: { type: "string" }, payload: { type: "object" }, created_at: time }),
  StudioV2LearningAttempts: exact({ items: { type: "array", items: ref("StudioV2LearningAttempt") } }),
  StudioV2Customization: exact({ instruction: { type: "string", maxLength: 4000 }, version: { type: "integer", minimum: 0 } }),
  StudioV2CustomizationRequest: exact({ instruction: { type: "string", maxLength: 4000 } }),
  StudioV2MemoRequest: exact({ title: { type: "string", maxLength: 160 }, markdown: { type: "string", maxLength: 200000 }, from_run_result_id: { type: "string", maxLength: 256 } }, []),
  StudioV2MemoReceipt: exact({ output_id: id, status: { type: "string", enum: ["completed"] }, replayed: { type: "boolean" } }),
};

Object.assign(schemas, {
  StudioV2AuthoringTemplates: exact({ templates: { type: "array", items: { type: "object" } } }),
  StudioV2AuthoringCreateRequest: exact({ template_id: { type: "string", maxLength: 64 }, request_text: { type: "string", maxLength: 500 } }, []),
  StudioV2AuthoringSession: { type: "object", required: ["state", "template_id", "revision_no"], properties: {
    output_id: id, template_id: { type: "string" }, analysis: { type: ["string", "null"] }, style: { type: ["string", "null"] }, state: { type: "string", enum: ["collecting", "analyzing", "review", "generating", "completed", "failed", "cancelled"] },
    inputs: { type: "object" }, assumptions: { type: "array" }, pending_questions: { type: "array" }, requests: { type: "array" }, requirements: { type: "array" },
    plan: { type: ["object", "null"] }, output_formats: { type: "array" }, document: { type: ["object", "null"] }, revision_no: { type: "integer" }, job_status: { type: "string" } } },
  StudioV2AuthoringAnswersRequest: exact({ expected_revision: { type: "integer", minimum: 1 }, answers: { type: "array", maxItems: 10 }, skip_remaining: { type: "boolean" } }, ["expected_revision", "answers"]),
  StudioV2AuthoringReviewRequest: exact({ expected_revision: { type: "integer", minimum: 1 }, requirements: { type: "array" }, plan_sections: { type: "array" },
    output_formats: { type: "array" }, confirm: { type: "boolean" } }, ["expected_revision"]),
  StudioV2AuthoringReceipt: { type: "object", required: ["output_id", "revision_no"], properties: { output_id: id, revision_no: { type: "integer" }, state: { type: "string" }, queued: { type: "boolean" } } },
});

const envelope = (name) => ({ type: "object", additionalProperties: false, required: ["data", "meta"], properties: { data: ref(name), meta: ref("StudioV2Meta") } });
for (const name of ["AuthoringTemplates", "AuthoringSession", "AuthoringReceipt", "Types", "CreateReceipt", "OutputPage", "OutputDetail", "RenameReceipt", "RevisionReceipt", "CancelReceipt", "Provenance",
  "Sharing", "LearningReceipt", "LearningAttempts", "Customization", "MemoReceipt"]) schemas[`StudioV2${name}Envelope`] = envelope(`StudioV2${name}`);

const parameters = {
  WorkspaceId: { name: "id", in: "path", required: true, schema: id },
  NotebookId: { name: "notebook_id", in: "path", required: true, schema: id },
  OutputId: { name: "output_id", in: "path", required: true, schema: { type: "string", pattern: "^sv2-[0-9a-f]{32}$" } },
  RefId: { name: "ref_id", in: "path", required: true, schema: id },
  FormatName: { name: "format_name", in: "path", required: true, schema: { type: "string", enum: ["docx", "pdf", "md", "txt", "xlsx", "csv", "json", "svg", "png", "pptx", "mp3", "wav", "mp4"] } },
  IdempotencyKey: { name: "Idempotency-Key", in: "header", required: true, schema: { type: "string", minLength: 16, maxLength: 128 } },
  IfMatch: { name: "If-Match", in: "header", required: false, schema: { type: "string" } },
  Revision: { name: "revision", in: "query", required: false, schema: { type: "integer", minimum: 1 } },
  Cursor: { name: "cursor", in: "query", required: false, schema: { type: "string" } },
  Limit: { name: "limit", in: "query", required: false, schema: { type: "integer", minimum: 1, maximum: 50 } },
};
const P = (name) => ({ $ref: `#/components/parameters/${name}` });
const base = [P("WorkspaceId"), P("NotebookId")];
const out = [...base, P("OutputId")];
const json = (name) => ({ required: true, content: { "application/json": { schema: ref(name) } } });
const okJson = (name, description = "OK") => ({ description, content: { "application/json": { schema: ref(name) } } });
const errorResponses = {
  "400": { description: "Invalid request", content: { "application/json": { schema: ref("StudioV2Error") } } },
  "401": { description: "Authentication required", content: { "application/json": { schema: ref("StudioV2Error") } } },
  "404": { description: "Resource unavailable", content: { "application/json": { schema: ref("StudioV2Error") } } },
  "409": { description: "Conflict", content: { "application/json": { schema: ref("StudioV2Error") } } },
};
const op = (operationId, parameters, responses, requestBody) => ({
  operationId, parameters, ...(requestBody ? { requestBody } : {}), responses: { ...responses, ...errorResponses },
});
const S = "/api/v1/workspaces/{id}/notebooks/{notebook_id}/studio";
const binary = (description) => ({ description, headers: { ETag: { schema: { type: "string" } }, "Content-Disposition": { schema: { type: "string" } } },
  content: { "application/octet-stream": { schema: { type: "string", format: "binary" } } } });

const paths = {
  [`${S}/types`]: { get: op("listStudioV2Types", base, { "200": okJson("StudioV2TypesEnvelope") }) },
  [`${S}/outputs`]: {
    get: op("listStudioV2Outputs", [...base, P("Cursor"), P("Limit")], { "200": okJson("StudioV2OutputPageEnvelope") }),
    post: op("createStudioV2Output", [...base, P("IdempotencyKey")], { "200": okJson("StudioV2CreateReceiptEnvelope", "Replayed"), "202": okJson("StudioV2CreateReceiptEnvelope", "Accepted") }, json("StudioV2CreateRequest")),
  },
  [`${S}/outputs/{output_id}`]: {
    get: op("getStudioV2Output", [...out, P("Revision")], { "200": okJson("StudioV2OutputDetailEnvelope") }),
    patch: op("renameStudioV2Output", [...out, P("IfMatch")], { "200": okJson("StudioV2RenameReceiptEnvelope") }, json("StudioV2RenameRequest")),
    delete: op("deleteStudioV2Output", out, { "204": { description: "Deleted" } }),
  },
  [`${S}/outputs/{output_id}/revisions`]: { post: op("createStudioV2Revision", [...out, P("IdempotencyKey")], { "201": okJson("StudioV2RevisionReceiptEnvelope", "Created") }, json("StudioV2RevisionRequest")) },
  [`${S}/outputs/{output_id}/regenerate`]: { post: op("regenerateStudioV2Output", [...out, P("IdempotencyKey")], { "202": okJson("StudioV2CreateReceiptEnvelope", "Accepted") }, json("StudioV2RegenerateRequest")) },
  [`${S}/outputs/{output_id}/cancel`]: { post: op("cancelStudioV2Output", out, { "202": okJson("StudioV2CancelReceiptEnvelope", "Accepted") }) },
  [`${S}/outputs/{output_id}/provenance`]: { get: op("getStudioV2Provenance", [...out, P("Revision")], { "200": okJson("StudioV2ProvenanceEnvelope") }) },
  [`${S}/outputs/{output_id}/exports/{format_name}`]: { get: op("exportStudioV2Output", [...out, P("FormatName"), P("Revision")], { "200": binary("Attachment") }) },
  [`${S}/outputs/{output_id}/audio`]: { get: op("getStudioV2Audio", out, { "200": binary("Audio overview mp3 (supports single Range)"), "206": binary("Partial audio") }) },
  [`${S}/outputs/{output_id}/video`]: { get: op("getStudioV2Video", out, { "200": binary("Video overview mp4 (supports single Range)"), "206": binary("Partial video") }) },
  [`${S}/outputs/{output_id}/sharing`]: { get: op("getStudioV2Sharing", out, { "200": okJson("StudioV2SharingEnvelope") }) },
  [`${S}/outputs/{output_id}/learning-attempts`]: {
    get: op("listStudioV2LearningAttempts", out, { "200": okJson("StudioV2LearningAttemptsEnvelope") }),
    post: op("recordStudioV2LearningAttempt", [...out, P("IdempotencyKey")], { "201": okJson("StudioV2LearningReceiptEnvelope", "Created") }, json("StudioV2LearningRequest")),
  },
  [`${S}/outputs/{output_id}/evidence/{ref_id}/content`]: { get: op("getStudioV2EvidenceContent", [...out, P("RefId"), P("Revision")], { "200": binary("Evidence content") }) },
  [`${S}/customization`]: {
    get: op("getStudioV2Customization", base, { "200": okJson("StudioV2CustomizationEnvelope") }),
    put: op("putStudioV2Customization", [...base, P("IfMatch")], { "200": okJson("StudioV2CustomizationEnvelope") }, json("StudioV2CustomizationRequest")),
  },
  [`${S}/authoring/templates`]: { get: op("listStudioV2AuthoringTemplates", base, { "200": okJson("StudioV2AuthoringTemplatesEnvelope") }) },
  [`${S}/authoring/sessions`]: { post: op("createStudioV2AuthoringSession", [...base, P("IdempotencyKey")], { "201": okJson("StudioV2AuthoringSessionEnvelope", "Created"), "200": okJson("StudioV2AuthoringSessionEnvelope", "Template candidates") }, json("StudioV2AuthoringCreateRequest")) },
  [`${S}/authoring/sessions/{output_id}`]: { get: op("getStudioV2AuthoringSession", out, { "200": okJson("StudioV2AuthoringSessionEnvelope") }) },
  [`${S}/authoring/sessions/{output_id}/answers`]: { post: op("answerStudioV2AuthoringSession", [...out, P("IdempotencyKey")], { "202": okJson("StudioV2AuthoringReceiptEnvelope", "Accepted") }, json("StudioV2AuthoringAnswersRequest")) },
  [`${S}/authoring/sessions/{output_id}/review`]: { put: op("reviewStudioV2AuthoringSession", out, { "202": okJson("StudioV2AuthoringReceiptEnvelope", "Accepted") }, json("StudioV2AuthoringReviewRequest")) },
  [`${S}/memos`]: { post: op("createStudioV2Memo", [...base, P("IdempotencyKey")], { "201": okJson("StudioV2MemoReceiptEnvelope", "Created") }, json("StudioV2MemoRequest")) },
};

export function buildContract() {
  return {
    openapi: "3.1.0",
    info: { title: "Daon2-User Studio v2 API", version: "0.1.0", description: "Studio v2 (flag DAON_STUDIO_V2_ENABLED). The v1 Studio contract in openapi.json is frozen." },
    paths,
    components: { parameters, schemas },
  };
}

const serialize = () => `${JSON.stringify(buildContract(), null, 2)}\n`;

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  if (process.argv.includes("--write")) {
    writeFileSync(CONTRACT_PATH, serialize());
    console.log("studio v2 contract written");
  } else {
    const stored = readFileSync(CONTRACT_PATH, "utf8").replace(/\r\n/g, "\n");
    if (stored !== serialize()) {
      console.error("studio v2 contract is stale; run with --write");
      process.exit(1);
    }
    const document = buildContract();
    const operations = Object.values(document.paths).reduce((sum, item) => sum + Object.keys(item).length, 0);
    console.log(`studio v2 contract verified: paths=${Object.keys(document.paths).length} operations=${operations} schemas=${Object.keys(document.components.schemas).length}`);
  }
}
