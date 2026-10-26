"use client";

import { useEffect, useRef, useState } from "react";

// 입력창 위의 모델·추론 수준 선택. 승인된 Provider의 정확한 모델만 보이고, 지원이 확인되지 않은 추론 수준은 비활성이다.
const LEVEL_LABELS = Object.freeze({ none: "없음", low: "낮음", medium: "보통", high: "높음" });
const ERRORS = Object.freeze({
  SELECTED_MODEL_UNAVAILABLE: "선택한 모델을 지금 사용할 수 없습니다. 다른 모델을 고르거나 기본 모델로 되돌려 주세요.",
  REASONING_LEVEL_UNSUPPORTED: "이 모델에서 지원이 확인되지 않은 추론 수준입니다.",
  MODEL_SELECTION_UNAVAILABLE: "모델 선택을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
});
const SEPARATOR = "\u0001";

export function ModelSelectionBar({ studio, disabled = false }) {
  const [state, setState] = useState({ data: null, error: null, saving: false });
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    if (typeof studio?.getModelSelection !== "function") return () => { mounted.current = false; };
    const controller = new AbortController();
    studio.getModelSelection({ signal: controller.signal })
      .then((data) => { if (mounted.current) setState({ data, error: null, saving: false }); })
      .catch(() => { if (mounted.current && !controller.signal.aborted) setState({ data: null, error: "MODEL_SELECTION_UNAVAILABLE", saving: false }); });
    return () => { mounted.current = false; controller.abort(); };
  }, [studio]);
  if (typeof studio?.saveModelSelection !== "function" || !state.data) {
    return state.error ? <p className="inline-alert compact" role="alert">{ERRORS[state.error]}</p> : null;
  }
  const { available, selection, levels } = state.data;
  const current = selection ? available.find((item) => item.connection_id === selection.connection_id && item.model_id === selection.model_id) : null;
  const selectedValue = selection ? `${selection.connection_id}${SEPARATOR}${selection.model_id}` : "";
  const supported = new Set(current?.reasoning_levels ?? []);
  const save = async (connectionId, modelId, reasoningLevel) => {
    setState((value) => ({ ...value, saving: true, error: null }));
    try {
      const data = await studio.saveModelSelection({ connectionId, modelId, reasoningLevel });
      if (mounted.current) setState({ data, error: null, saving: false });
    } catch (error) {
      if (mounted.current) setState((value) => ({ ...value, saving: false, error: ERRORS[error?.code] ? error.code : "MODEL_SELECTION_UNAVAILABLE" }));
    }
  };
  const onModel = (event) => {
    const value = event.currentTarget.value;
    if (!value) { void save(null, null, null); return; }
    const [connectionId, modelId] = value.split(SEPARATOR);
    // 모델을 바꾸면 추론 수준은 새 모델이 지원을 확인받은 경우에만 유지한다.
    const target = available.find((item) => item.connection_id === connectionId && item.model_id === modelId);
    const keep = selection?.reasoning_level && target?.reasoning_levels.includes(selection.reasoning_level) ? selection.reasoning_level : null;
    void save(connectionId, modelId, keep);
  };
  const onLevel = (event) => {
    if (!current) return;
    void save(current.connection_id, current.model_id, event.currentTarget.value || null);
  };
  const busy = disabled || state.saving;
  return <div className="model-selection-bar" role="group" aria-label="모델 선택">
    <label><span className="sr-only">모델</span>
      <select aria-label="모델" value={selectedValue} disabled={busy} onChange={onModel}>
        <option value="">기본 모델{state.data.default ? ` (${state.data.default.model_id})` : ""}</option>
        {available.map((item) => <option key={`${item.connection_id}${SEPARATOR}${item.model_id}`} value={`${item.connection_id}${SEPARATOR}${item.model_id}`}>{item.display_name} · {item.model_id}</option>)}
      </select></label>
    <label><span className="sr-only">추론 수준</span>
      <select aria-label="추론 수준" value={selection?.reasoning_level ?? ""} disabled={busy || !current} onChange={onLevel}
        title={current ? undefined : "모델을 선택하면 지원이 확인된 추론 수준을 고를 수 있습니다."}>
        <option value="">모델 기본</option>
        {levels.filter((level) => !current?.reasoning_checked || supported.has(level)).map((level) => <option key={level} value={level} disabled={!supported.has(level)}>{LEVEL_LABELS[level] ?? level}{supported.has(level) ? "" : " (확인 전)"}</option>)}
      </select></label>
    {state.saving ? <small role="status">모델과 추론 수준을 확인하는 중…</small> : null}
    {state.error ? <p className="inline-alert compact" role="alert">{ERRORS[state.error]}</p> : null}
  </div>;
}
