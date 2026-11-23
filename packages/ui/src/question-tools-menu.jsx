"use client";

// 질문 도구 켜고 끄기(NB2-U1, WO-N1 N1-2, 결정 D-02 웹 제외). 문구는 notebook-messages.ko.js의 notebook.question_tools.* 키만 쓴다.
// 입력창 아래 모델 선택 옆 "도구" 버튼(켠 도구 수 배지) → 목록 팝오버에서 도구마다 켜고 끈다. 누르면 바로 저장하고 바꾼 도구만 보낸다.
// 값의 정본은 서버다: 열 때마다 studio.getQuestionTools()로 읽고, 저장 응답으로 화면을 맞춘다. 저장에 실패하면 이전 값으로 되돌린다.
// studio: 노트북 범위가 묶인 어댑터. getQuestionTools({signal}) → {tools}, saveQuestionTools(enabled) → {tools}. 둘 중 하나라도 없으면 그리지 않는다.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";
import "./question-tools.css";

const REASONS = new Set(["NO_SCOPE_SELECTED", "CONNECTOR_NOT_READY", "CONNECTOR_DISABLED"]);
const reasonText = (reason) => (REASONS.has(reason) ? msg(`notebook.question_tools.reason.${reason.toLowerCase()}`) : null);
const isOn = (tool) => tool.available === true && tool.enabled === true;

export function QuestionToolsMenu({ studio, disabled = false }) {
  const supported = typeof studio?.getQuestionTools === "function" && typeof studio?.saveQuestionTools === "function";
  const [state, setState] = useState({ status: "loading", tools: [], saving: false, error: null });
  const [open, setOpen] = useState(false);
  const [reload, setReload] = useState(0);
  const mounted = useRef(true);
  const buttonRef = useRef(null);
  const rootRef = useRef(null);
  const baseId = useId();
  const popoverId = `${baseId}-tools`;

  useEffect(() => {
    mounted.current = true;
    if (!supported) return () => { mounted.current = false; };
    const controller = new AbortController();
    setState({ status: "loading", tools: [], saving: false, error: null });
    studio.getQuestionTools({ signal: controller.signal })
      .then((data) => { if (mounted.current && !controller.signal.aborted) setState({ status: "ready", tools: data?.tools ?? [], saving: false, error: null }); })
      .catch(() => { if (mounted.current && !controller.signal.aborted) setState({ status: "error", tools: [], saving: false, error: null }); });
    return () => { mounted.current = false; controller.abort(); };
  }, [studio, supported, reload]);

  // 노트북이 바뀌면 목록을 닫는다.
  useEffect(() => { setOpen(false); }, [studio]);

  // 목록 밖을 누르면 닫는다.
  useEffect(() => {
    if (!open) return undefined;
    const doc = rootRef.current?.ownerDocument;
    const onPointer = (event) => { if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false); };
    doc?.addEventListener?.("mousedown", onPointer);
    return () => doc?.removeEventListener?.("mousedown", onPointer);
  }, [open]);

  const close = useCallback(() => { setOpen(false); buttonRef.current?.focus?.(); }, []);

  const toggle = async (tool) => {
    if (!tool.available || state.saving) return;
    const next = !tool.enabled;
    const previous = state.tools;
    // 누르면 바로 바뀐 값을 보이고, 저장이 끝날 때까지 다른 스위치는 잠근다.
    setState((value) => ({ ...value, saving: true, error: null, tools: value.tools.map((item) => (item.id === tool.id ? { ...item, enabled: next } : item)) }));
    try {
      const data = await studio.saveQuestionTools({ [tool.id]: next });
      if (mounted.current) setState({ status: "ready", tools: data?.tools ?? previous, saving: false, error: null });
    } catch {
      if (mounted.current) setState((value) => ({ ...value, tools: previous, saving: false, error: "save_failed" }));
    }
  };

  if (!supported) return null;
  const loading = state.status === "loading";
  const count = state.tools.filter(isOn).length;
  const allOff = state.status === "ready" && count === 0;

  return <div className="question-tools" ref={rootRef}>
    <button type="button" ref={buttonRef} className="question-tools__button" aria-haspopup="true" aria-expanded={open ? "true" : "false"} aria-controls={popoverId}
      aria-busy={loading ? "true" : undefined} aria-label={loading ? msg("notebook.question_tools.button") : msg("notebook.question_tools.button.label", { count })}
      disabled={loading || state.status === "error"} onClick={() => setOpen((value) => !value)}>
      <span>{msg("notebook.question_tools.button")}</span>
      {loading ? null : <span className="question-tools__count" data-question-tools-count="" aria-hidden="true">{count}</span>}
    </button>
    {loading ? <small className="question-tools__status" role="status">{msg("notebook.question_tools.loading")}</small> : null}
    {state.status === "error" ? <p className="question-tools__alert" role="alert">
      {msg("notebook.question_tools.load_failed")}
      <button type="button" className="question-tools__retry" onClick={() => setReload((value) => value + 1)}>{msg("notebook.question_tools.retry")}</button>
    </p> : null}
    {allOff ? <small className="question-tools__status question-tools__sources-only">{msg("notebook.question_tools.sources_only")}</small> : null}
    {state.error && !open ? <p className="question-tools__alert" role="alert">{msg(`notebook.question_tools.${state.error}`)}</p> : null}
    {open && state.status === "ready" ? <div className="question-tools__popover" id={popoverId} role="group" aria-label={msg("notebook.question_tools.list")}
      onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault?.(); event.stopPropagation?.(); close(); } }}>
      <strong className="question-tools__title">{msg("notebook.question_tools.list")}</strong>
      {state.tools.length ? <ul className="question-tools__list">
        {state.tools.map((tool) => {
          const reason = tool.available ? null : reasonText(tool.reason);
          const reasonId = `${baseId}-reason-${tool.id}`;
          return <li key={tool.id} className="question-tools__item" data-available={tool.available ? "true" : "false"}>
            <label className="question-tools__label">
              <span className="question-tools__name">{tool.label}</span>
              <input type="checkbox" role="switch" className="question-tools__switch" checked={isOn(tool)} aria-checked={isOn(tool) ? "true" : "false"}
                disabled={disabled || !tool.available || state.saving} aria-describedby={reason ? reasonId : undefined} onChange={() => { void toggle(tool); }} />
            </label>
            {reason ? <small className="question-tools__reason" id={reasonId}>{reason}</small> : null}
          </li>;
        })}
      </ul> : <p className="question-tools__hint">{msg("notebook.question_tools.empty")}</p>}
      {state.saving ? <small className="question-tools__hint" role="status">{msg("notebook.question_tools.saving")}</small> : null}
      {state.error ? <p className="question-tools__alert" role="alert">{msg(`notebook.question_tools.${state.error}`)}</p> : null}
      <p className="question-tools__hint">{msg("notebook.question_tools.hint")}</p>
    </div> : null}
  </div>;
}
