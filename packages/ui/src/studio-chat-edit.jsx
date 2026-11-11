"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { shouldSubmitOnEnter } from "./answer-presentation.js";
import { msg, studioErrorMessage } from "./studio-messages.ko.js";

// 완료 자료 대화 수정(WO-K5): 말로 지시하고, 고치기 전·후를 본 뒤 반영한다.

export const CHAT_EDIT_TYPES = ["report", "slides", "flashcards", "quiz", "authored_document"];
const POLL_MS = 2000;
const ACTIVE = new Set(["queued", "working"]);
const STATE_NOTE = { applied: "studio.chat_edit.applied", discarded: "studio.chat_edit.discarded" };
// 위치 표시용으로 앞 조각의 글을 짧게 줄인다.
const clip = (text, limit = 20) => { const one = String(text).split(/\s+/u).join(" ").trim(); return one.length > limit ? `${one.slice(0, limit)}…` : one; };

function Change({ change }) {
  return <div className="studio-chat-edit__change">
    <p className="studio-chat-edit__piece">{change.op === "insert_after" && change.anchor_text ? `‘${clip(change.anchor_text)}’ ` : ""}{msg(`studio.chat_edit.op.${change.op}`)}{change.reason ? ` · ${change.reason}` : ""}</p>
    <div className="studio-chat-edit__compare">
      <div><strong>{msg("studio.chat_edit.before")}</strong><p>{change.before_text || msg("studio.chat_edit.empty")}</p></div>
      <div><strong>{msg("studio.chat_edit.after")}</strong><p>{change.after_text || msg("studio.chat_edit.empty")}</p></div>
    </div>
  </div>;
}

function Turn({ turn, busy, onApply, onDiscard }) {
  const note = STATE_NOTE[turn.state];
  return <li className="studio-chat-edit__turn">
    <p className="studio-chat-edit__instruction">{turn.instruction}</p>
    {ACTIVE.has(turn.state) && <p role="status">{msg("studio.chat_edit.working")}</p>}
    {turn.reply && <p>{turn.reply}</p>}
    {turn.state === "failed" && <p className="studio-alert" role="alert">{studioErrorMessage(turn.error_code)}</p>}
    {turn.changes.map((change, index) => <Change key={index} change={change} />)}
    {turn.state === "ready" && <div className="studio-chat-edit__actions">
      <button type="button" className="studio-btn studio-btn--primary" disabled={busy} onClick={() => onApply(turn.turn_id)}>{msg("studio.chat_edit.apply")}</button>
      <button type="button" className="studio-btn" disabled={busy} onClick={() => onDiscard(turn.turn_id)}>{msg("studio.chat_edit.discard")}</button>
    </div>}
    {note && <p role="status">{msg(note)}</p>}
  </li>;
}

export function StudioChatEdit({ studio, outputId, onApplied, pollMs = POLL_MS }) {
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [listRetry, setListRetry] = useState(0);
  const alive = useRef(true);
  const working = useRef(false);

  const load = useCallback(async () => {
    try {
      const next = await studio.listEditTurns(outputId);
      if (alive.current) { setTurns(next); setListRetry(0); }
    } catch {
      if (alive.current) setListRetry((count) => count + 1);  // 일시 오류면 다음 조회로 잇는다
    }
  }, [studio, outputId]);

  useEffect(() => {
    alive.current = true;
    load();
    return () => { alive.current = false; };
  }, [load]);

  const active = turns.some((turn) => ACTIVE.has(turn.state));
  useEffect(() => {
    if (!active) return undefined;
    const timer = setTimeout(load, pollMs);
    return () => clearTimeout(timer);
  }, [active, turns, listRetry, load, pollMs]);

  const run = async (work) => {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (failure) {
      if (alive.current) setError(failure?.code ?? "STUDIO_REQUEST_FAILED");
    } finally {
      working.current = false;
      if (alive.current) setBusy(false);
      await load();
    }
  };

  const send = () => {
    const instruction = draft.trim();
    if (!instruction || active) return undefined;
    return run(async () => {
      await studio.createEditTurn(outputId, { instruction });
      if (alive.current) setDraft("");
    });
  };
  const apply = (turnId) => run(async () => {
    await studio.applyEditTurn(outputId, turnId);
    await onApplied?.();
  });
  const discard = (turnId) => run(() => studio.discardEditTurn(outputId, turnId));

  return <section className="studio-chat-edit" aria-label={msg("studio.chat_edit.title")}>
    <h3>{msg("studio.chat_edit.title")}</h3>
    {(error || listRetry > 0) && <p className="studio-alert" role="alert">{studioErrorMessage(error ?? "STUDIO_REQUEST_FAILED")}</p>}
    <ul className="studio-chat-edit__turns">
      {turns.map((turn) => <Turn key={turn.turn_id} turn={turn} busy={busy} onApply={apply} onDiscard={discard} />)}
    </ul>
    <div className="studio-chat-edit__input">
      <textarea aria-label={msg("studio.chat_edit.input")} placeholder={msg("studio.chat_edit.placeholder")} rows={2} maxLength={2000} value={draft} disabled={active || busy}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => { if (shouldSubmitOnEnter(event)) { event.preventDefault(); send(); } }} />
      <button type="button" className="studio-btn studio-btn--primary" disabled={active || busy || !draft.trim()} onClick={send}>{msg("studio.chat_edit.send")}</button>
    </div>
  </section>;
}

export default StudioChatEdit;
