// Studio v2 패널 모델(순수 함수). WO-S1 T-S1-03. DOM·fetch에 의존하지 않는다.

export const TILE_ORDER = Object.freeze(["audio_overview", "slides", "video_overview", "mind_map", "report", "flashcards", "quiz", "infographic", "data_table", "web_page", "data_aggregation"]);
const ACTIVE = new Set(["queued", "generating"]);
export const POLL_ACTIVE_MS = 1500;
export const POLL_HIDDEN_MS = 10000;

export function createStudioPanelState() {
  return Object.freeze({
    status: "loading", types: [], outputs: [], nextCursor: null, pendingCreate: [], selectedOutputId: null,
    dialog: null, busy: [], error: null,
  });
}

const upsert = (outputs, item) => {
  const index = outputs.findIndex((o) => o.output_id === item.output_id);
  if (index < 0) return [item, ...outputs];
  const next = outputs.slice();
  next[index] = { ...outputs[index], ...item };
  return next;
};

export function reduce(state, action) {
  switch (action.type) {
    case "LOADED":
      return { ...state, status: "ready", types: action.types ?? state.types, outputs: action.outputs ?? state.outputs,
        nextCursor: action.nextCursor ?? null, error: null };
    case "CREATE_STARTED":
      return { ...state, pendingCreate: [...new Set([...state.pendingCreate, action.typeId])], error: null };
    case "OUTPUT_CREATED":
      return { ...state, pendingCreate: state.pendingCreate.filter((t) => t !== action.typeId), outputs: upsert(state.outputs, action.output) };
    case "CREATE_FAILED":
      return { ...state, pendingCreate: state.pendingCreate.filter((t) => t !== action.typeId), error: action.code };
    case "OUTPUT_UPDATED":
      return { ...state, outputs: upsert(state.outputs, action.output) };
    case "OUTPUT_REMOVED":
      return { ...state, outputs: state.outputs.filter((o) => o.output_id !== action.outputId),
        selectedOutputId: state.selectedOutputId === action.outputId ? null : state.selectedOutputId };
    case "POLL_RESULT": {
      // 서버 목록이 정본이다. 낙관적으로 넣은 항목(서버 id가 아직 없음)은 유지한다.
      const server = new Map(action.outputs.map((o) => [o.output_id, o]));
      const kept = state.outputs.filter((o) => server.has(o.output_id) || o.optimistic);
      const merged = kept.map((o) => (server.has(o.output_id) ? server.get(o.output_id) : o));
      const added = action.outputs.filter((o) => !state.outputs.some((x) => x.output_id === o.output_id));
      return { ...state, outputs: [...added, ...merged] };
    }
    case "SELECT":
      return { ...state, selectedOutputId: action.outputId };
    case "DIALOG_OPEN":
      return { ...state, dialog: { kind: action.kind, outputId: action.outputId ?? null, typeId: action.typeId ?? null } };
    case "DIALOG_CLOSE":
      return { ...state, dialog: null };
    case "BUSY":
      return { ...state, busy: action.on ? [...new Set([...state.busy, action.outputId])] : state.busy.filter((id) => id !== action.outputId) };
    case "ERROR":
      return { ...state, error: action.code };
    case "ERROR_CLEARED":
      return { ...state, error: null };
    default:
      return state;
  }
}

export function hasActiveJob(outputs) {
  return outputs.some((o) => ACTIVE.has(o.status));
}

export function pollInterval(outputs, hidden = false) {
  if (!hasActiveJob(outputs)) return null;
  return hidden ? POLL_HIDDEN_MS : POLL_ACTIVE_MS;
}

// 타일 활성 규칙(설계서 §6.1): 유형 미제공 > 소스 없음 > 선택 0개 > 처리 중(준비된 소스가 없고 처리 중) > 활성.
export function tileState(type, { sourceCount = 0, checkedCount = 0, readySourceCount = 0, processingCount = 0, knowledgeCount = 0 } = {}) {
  if (!type || type.available !== true) return { enabled: false, reason: "unavailable" };
  if (type.type_id === "memo") return { enabled: true, reason: null };
  if (knowledgeCount > 0) return { enabled: true, reason: null }; // 승인 지식을 골랐으면 소스 없이도 만들 수 있다
  if (sourceCount === 0) return { enabled: false, reason: "no_sources" };
  if (checkedCount === 0) return { enabled: false, reason: "none_selected" };
  if (readySourceCount === 0 && processingCount > 0) return { enabled: false, reason: "processing" };
  if (readySourceCount === 0) return { enabled: false, reason: "no_sources" };
  return { enabled: true, reason: null };
}

export function formatRelativeTime(iso, now = Date.now()) {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "";
  const seconds = Math.max(0, Math.round((now - time) / 1000));
  if (seconds < 45) return "방금";
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))}분 전`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}시간 전`;
  return `${Math.round(seconds / 86400)}일 전`;
}

const FORMAT_LABELS = Object.freeze({ summary: "요약", briefing: "브리핑", blog: "블로그", study_guide: "스터디 가이드", custom: "사용자 정의" });

// 카드 부제(설계서 §6.4): 보고서 → "{형식} · 소스 N개 · 상대시간", 메모 → 상대시간만.
export function cardSubtitle(output, { now = Date.now() } = {}) {
  const when = formatRelativeTime(output.updated_at ?? output.created_at, now);
  if (output.type_id === "memo") return when;
  const parts = [];
  if (output.format_id && FORMAT_LABELS[output.format_id]) parts.push(FORMAT_LABELS[output.format_id]);
  parts.push(`소스 ${output.source_count}개`, when);
  return parts.join(" · ");
}

export function optimisticOutput(typeId, title, now = Date.now()) {
  const iso = new Date(now).toISOString();
  return { output_id: `pending-${typeId}-${now}`, type_id: typeId, format_id: null, title, status: "queued", error_code: null, source_count: 0,
    current_revision: 0, created_at: iso, updated_at: iso, stale: false, optimistic: true };
}

export const DEFAULT_USER_CONCURRENCY = 2;

/** 접수(queued)만 되고 아직 시작되지 않은 산출물 id 집합: 실행 중인 작업이 사용자 한도 이상이면 남은 대기열 전체, 아니면 한도를 넘는 뒤쪽 순서. */
export function waitingOutputIds(outputs, limit = DEFAULT_USER_CONCURRENCY) {
  const running = outputs.filter((o) => o.status === "generating").length;
  const queued = outputs.filter((o) => o.status === "queued" && !o.optimistic).sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
  const free = Math.max(0, limit - running);
  return new Set(queued.slice(free).map((o) => o.output_id));
}

export function cardState(output) {
  if (output.status === "queued" || output.status === "generating") return "generating";
  if (output.status === "failed") return "failed";
  if (output.status === "cancelled") return "cancelled";
  return output.stale ? "stale" : "ready";
}

export function menuItems(output) {
  const state = cardState(output);
  const done = state === "ready" || state === "stale";
  const items = [
    { id: "share", disabled: !done },
    { id: "rename", disabled: state === "generating" },
    { id: "download", disabled: !done },
    { id: "provenance", disabled: output.current_revision < 1 },
    { id: "delete", disabled: false, danger: true },
  ];
  if (output.type_id !== "memo") {
    items.splice(4, 0, { id: "regenerate", disabled: state === "generating" }, { id: "regenerate_with_settings", disabled: state === "generating" });
  }
  return items;
}

// 심층 조사 진행(WO-N1 NB4-F2 계약): 보고서 생성 작업의 progress.note는 "계획" → "찾기 n/m" → "작성" 세 가지 코드성 문구다.
// 진행 중 보고서가 이 문구일 때만 단계로 바꾸고, 그 밖의 메모(작성 마법사 등)나 다른 유형은 null(기존 문구 그대로)이다. 원문 메모는 화면에 쓰지 않는다.
const RESEARCH_FIND = /^찾기 (\d{1,2})\/(\d{1,2})$/u;
export function researchProgress(output) {
  if (output?.type_id !== "report" || !ACTIVE.has(output.status)) return null;
  const note = output.progress?.note;
  if (note === "계획") return { step: "plan" };
  if (note === "작성") return { step: "write" };
  const find = typeof note === "string" ? RESEARCH_FIND.exec(note) : null;
  if (find && Number(find[1]) >= 1 && Number(find[1]) <= Number(find[2])) return { step: "find", n: Number(find[1]), m: Number(find[2]) };
  return null;
}

// 유형별 서버 진행 메모 → 카드 문구 키. 웹 페이지(WO-N8) 두 단계, 데이터 집계(WO-N9) 세 단계.
const PROGRESS_NOTES = new Map([
  ["web_page", new Map([["내용 만드는 중", "studio.progress.web_page.content"], ["페이지 만드는 중", "studio.progress.web_page.html"]])],
  ["data_aggregation", new Map([["표 읽는 중", "studio.progress.aggregation.read"], ["집계 조건 만드는 중", "studio.progress.aggregation.spec"],
    ["계산 중", "studio.progress.aggregation.compute"]])],
]);

/** 생성 중 카드 문구 키. 서버 진행 메모가 그 유형의 단계 중 하나일 때만, 아니면 null(기존 문구). 원문 메모는 화면에 쓰지 않는다. */
export function progressNoteKey(output) {
  const notes = PROGRESS_NOTES.get(output?.type_id);
  if (!notes || !ACTIVE.has(output.status)) return null;
  return notes.get(output.progress?.note) ?? null;
}

/** 예전 이름(WO-N8). */
export const webPageProgressKey = progressNoteKey;

// 데이터 집계(WO-N9): 표 소스로 고를 수 있는 파일(XLSX·CSV)인지. 처리 완료(ready)된 소스만.
const TABLE_FILE = /\.(xlsx|csv)$/iu;
export const tableSourceKind = (source) => {
  const match = TABLE_FILE.exec(String(source?.filename ?? ""));
  return match ? match[1].toLowerCase() : null;
};
export function tableSources(sources = []) {
  return sources.filter((source) => source?.ready === true && typeof source.sourceVersionId === "string" && tableSourceKind(source) !== null);
}

/** 설정 창이 꼭 필요한 유형(요청 글 필수): 웹 페이지·데이터 집계. 타일을 눌러도 바로 만들지 않는다. */
export function needsSettingsDialog(type) {
  const properties = type?.settings_schema?.properties;
  return Boolean(properties?.page_request || properties?.aggregation_request);
}

/** 진행 막대 너비(%):서버 진행률(progress.pct)이 있으면 그것, 없으면 예전 progress_pct, 둘 다 없으면 20. */
export function progressPercent(output) {
  const pct = output?.progress?.pct ?? output?.progress_pct;
  return Number.isFinite(pct) ? Math.min(100, Math.max(0, pct)) : 20;
}
