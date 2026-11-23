"use client";

// 메모를 소스로(NB1-U2, WO-N1 N1-3, 결정 D-10). 문구는 notebook-messages.ko.js의 notebook.memo_source.* 키만 쓴다.
// MemoSourceAction: 메모 보기 안의 버튼(소스로 사용 / 소스에 반영 / 소스와 같음)과 진행·완료·실패 표시.
// MemoOriginBadge: 소스 줄의 "메모" 표시(누르면 원본 메모 보기) 또는 "원본 메모 없음"(누를 수 없음).
import { useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";
import "./memo-source.css";

// 서버 source_link → 버튼 상태. null이면 연결 없음, outdated면 반영 필요, 아니면 같음.
export function memoSourceState(link) {
  if (!link) return "none";
  return link.outdated === true ? "outdated" : "same";
}

const ERROR_KEYS = Object.freeze({
  MEMO_EMPTY: "notebook.memo_source.error.memo_empty",
  MEMO_TOO_LARGE: "notebook.memo_source.error.memo_too_large",
  MEMO_SOURCE_EXISTS: "notebook.memo_source.error.memo_source_exists",
  STUDIO_OUTPUT_NOT_FOUND: "notebook.memo_source.error.studio_output_not_found",
  OUTPUT_NOT_MEMO: "notebook.memo_source.error.output_not_memo",
  MEMO_SOURCE_NOT_LINKED: "notebook.memo_source.error.memo_source_not_linked",
  MEMO_SOURCE_UNCHANGED: "notebook.memo_source.error.memo_source_unchanged",
  SOURCE_PROCESSING_ACTIVE: "notebook.memo_source.error.source_processing_active",
  FORBIDDEN: "notebook.memo_source.error.forbidden",
});

export function isMemoSourceForbidden(error) {
  return error?.code === "FORBIDDEN" || error?.status === 403;
}

// 원문 오류 코드는 화면에 그대로 보이지 않는다. 알려진 코드만 문구로 바꾸고 나머지는 일반 문구.
export function memoSourceErrorKey(error) {
  if (isMemoSourceForbidden(error)) return ERROR_KEYS.FORBIDDEN;
  return (typeof error?.code === "string" && ERROR_KEYS[error.code]) || "notebook.memo_source.error.generic";
}

const LABEL_KEYS = { none: "notebook.memo_source.create", outdated: "notebook.memo_source.reflect", same: "notebook.memo_source.same" };
const HINT_KEYS = { none: "notebook.memo_source.hint.create", outdated: "notebook.memo_source.hint.reflect", same: "notebook.memo_source.hint.same" };

/**
 * link: 서버 source_link({source_id, reflected_revision_no, outdated} | null).
 * saving: 메모 자동 저장 대기 중이면 true(저장 전 내용으로 소스를 만들지 않도록 버튼을 잠근다).
 * onCreate/onReflect: 성공하면 끝나는 Promise. 실패하면 {code, status} 오류를 던진다.
 */
export function MemoSourceAction({ link, saving = false, onCreate, onReflect }) {
  const [busy, setBusy] = useState(null); // "create" | "reflect" | null
  const [result, setResult] = useState(null); // { kind: "notice" | "error", key }
  const [forbidden, setForbidden] = useState(false);
  const running = useRef(false);
  const state = memoSourceState(link);
  const run = async () => {
    if (running.current || state === "same") return;
    const kind = state === "none" ? "create" : "reflect";
    running.current = true;
    setBusy(kind); setResult(null);
    try {
      await (kind === "create" ? onCreate : onReflect)?.();
      setResult({ kind: "notice", key: kind === "create" ? "notebook.memo_source.created" : "notebook.memo_source.reflected" });
    } catch (error) {
      if (isMemoSourceForbidden(error)) setForbidden(true);
      setResult({ kind: "error", key: memoSourceErrorKey(error) });
    } finally {
      running.current = false;
      setBusy(null);
    }
  };
  const disabled = busy !== null || saving || state === "same";
  const hintKey = busy ? (busy === "create" ? "notebook.memo_source.creating" : "notebook.memo_source.reflecting")
    : saving && state !== "same" ? "notebook.memo_source.hint.saving" : HINT_KEYS[state];
  return <div className="memo-source" role="group" aria-label={msg("notebook.memo_source.group")} data-state={busy ? "busy" : state}>
    {forbidden ? null : <div className="memo-source__row">
      <button type="button" className={`studio-btn${state === "same" ? "" : " studio-btn--primary"}`} data-memo-source={state}
        disabled={disabled} aria-busy={busy ? "true" : undefined} aria-describedby="memo-source-hint" onClick={() => void run()}>
        {busy ? <span className="memo-source__spinner" aria-hidden="true" /> : null}{msg(LABEL_KEYS[state])}
      </button>
      <small id="memo-source-hint" className="memo-source__hint" role={busy ? "status" : undefined}>{msg(hintKey)}</small>
    </div>}
    {result?.kind === "notice" ? <p className="memo-source__notice" role="status">{msg(result.key)}</p> : null}
    {result?.kind === "error" ? <p className="memo-source__error" role="alert">{msg(result.key)}</p> : null}
  </div>;
}

/** 소스 줄 표시. origin: { memoOutputId, memoExists }. 원본이 있으면 버튼, 없으면 누를 수 없는 표시. */
export function MemoOriginBadge({ origin, name, onOpen }) {
  if (!origin) return null;
  if (!origin.memoExists) {
    return <span className="memo-origin">
      <span className="memo-origin--missing" data-memo-origin-missing="" title={msg("notebook.memo_source.origin.missing_hint")}>
        {msg("notebook.memo_source.origin.missing")}
      </span>
    </span>;
  }
  return <span className="memo-origin">
    <button type="button" className="memo-origin__open" data-memo-origin={origin.memoOutputId}
      aria-label={msg("notebook.memo_source.origin.open", { name })} onClick={() => onOpen?.(origin.memoOutputId)}>
      {msg("notebook.memo_source.origin")}
    </button>
  </span>;
}
