"use client";

// 노트북 개요·추천 질문(NB2-U2, WO-N1 N1-4, 결정 D-06 자동 1회 + "다시 만들기"). 문구는 notebook-messages.ko.js의 notebook.overview.* 키만 쓴다.
// 대화 영역 위쪽에 둔다. 상태: none(그리지 않음 — 기존 빈 화면 유지) / queued·working(자리 표시) / ready(요약 + 인용 칩 + 추천 질문 3개)
// / ready+stale(낡음 안내 + 다시 만들기) / failed(오류 코드별 문구 + 다시 시도) / blocked(정책 문구 + 시작 제안 3개).
// 값의 정본은 서버다. queued·working이면 pollIntervalMs(기본 3초)마다 다시 읽고 none·ready·failed·blocked에서 멈춘다.
// refreshKey가 바뀌면(셸: 준비된 소스 목록이 바뀜) 다시 읽는다. 첫 자동 생성(queued)은 서버가 GET에서 만든다.
// 다시 만들기는 편집 권한자만 된다. 응답에 권한 값이 없으므로 403을 받으면 버튼을 숨긴다(NB1-U2 memo-source와 같은 방식).
// studio: 노트북 범위 어댑터. getNotebookOverview({signal}), regenerateNotebookOverview(). 조회 함수가 없으면 그리지 않는다.
// onAskQuestion(text): 추천 질문 칩 → 입력창에 채우기만 한다(전송하지 않는다). onOpenSource(citation): 인용 칩 → 소스 보기. 없으면 칩은 표시만 한다.
// storage: 접기 상태 저장소(기본 localStorage). 노트북별 키, 읽기·쓰기 실패는 무시한다.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";
import "./notebook-overview.css";

export const NOTEBOOK_OVERVIEW_POLL_MS = 3000;
const ACTIVE_STATES = new Set(["queued", "working"]);
const ERROR_CODES = new Set(["OVERVIEW_UNGROUNDED", "OVERVIEW_BLOCKED", "OVERVIEW_NO_READY_SOURCE", "OVERVIEW_PROVIDER_UNAVAILABLE", "OVERVIEW_GENERATION_FAILED"]);
const START_KEYS = ["notebook.overview.start.learn", "notebook.overview.start.create", "notebook.overview.start.project"];
const STORAGE_PREFIX = "daon.notebook-overview.collapsed.";

function defaultStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}
function readCollapsed(storage, notebookId) {
  if (!notebookId) return false;
  try { return storage?.getItem?.(`${STORAGE_PREFIX}${notebookId}`) === "1"; } catch { return false; }
}
function writeCollapsed(storage, notebookId, collapsed) {
  if (!notebookId) return;
  try {
    if (collapsed) storage?.setItem?.(`${STORAGE_PREFIX}${notebookId}`, "1");
    else storage?.removeItem?.(`${STORAGE_PREFIX}${notebookId}`);
  } catch {
    // 저장이 막혀도 이번 화면에서는 접기가 동작한다.
  }
}

const errorText = (code) => (ERROR_CODES.has(code) ? msg(`notebook.overview.error.${code.toLowerCase()}`) : msg("notebook.overview.error.generic"));
const isForbidden = (error) => error?.code === "FORBIDDEN" || error?.status === 403;
const citationText = (citation, open) => {
  const base = open ? "notebook.overview.citation.open" : "notebook.overview.citation.label";
  return msg(citation.page ? `${base}_page` : base, { label: citation.label, title: citation.source_title, page: citation.page });
};

// 요약의 각 문장 끝 [n]을 인용 칩으로 바꾼다. 인용 목록에 없는 번호는 글자 그대로 둔다.
function summaryParts(summary, citations) {
  const byLabel = new Map(citations.map((citation) => [citation.label, citation]));
  const parts = [];
  const pattern = /\[([1-9][0-9]{0,2})\]/gu;
  let last = 0;
  for (const match of summary.matchAll(pattern)) {
    if (match.index > last) parts.push({ text: summary.slice(last, match.index) });
    const citation = byLabel.get(match[1]);
    parts.push(citation ? { citation } : { text: match[0] });
    last = match.index + match[0].length;
  }
  if (last < summary.length) parts.push({ text: summary.slice(last) });
  return parts;
}

export function NotebookOverview({ studio, notebookId = null, refreshKey = null, onAskQuestion, onOpenSource, pollIntervalMs = NOTEBOOK_OVERVIEW_POLL_MS, storage }) {
  const supported = typeof studio?.getNotebookOverview === "function";
  const store = useMemo(() => (storage === undefined ? defaultStorage() : storage), [storage]);
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | loaded | error
  const [fetchTick, setFetchTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [forbidden, setForbidden] = useState(false);
  const [collapsed, setCollapsed] = useState(() => readCollapsed(store, notebookId));
  const mounted = useRef(true);
  // 다시 만들기 직후에는 이미 queued를 받았으므로 바로 읽지 않고 한 간격 뒤에 읽는다.
  const delayNextRef = useRef(false);
  const baseId = useId();
  const titleId = `${baseId}-title`;
  const bodyId = `${baseId}-body`;

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  // 노트북이 바뀌면 이전 노트북의 개요·안내·권한 판단을 버린다.
  useEffect(() => { setData(null); setStatus("loading"); setNotice(null); setForbidden(false); }, [studio]);
  useEffect(() => { setCollapsed(readCollapsed(store, notebookId)); }, [store, notebookId]);

  useEffect(() => {
    if (!supported) return undefined;
    const controller = new AbortController();
    let timer = null;
    const load = async () => {
      timer = null;
      try {
        const value = await studio.getNotebookOverview({ signal: controller.signal });
        if (controller.signal.aborted || !mounted.current) return;
        setData(value);
        setStatus("loaded");
        if (ACTIVE_STATES.has(value?.state)) timer = setTimeout(load, pollIntervalMs);
        else setNotice((current) => (current === "in_progress" ? null : current));
      } catch {
        if (!controller.signal.aborted && mounted.current) setStatus("error");
      }
    };
    if (delayNextRef.current) { delayNextRef.current = false; timer = setTimeout(load, pollIntervalMs); }
    else void load();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [studio, supported, refreshKey, fetchTick, pollIntervalMs]);

  const reload = () => { setStatus((current) => (current === "error" ? "loading" : current)); setFetchTick((value) => value + 1); };

  const regenerate = async () => {
    if (busy || typeof studio?.regenerateNotebookOverview !== "function") return;
    setBusy(true);
    setNotice(null);
    try {
      const value = await studio.regenerateNotebookOverview();
      if (!mounted.current) return;
      // 서버가 이전 내용을 비우고 queued를 돌려준다. 만드는 동안 이전 개요는 보이지 않는다.
      setData(value ?? { state: "queued", summary: null, questions: [], citations: [], stale: false, generated_at: null, error_code: null });
      setStatus("loaded");
      delayNextRef.current = ACTIVE_STATES.has(value?.state ?? "queued");
      setFetchTick((tick) => tick + 1);
    } catch (error) {
      if (!mounted.current) return;
      if (isForbidden(error)) { setForbidden(true); setNotice("forbidden"); }
      else if (error?.code === "OVERVIEW_IN_PROGRESS") { setNotice("in_progress"); setFetchTick((tick) => tick + 1); }
      else if (error?.code === "OVERVIEW_NO_READY_SOURCE") { setNotice("no_ready_source"); setFetchTick((tick) => tick + 1); }
      else setNotice("failed");
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const toggleCollapsed = () => {
    setCollapsed((current) => {
      const next = !current;
      writeCollapsed(store, notebookId, next);
      return next;
    });
  };

  if (!supported) return null;
  if (!data && status !== "error") return null;
  if (data?.state === "none" && status !== "error") return null;

  const state = data?.state;
  const viewState = !data ? "error" : ACTIVE_STATES.has(state) ? "generating" : state;
  const generating = viewState === "generating";
  const canRegenerate = !forbidden && typeof studio?.regenerateNotebookOverview === "function";
  const regenerateButton = (key) => <button type="button" className="notebook-overview__action" disabled={busy} aria-busy={busy ? "true" : undefined} onClick={() => { void regenerate(); }}>{msg(key)}</button>;

  let body = null;
  if (generating) {
    body = <>
      <p className="notebook-overview__status" role="status">{msg("notebook.overview.generating")}</p>
      <small className="notebook-overview__hint">{msg("notebook.overview.generating.hint")}</small>
      <div className="notebook-overview__skeleton" aria-hidden="true"><span /><span /><span /></div>
    </>;
  } else if (viewState === "ready") {
    const citations = Array.isArray(data.citations) ? data.citations : [];
    const questions = Array.isArray(data.questions) ? data.questions : [];
    body = <>
      {data.stale ? <div className="notebook-overview__stale" role="status">
        <span>{msg("notebook.overview.stale")}</span>
        {canRegenerate ? regenerateButton("notebook.overview.regenerate") : null}
      </div> : null}
      <p className="notebook-overview__summary" aria-label={msg("notebook.overview.summary")}>
        {summaryParts(String(data.summary ?? ""), citations).map((part, index) => {
          if (!part.citation) return <span key={index}>{part.text}</span>;
          const { citation } = part;
          if (typeof onOpenSource === "function") {
            return <button key={index} type="button" className="notebook-overview__cite" data-overview-citation={citation.label}
              aria-label={citationText(citation, true)} title={citationText(citation, false)} onClick={() => onOpenSource({ ...citation }, { stale: data.stale })}>{citation.label}</button>;
          }
          return <span key={index} className="notebook-overview__cite" data-overview-citation={citation.label} role="img"
            aria-label={citationText(citation, false)} title={citationText(citation, false)}>{citation.label}</span>;
        })}
      </p>
      {questions.length ? <div className="notebook-overview__questions">
        <strong className="notebook-overview__label">{msg("notebook.overview.questions")}</strong>
        <ul className="notebook-overview__chips">
          {questions.map((question, index) => <li key={index}>
            <button type="button" className="notebook-overview__question" data-overview-question="" disabled={typeof onAskQuestion !== "function"}
              aria-label={msg("notebook.overview.question.label", { question })} onClick={() => onAskQuestion?.(question)}>{question}</button>
          </li>)}
        </ul>
        <small className="notebook-overview__hint">{msg("notebook.overview.questions.hint")}</small>
      </div> : null}
      {!data.stale && canRegenerate ? <div className="notebook-overview__footer">{regenerateButton("notebook.overview.regenerate")}</div> : null}
    </>;
  } else if (viewState === "failed") {
    body = <div className="notebook-overview__failed">
      <p className="notebook-overview__alert" role="alert">{errorText(data.error_code)}</p>
      {canRegenerate ? regenerateButton("notebook.overview.retry") : null}
    </div>;
  } else if (viewState === "blocked") {
    body = <>
      <p className="notebook-overview__status" role="status">{msg("notebook.overview.blocked")}</p>
      <strong className="notebook-overview__label">{msg("notebook.overview.start.title")}</strong>
      <ul className="notebook-overview__starts">
        {START_KEYS.map((key) => <li key={key} className="notebook-overview__start" data-overview-start="">{msg(key)}</li>)}
      </ul>
    </>;
  }

  return <section className="notebook-overview" data-notebook-overview="" data-overview-state={viewState} aria-labelledby={titleId} aria-busy={generating ? "true" : undefined}>
    <header className="notebook-overview__header">
      <h3 className="notebook-overview__title" id={titleId}>{msg("notebook.overview.title")}</h3>
      <button type="button" className="notebook-overview__collapse" aria-expanded={collapsed ? "false" : "true"} aria-controls={bodyId} onClick={toggleCollapsed}>
        {msg(collapsed ? "notebook.overview.expand" : "notebook.overview.collapse")}
      </button>
    </header>
    {collapsed ? null : <div className="notebook-overview__body" id={bodyId}>
      {status === "error" ? <p className="notebook-overview__alert" role="alert">
        {msg("notebook.overview.loading_failed")}
        <button type="button" className="notebook-overview__action" onClick={reload}>{msg("notebook.overview.retry")}</button>
      </p> : null}
      {body}
      {notice ? <p className="notebook-overview__notice" role="status">{msg(`notebook.overview.notice.${notice}`)}</p> : null}
    </div>}
  </section>;
}
