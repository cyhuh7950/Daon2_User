"use client";

import { useEffect, useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";

// 내려받기 추가 인증 정책 화면(WO-F1B, ST-T27). api: { get(), set(requireStepUp) }. 조직 step-up 목록은 되돌릴 수 없으므로 켠 뒤에는 변경 칸을 잠근다.
export function ExportPolicyPane({ api }) {
  const [state, setState] = useState({ status: "loading", enabled: false, draft: false, notice: null, error: null });
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    api.get().then((policy) => { if (alive.current) setState({ status: "ready", enabled: policy.require_step_up, draft: policy.require_step_up, notice: null, error: null }); })
      .catch((error) => { if (alive.current) setState({ status: error?.status === 403 ? "forbidden" : "error", enabled: false, draft: false, notice: null, error: msg("expol.failed") }); });
    return () => { alive.current = false; };
  }, [api]);
  const save = async () => {
    try {
      const policy = await api.set(state.draft);
      setState({ status: "ready", enabled: policy.require_step_up, draft: policy.require_step_up, notice: msg("expol.saved"), error: null });
    } catch {
      setState((current) => ({ ...current, error: msg("expol.failed"), notice: null }));
    }
  };
  return <section className="connectors-pane" aria-labelledby="expol-title">
    <header className="connectors-header"><h2 id="expol-title">{msg("expol.title")}</h2></header>
    <p>{msg("expol.help")}</p>
    {state.status === "loading" ? <p role="status">{msg("expol.loading")}</p> : null}
    {state.status === "forbidden" ? <p role="alert">{msg("expol.forbidden")}</p> : null}
    {state.status === "ready" ? <>
      <label><input type="checkbox" aria-label={msg("expol.field")} checked={state.draft} disabled={state.enabled}
        onChange={() => setState((current) => ({ ...current, draft: !current.draft, notice: null }))} /> {msg("expol.field")}{state.enabled ? ` — ${msg("expol.on")}` : ""}</label>
      <button type="button" disabled={state.enabled || !state.draft} onClick={() => void save()}>{msg("expol.save")}</button>
    </> : null}
    {state.notice ? <p role="status">{state.notice}</p> : null}
    {state.error && state.status !== "forbidden" ? <p role="alert">{state.error}</p> : null}
  </section>;
}

export default ExportPolicyPane;
