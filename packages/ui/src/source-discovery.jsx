"use client";

// 자료 찾기·빠른 찾기(NB4-U1)·심층 조사(NB4-U2) (WO-N1 N1-7, 결정 D-02 웹 제외 — 내부 승인 지식·지식 연결만). 문구는 notebook-messages.ko.js의
// notebook.source_discovery.* 키만 쓴다. 셸 소스 칸 위쪽에 놓이며 기존 소스 목록·소스 묶음 동작은 건드리지 않는다.
// 서버 계약(NB4-F1 어댑터): searchSourceDiscovery(query, scopes) → {candidates, unavailable}; addSourceDiscovery(ref) → {added, sourceId}.
//   - unavailable 이유 중 DISCOVERY_CONNECTOR_FAILED는 일시 실패라 결과 위 한 줄로 알리고, 나머지(연결 설정·준비·꺼짐·도구 불허)는
//     칩을 흐리게 하고 칩 아래에 이유를 적는다. 422 DISCOVERY_SCOPE_UNAVAILABLE이면 요청한 범위 칩을 모두 흐리게 한다.
//   - 추가는 사람이 고른 후보만, 한 번에 하나씩 보낸다. Idempotency-Key는 어댑터가 요청마다 새로 만든다(키를 넘기지 않는다).
//   - 403이면 남은 추가를 멈추고 체크칸·추가 버튼을 숨긴다(응답에 권한 값이 없어 canEdit 기본 true — 소스 묶음과 같은 방식).
//   - 추가가 끝나면 onAdded({sourceIds, scopeAdded})를 한 번 부른다. 셸은 소스 목록·승인 지식 칸을 다시 읽는다(N1-B07 교훈).
// 심층 조사(NB4-F2 어댑터): createResearch(query, scopes) → 스튜디오 보고서 산출물 접수 {output_id, status}. 소스 버전·구성 확인은 보내지 않는다.
//   - 시작하면 onResearchStarted({outputId})를 부른다. 셸은 스튜디오 목록을 다시 읽고 새 카드로 스크롤한다. 진행·실패·취소는 스튜디오 카드가 보인다.
//   - 조사 결과의 "사용한 자료"는 ResearchSourcesPanel(아래)이 보고서 보기 아래에 그린다. 추가 동작은 빠른 찾기와 같다(useCandidateAdder).
// 배치: 결과 목록은 정해진 높이의 창 안에서만 스크롤한다(source-discovery.css). 목록이 길어도 소스 칸·페이지가 늘어나지 않는다.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";
import { NOTEBOOK_MESSAGES } from "./notebook-messages.ko.js";
import "./source-discovery.css";

const SCOPES = ["knowledge", "documents"];
const MAX_QUERY = 500;
const FAILED = "DISCOVERY_CONNECTOR_FAILED";
const KEY = "notebook.source_discovery.";
const text = (key, params) => msg(`${KEY}${key}`, params);
// 서버 코드에 맞는 문구가 없으면 기본 문구를 쓴다. 코드 원문은 화면에 보이지 않는다.
const coded = (group, code) => (typeof code === "string" && Object.hasOwn(NOTEBOOK_MESSAGES, `${KEY}${group}.${code}`) ? text(`${group}.${code}`) : text(`${group}.default`));
const scopeLabel = (scope) => text(`scope.${scope}`);
const isForbidden = (error) => error?.status === 403 || error?.code === "FORBIDDEN";

const initialScopes = () => new Set(SCOPES);

/** 고른 후보를 하나씩 추가하는 상태(빠른 찾기 결과·조사 보고서의 사용한 자료 공통). reset()은 진행 중 추가 응답도 버린다. */
function useCandidateAdder({ studio, onAdded }) {
  const [selected, setSelected] = useState(() => new Set());
  const [rowState, setRowState] = useState(() => new Map()); // candidate_id → { state: adding|added|failed, added?, code? }
  const [adding, setAdding] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const seqRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const reset = useCallback(({ keepForbidden = true } = {}) => {
    seqRef.current += 1;
    setSelected(new Set()); setRowState(new Map()); setAdding(false);
    if (!keepForbidden) setForbidden(false);
  }, []);

  const toggle = (candidateId) => {
    if (adding) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(candidateId)) next.delete(candidateId); else next.add(candidateId);
      return next;
    });
  };

  const setRow = (candidateId, value) => setRowState((current) => {
    const next = new Map(current);
    if (value) next.set(candidateId, value); else next.delete(candidateId);
    return next;
  });

  const addSelected = async (candidates) => {
    if (adding || typeof studio?.addSourceDiscovery !== "function") return;
    const seq = seqRef.current;
    const queue = candidates.filter((candidate) => selected.has(candidate.candidate_id) && rowState.get(candidate.candidate_id)?.state !== "added");
    if (!queue.length) return;
    setAdding(true);
    setRowState((current) => {
      const next = new Map(current);
      for (const candidate of queue) next.set(candidate.candidate_id, { state: "adding" });
      return next;
    });
    const sourceIds = [];
    let scopeAdded = false;
    let stopped = false;
    for (const candidate of queue) {
      if (stopped) { setRow(candidate.candidate_id, null); continue; }
      try {
        const response = await studio.addSourceDiscovery(candidate.ref);
        if (seq !== seqRef.current || !mountedRef.current) return;
        if (response?.added === "source" && typeof response.sourceId === "string") sourceIds.push(response.sourceId);
        if (response?.added === "scope") scopeAdded = true;
        setRow(candidate.candidate_id, { state: "added", added: response?.added === "scope" ? "scope" : "source" });
      } catch (error) {
        if (seq !== seqRef.current || !mountedRef.current) return;
        if (isForbidden(error)) {
          stopped = true;
          setForbidden(true);
          setRow(candidate.candidate_id, null);
        } else {
          setRow(candidate.candidate_id, { state: "failed", code: error?.code ?? null });
        }
      }
    }
    setSelected(new Set());
    setAdding(false);
    if (sourceIds.length || scopeAdded) onAdded?.({ sourceIds, scopeAdded });
  };

  return { selected, rowState, adding, forbidden, toggle, addSelected, reset };
}

/** 후보 한 줄(빠른 찾기 결과·사용한 자료 공통). label은 조사 근거 라벨(S1…), cited는 보고서에서 인용했는지. */
function CandidateRow({ candidate, row, editable, adding, checked, onToggle, label = null, cited = false }) {
  const added = row?.state === "added";
  const checkable = editable && !added;
  return (
    <li className={`source-discovery__item${added ? " is-added" : ""}`} data-candidate-id={candidate.candidate_id}>
      {checkable ? <input type="checkbox" className="source-discovery__check" aria-label={text("select", { title: candidate.title })}
        checked={checked} disabled={adding} onChange={() => onToggle(candidate.candidate_id)} /> : null}
      <div className="source-discovery__body">
        <div className="source-discovery__meta">
          {label ? <span className="source-discovery__label" data-ref-label={label}>{label}</span> : null}
          <span className={`source-discovery__kind is-${candidate.kind === "document" ? "document" : "package"}`}>{text(`kind.${candidate.kind === "document" ? "document" : "knowledge_package"}`)}</span>
          <small>{candidate.origin_label}</small>
          {cited ? <span className="source-discovery__cited">{text("used.cited")}</span> : null}
        </div>
        <strong className="source-discovery__name">{candidate.title}</strong>
        {candidate.reason ? <p className="source-discovery__reason">{candidate.reason}</p> : null}
        {candidate.preview ? <p className="source-discovery__preview">{candidate.preview}</p> : null}
        <small className="source-discovery__action">{text(`action.${candidate.action === "add_source" ? "add_source" : "add_scope"}`)}</small>
        {row?.state === "adding" ? <p className="source-discovery__row-state is-adding" role="status">{text("adding")}</p> : null}
        {added ? <p className="source-discovery__row-state is-added" role="status"><b>{text("added")}</b> {text(`added.${row.added}`)}</p> : null}
        {row?.state === "failed" ? <p className="source-discovery__row-state is-failed" role="alert" data-discovery-row-error="">{coded("error.add", row.code)}</p> : null}
      </div>
    </li>
  );
}

export function SourceDiscoveryPanel({ studio, notebookId = null, canEdit = true, onAdded, onResearchStarted }) {
  const supported = typeof studio?.searchSourceDiscovery === "function";
  const canAdd = typeof studio?.addSourceDiscovery === "function";
  const canResearch = typeof studio?.createResearch === "function";
  const [mode, setMode] = useState("quick"); // quick | deep
  const [query, setQuery] = useState("");
  const [scopes, setScopes] = useState(initialScopes);
  const [phase, setPhase] = useState("idle"); // idle | searching | done | error | starting | started | start_error
  const [result, setResult] = useState(null); // { candidates, failedScopes }
  const [unavailable, setUnavailable] = useState(() => new Map());
  const [searchError, setSearchError] = useState(null);
  const [researchForbidden, setResearchForbidden] = useState(false);
  const adder = useCandidateAdder({ studio, onAdded });
  const { selected, rowState, adding, forbidden, reset: resetAdder } = adder;
  const seqRef = useRef(0);
  const mountedRef = useRef(true);
  const baseId = useId();

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  // 노트북(또는 어댑터)이 바뀌면 이전 노트북의 검색어·결과·권한 판단을 버린다. 늦게 오는 이전 응답도 버린다.
  useEffect(() => {
    seqRef.current += 1;
    setMode("quick"); setQuery(""); setScopes(initialScopes()); setPhase("idle"); setResult(null); setUnavailable(new Map()); setSearchError(null);
    setResearchForbidden(false);
    resetAdder({ keepForbidden: false });
  }, [studio, notebookId, resetAdder]);

  if (!supported) return null;

  const deep = mode === "deep";
  const editable = canEdit && canAdd && !forbidden;
  const trimmed = query.trim();
  const searching = phase === "searching";
  const starting = phase === "starting";
  const busy = searching || adding || starting;
  const researchAllowed = canEdit && canResearch && !researchForbidden;
  const canSearch = trimmed.length > 0 && scopes.size > 0 && !busy;
  const canStart = canSearch && researchAllowed;

  const toggleScope = (scope) => {
    if (busy) return;
    setScopes((current) => {
      const next = new Set(current);
      if (next.has(scope)) next.delete(scope); else next.add(scope);
      return next;
    });
  };

  // 방식을 바꾸면 이전 방식의 결과·안내는 닫는다(검색어·범위는 그대로 둔다).
  const switchMode = (next) => {
    if (busy || next === mode || (next === "deep" && !canResearch)) return;
    seqRef.current += 1;
    setMode(next); setPhase("idle"); setResult(null); setSearchError(null);
    resetAdder();
  };

  const search = async () => {
    if (!canSearch) return;
    const seq = ++seqRef.current;
    const requested = SCOPES.filter((scope) => scopes.has(scope));
    setPhase("searching"); setSearchError(null);
    resetAdder();
    try {
      const data = await studio.searchSourceDiscovery(trimmed, requested);
      if (seq !== seqRef.current || !mountedRef.current) return;
      const failedScopes = [];
      const off = new Map();
      for (const item of data.unavailable ?? []) {
        if (item.reason === FAILED) failedScopes.push(item.scope);
        else off.set(item.scope, item.reason);
      }
      setUnavailable(off);
      setResult({ candidates: Array.isArray(data.candidates) ? data.candidates : [], failedScopes });
      setPhase("done");
    } catch (error) {
      if (seq !== seqRef.current || !mountedRef.current) return;
      if (error?.code === "DISCOVERY_SCOPE_UNAVAILABLE") setUnavailable(new Map(requested.map((scope) => [scope, null])));
      setResult(null);
      setSearchError(error?.code ?? null);
      setPhase("error");
    }
  };

  const startResearch = async () => {
    if (!canStart) return;
    const seq = ++seqRef.current;
    const requested = SCOPES.filter((scope) => scopes.has(scope));
    setPhase("starting"); setSearchError(null);
    try {
      const receipt = await studio.createResearch(trimmed, requested);
      if (seq !== seqRef.current || !mountedRef.current) return;
      setPhase("started");
      if (typeof receipt?.output_id === "string") onResearchStarted?.({ outputId: receipt.output_id });
    } catch (error) {
      if (seq !== seqRef.current || !mountedRef.current) return;
      if (isForbidden(error)) setResearchForbidden(true);
      setSearchError(isForbidden(error) ? null : error?.code ?? null);
      setPhase(isForbidden(error) ? "idle" : "start_error");
    }
  };

  const submit = (event) => {
    event?.preventDefault?.();
    if (deep) void startResearch(); else void search();
  };

  const clear = () => {
    if (adding) return;
    seqRef.current += 1;
    setPhase("idle"); setResult(null); setSearchError(null);
    resetAdder();
  };

  const candidates = result?.candidates ?? [];
  const selectedCount = candidates.filter((candidate) => selected.has(candidate.candidate_id)).length;
  const reasonsId = `${baseId}-reasons`;
  const unavailableList = SCOPES.filter((scope) => unavailable.has(scope));
  let statusText = "";
  if (searching) statusText = text("searching");
  else if (phase === "done") statusText = candidates.length ? text("count", { count: candidates.length }) : text("empty");
  else if (phase === "started") statusText = text("deep.started");
  const submitLabel = deep ? (starting ? text("deep.starting") : text("deep.start")) : (searching ? text("searching_button") : text("search"));

  return (
    <section className="source-discovery" aria-label={text("title")} data-mode={mode}>
      <div className="source-discovery__modes" role="group" aria-label={text("mode_group")}>
        <button type="button" aria-pressed={deep ? "false" : "true"} disabled={busy} onClick={() => switchMode("quick")}>{text("mode.quick")}</button>
        <button type="button" aria-pressed={deep ? "true" : "false"} disabled={busy || !canResearch} title={canResearch ? undefined : text("mode.deep_unavailable")}
          onClick={() => switchMode("deep")}>{text("mode.deep")}</button>
      </div>
      <form className="source-discovery__form" aria-label={text("form")} onSubmit={submit}>
        <input type="search" className="source-discovery__input" aria-label={deep ? text("deep.query") : text("query")} placeholder={deep ? text("deep.placeholder") : text("placeholder")}
          maxLength={MAX_QUERY} value={query} onChange={(event) => setQuery(event.target.value)} disabled={adding || starting} />
        <button type="submit" className="source-discovery__submit" disabled={deep ? !canStart : !canSearch}>{submitLabel}</button>
      </form>
      <div className="source-discovery__scopes" role="group" aria-label={text("scope_group")}>
        {SCOPES.map((scope) => {
          const off = unavailable.has(scope);
          return (
            <button key={scope} type="button" data-scope={scope} aria-pressed={scopes.has(scope) ? "true" : "false"}
              className={`source-discovery__chip${off ? " is-unavailable" : ""}`} data-unavailable={off ? "true" : undefined}
              aria-describedby={off ? reasonsId : undefined} disabled={busy} onClick={() => toggleScope(scope)}>
              {scopeLabel(scope)}{off ? <small>{text("scope_unavailable_badge")}</small> : null}
            </button>
          );
        })}
      </div>
      {unavailableList.length ? <ul className="source-discovery__reasons" id={reasonsId}>
        {unavailableList.map((scope) => <li key={scope}>{text("scope_unavailable", { scope: scopeLabel(scope), reason: coded("reason", unavailable.get(scope)) })}</li>)}
      </ul> : null}
      {scopes.size === 0 ? <p className="source-discovery__hint">{text("scope_none")}</p> : null}
      {deep ? <p className="source-discovery__hint" data-discovery-deep-hint="">{text("deep.hint")}</p> : null}
      {deep && !researchAllowed && canResearch ? <p className="source-discovery__hint" role="note">{text("deep.view_only")}</p> : null}
      {statusText ? <p className="source-discovery__status" role="status" data-discovery-status="">{statusText}</p> : null}
      {phase === "error" ? <p className="source-discovery__alert" role="alert">{coded("error.search", searchError)}</p> : null}
      {phase === "start_error" ? <p className="source-discovery__alert" role="alert">{coded("deep.error", searchError)}</p> : null}
      {phase === "done" && result ? <div className="source-discovery__result">
        {result.failedScopes.length ? <p className="source-discovery__partial" role="status" data-discovery-partial="">
          {text("partial", { scopes: result.failedScopes.map(scopeLabel).join(text("scope_join")) })}</p> : null}
        {candidates.length ? <ul className="source-discovery__results" aria-label={text("results")}>
          {candidates.map((candidate) => <CandidateRow key={candidate.candidate_id} candidate={candidate} row={rowState.get(candidate.candidate_id)} editable={editable}
            adding={adding} checked={selected.has(candidate.candidate_id)} onToggle={adder.toggle} />)}
        </ul> : null}
      </div> : null}
      {phase === "done" && candidates.length && !editable ? <p className="source-discovery__hint" role="note">{text("view_only")}</p> : null}
      {phase === "done" || phase === "error" ? <div className="source-discovery__footer">
        {phase === "done" && candidates.length && editable ? <>
          <span className="source-discovery__count">{text("selected", { count: selectedCount })}</span>
          <button type="button" className="source-discovery__add" disabled={adding || selectedCount === 0} onClick={() => void adder.addSelected(candidates)}>{text("add")}</button>
        </> : null}
        <button type="button" className="source-discovery__clear" disabled={adding} onClick={clear}>{text("clear")}</button>
      </div> : null}
    </section>
  );
}

/**
 * 조사 보고서 아래 "사용한 자료"(NB4-U2). research는 어댑터 researchOf(=studioResearchOf) 결과 {query, subQuestions, candidates, unavailable, toolCalls}.
 * candidates[i]의 라벨은 S{i+1}(보고서 근거 번호). citedRefs는 보고서 본문에서 실제로 인용한 라벨 목록.
 * 추가는 빠른 찾기와 같은 경로(addSourceDiscovery → onAdded({sourceIds, scopeAdded}) → 셸이 소스 목록·승인 지식 칸을 다시 읽음).
 * 배치: 목록은 스튜디오 보기 창(.studio-detail__body) 안에서 함께 스크롤하고, 추가 줄은 목록을 보는 동안 창 아래에 붙는다.
 */
export function ResearchSourcesPanel({ studio, research, citedRefs = [], canEdit = true, onAdded }) {
  const adder = useCandidateAdder({ studio, onAdded });
  const candidates = Array.isArray(research?.candidates) ? research.candidates : [];
  const cited = new Set(citedRefs);
  const editable = canEdit && typeof studio?.addSourceDiscovery === "function" && !adder.forbidden;
  const selectedCount = candidates.filter((candidate) => adder.selected.has(candidate.candidate_id)).length;
  const unavailable = Array.isArray(research?.unavailable) ? research.unavailable.filter((item) => SCOPES.includes(item.scope)) : [];
  return (
    <section className="source-discovery source-discovery--used" aria-label={text("used.title")}>
      <h3 className="source-discovery__heading">{text("used.heading", { count: candidates.length })}</h3>
      {candidates.length ? <p className="source-discovery__hint">{text("used.help")}</p> : <p className="source-discovery__hint">{text("used.empty")}</p>}
      {unavailable.length ? <ul className="source-discovery__reasons" data-research-unavailable="">
        {unavailable.map((item) => <li key={item.scope}>{text("used.unavailable", { scope: scopeLabel(item.scope), reason: coded("reason", item.reason) })}</li>)}
      </ul> : null}
      {candidates.length ? <ul className="source-discovery__results source-discovery__results--used" aria-label={text("used.list")}>
        {candidates.map((candidate, index) => <CandidateRow key={candidate.candidate_id} candidate={candidate} row={adder.rowState.get(candidate.candidate_id)} editable={editable}
          adding={adder.adding} checked={adder.selected.has(candidate.candidate_id)} onToggle={adder.toggle} label={`S${index + 1}`} cited={cited.has(`S${index + 1}`)} />)}
      </ul> : null}
      {candidates.length && adder.forbidden ? <p className="source-discovery__hint" role="note">{text("used.view_only")}</p> : null}
      {candidates.length && editable ? <div className="source-discovery__footer source-discovery__footer--sticky">
        <span className="source-discovery__count">{text("selected", { count: selectedCount })}</span>
        <button type="button" className="source-discovery__add" disabled={adder.adding || selectedCount === 0} onClick={() => void adder.addSelected(candidates)}>{text("add")}</button>
      </div> : null}
    </section>
  );
}
