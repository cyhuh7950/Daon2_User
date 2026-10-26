import { useCallback, useEffect, useRef, useState } from "react";

// 지식 연결(MCP Connector) 관리 화면(WO-M0 T-M0-09). api는 apps/web/lib/knowledge-connectors-api.js 와 같은 모양을 주입한다.
// 규칙: 서버 주소·토큰은 화면에 남기지 않는다(등록 후 토큰 입력칸 비움). 기본 주소·예시는 두지 않는다.

const KIND_LABEL = { daon2_rag: "Daon2-RAG", daon2: "Daon2", law: "법령" };
const KIND_TOOLS = {
  daon2_rag: ["search_document_evidence", "get_document_evidence", "list_documents", "get_document_outline", "read_document_section", "get_document_version_status"],
  daon2: ["ontology_search_concepts", "ontology_get_concept", "ruleset_list", "ruleset_get", "ruleset_evaluate", "approved_knowledge_search"],
  law: ["search_law", "get_law_text"],
};
const STATUS_LABEL = { verified: "연결됨", registered: "확인 전", unverified: "확인 전", unavailable: "연결 안 됨", failed: "확인 실패", disabled: "사용 안 함" };
const ERROR_TEXT = {
  CONNECTOR_ENDPOINT_INVALID: "주소 형식을 확인해 주세요.",
  CONNECTOR_ENDPOINT_PRIVATE_DENIED: "사설 주소는 이 환경에서 연결할 수 없습니다.",
  CONNECTOR_NAME_INVALID: "이름을 1~120자로 입력해 주세요.",
  CONNECTOR_KIND_INVALID: "지원하지 않는 종류입니다.",
  CONNECTOR_TOOL_NOT_ALLOWED: "선택한 도구를 이 종류에서는 쓸 수 없습니다.",
  CONNECTOR_SCOPE_INVALID: "허용 컬렉션 값을 확인해 주세요.",
  CONNECTOR_CREDENTIAL_INVALID: "인증 토큰 형식을 확인해 주세요.",
  CONNECTOR_VERSION_CONFLICT: "다른 곳에서 먼저 수정되었습니다. 새로고침 후 다시 시도해 주세요.",
  VIRTUAL_CONNECTOR_FORBIDDEN_IN_PRODUCTION: "가상 서버는 운영 환경에서 연결할 수 없습니다.",
  KNOWLEDGE_SERVER_UNAVAILABLE: "지식 서버에 연결하지 못했습니다.",
  CONNECTOR_LIMITS_INVALID: "한도 값이 허용 범위를 벗어났습니다.",
};
const safeMessage = (error) => ERROR_TEXT[error?.code] ?? "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
const stamp = (value) => (value ? String(value).replace("T", " ").slice(0, 16) : "—");

const emptyForm = () => ({ kind: "daon2_rag", name: "", endpointUrl: "", token: "", tools: [], scopes: [{ projectId: "", workPackageId: "" }] });

function RegisterDialog({ onSubmit, onCancel, pending, error }) {
  const [form, setForm] = useState(emptyForm);
  const set = (patch) => setForm((current) => ({ ...current, ...patch }));
  const toggleTool = (tool) => set({ tools: form.tools.includes(tool) ? form.tools.filter((item) => item !== tool) : [...form.tools, tool] });
  const setScope = (index, patch) => set({ scopes: form.scopes.map((scope, position) => (position === index ? { ...scope, ...patch } : scope)) });
  const valid = form.name.trim() && form.endpointUrl.trim();
  return <section className="connector-dialog" role="dialog" aria-modal="true" aria-label="지식 연결 등록">
    <h3>지식 연결 등록</h3>
    <label>종류<select aria-label="종류" value={form.kind} onChange={(event) => set({ kind: event.target.value, tools: [] })}>
      {Object.entries(KIND_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label>이름<input type="text" aria-label="이름" maxLength={120} value={form.name} onChange={(event) => set({ name: event.target.value })} /></label>
    <label>서버 주소<input type="url" aria-label="서버 주소" autoComplete="off" value={form.endpointUrl} onChange={(event) => set({ endpointUrl: event.target.value })} /></label>
    <label>인증 토큰<input type="password" aria-label="인증 토큰" autoComplete="new-password" maxLength={8192} value={form.token} onChange={(event) => set({ token: event.target.value })} /></label>
    <fieldset><legend>허용 도구 (선택하지 않으면 종류의 기본 도구를 모두 허용)</legend>
      {KIND_TOOLS[form.kind].map((tool) => <label key={tool} className="connector-tool"><input type="checkbox" checked={form.tools.includes(tool)} onChange={() => toggleTool(tool)} />{tool}</label>)}
    </fieldset>
    <fieldset><legend>허용 컬렉션 (프로젝트·작업 패키지)</legend>
      {form.scopes.map((scope, index) => <div className="connector-scope" key={index}>
        <input type="text" aria-label={`프로젝트 ${index + 1}`} value={scope.projectId} onChange={(event) => setScope(index, { projectId: event.target.value })} />
        <input type="text" aria-label={`작업 패키지 ${index + 1}`} value={scope.workPackageId} onChange={(event) => setScope(index, { workPackageId: event.target.value })} />
        <button type="button" aria-label={`컬렉션 ${index + 1} 삭제`} onClick={() => set({ scopes: form.scopes.filter((_, position) => position !== index) })}>삭제</button>
      </div>)}
      <button type="button" onClick={() => set({ scopes: [...form.scopes, { projectId: "", workPackageId: "" }] })}>컬렉션 추가</button>
    </fieldset>
    {error ? <p role="alert" className="inline-alert">{error}</p> : null}
    <div className="connector-dialog-actions">
      <button type="button" onClick={onCancel} disabled={pending}>취소</button>
      <button type="button" disabled={!valid || pending} onClick={() => onSubmit({
        kind: form.kind, name: form.name, endpointUrl: form.endpointUrl, token: form.token, allowedTools: form.tools,
        allowedScopes: form.scopes.filter((scope) => scope.projectId.trim() && scope.workPackageId.trim()).map((scope) => ({ projectId: scope.projectId.trim(), workPackageId: scope.workPackageId.trim() })),
      })}>등록</button>
    </div>
  </section>;
}

// 호출 한도(F4-02): 비워 두면 서버 기본값을 쓴다.
const LIMIT_FIELDS = [
  ["max_concurrent", "동시 호출 수", 1, 8, "기본 4"],
  ["timeout_seconds", "호출 제한 시간(초)", 1, 60, "기본 25"],
  ["max_response_bytes", "응답 최대 크기(바이트)", 4096, 4194304, "기본 1048576"],
  ["calls_per_minute", "분당 호출 수", 1, 600, "기본 30"],
];

function LimitsDialog({ connector, onSubmit, onCancel, pending, error }) {
  const [values, setValues] = useState(() => Object.fromEntries(LIMIT_FIELDS.map(([key]) => [key, connector.limits?.[key] ?? ""])));
  const submit = () => onSubmit(Object.fromEntries(LIMIT_FIELDS.filter(([key]) => String(values[key]).trim() !== "").map(([key]) => [key, Number(values[key])])));
  return <section className="connector-dialog" role="dialog" aria-modal="true" aria-label="호출 한도">
    <h3>{connector.name} 호출 한도</h3>
    {LIMIT_FIELDS.map(([key, label, low, high, hint]) => <label key={key}>{label}
      <input type="number" aria-label={label} min={low} max={high} placeholder={hint} value={values[key]}
        onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} /></label>)}
    {error ? <p role="alert" className="inline-alert">{error}</p> : null}
    <div className="connector-dialog-actions">
      <button type="button" onClick={onCancel} disabled={pending}>취소</button>
      <button type="button" disabled={pending} onClick={submit}>저장</button>
    </div>
  </section>;
}

export function KnowledgeConnectorsPane({ api }) {
  const [state, setState] = useState({ status: "loading", connectors: [], error: null });
  const [dialog, setDialog] = useState(null); // { type: "register" | "disconnect", connector?, pending, error }
  const [busy, setBusy] = useState(null); // connector_id (연결 확인 진행)
  const [notice, setNotice] = useState(null);
  const alive = useRef(true);

  const reload = useCallback(async () => {
    try {
      const connectors = await api.list();
      if (alive.current) setState({ status: connectors.length ? "ready" : "empty", connectors, error: null });
    } catch (error) {
      if (alive.current) setState({ status: error?.status === 403 ? "forbidden" : "error", connectors: [], error: safeMessage(error) });
    }
  }, [api]);

  useEffect(() => {
    alive.current = true;
    void reload();
    return () => { alive.current = false; };
  }, [reload]);

  const register = async (input) => {
    setDialog((current) => ({ ...current, pending: true, error: null }));
    try {
      await api.register(input);
      setDialog(null);
      setNotice("지식 연결을 등록했습니다. 연결 확인을 실행해 주세요.");
      await reload();
    } catch (error) {
      setDialog((current) => (current ? { ...current, pending: false, error: safeMessage(error) } : current));
    }
  };

  const verify = async (connector) => {
    setBusy(connector.connector_id);
    setNotice(null);
    try {
      const result = await api.verify(connector.connector_id);
      setNotice(result.status === "verified" ? `${connector.name}: 연결을 확인했습니다.` : `${connector.name}: 연결을 확인하지 못했습니다.`);
    } catch (error) {
      setNotice(`${connector.name}: ${safeMessage(error)}`);
    } finally {
      setBusy(null);
      await reload();
    }
  };

  const saveLimits = async (connector, limits) => {
    setDialog((current) => ({ ...current, pending: true, error: null }));
    try {
      await api.updateLimits(connector.connector_id, connector.version, limits);
      setDialog(null);
      setNotice(`${connector.name}: 호출 한도를 저장했습니다.`);
      await reload();
    } catch (error) {
      setDialog((current) => (current ? { ...current, pending: false, error: safeMessage(error) } : current));
    }
  };

  const disconnect = async (connector) => {
    setDialog((current) => ({ ...current, pending: true, error: null }));
    try {
      await api.disconnect(connector.connector_id);
      setDialog(null);
      setNotice(`${connector.name} 연결을 해제했습니다.`);
      await reload();
    } catch (error) {
      setDialog((current) => (current ? { ...current, pending: false, error: safeMessage(error) } : current));
    }
  };

  return <section className="connectors-pane" aria-labelledby="connectors-title">
    <header className="connectors-header">
      <h2 id="connectors-title">지식 연결</h2>
      <button type="button" onClick={() => setDialog({ type: "register", pending: false, error: null })} disabled={state.status === "forbidden"}>연결 추가</button>
    </header>
    {notice ? <p role="status" className="context-selection-status">{notice}</p> : null}
    {state.status === "loading" ? <p role="status">불러오는 중…</p> : null}
    {state.status === "forbidden" ? <p role="alert">관리자만 지식 연결을 관리할 수 있습니다.</p> : null}
    {state.status === "error" ? <p role="alert">{state.error}</p> : null}
    {state.status === "empty" ? <p>등록된 지식 연결이 없습니다. “연결 추가”로 Daon2-RAG·Daon2 서버를 등록하세요.</p> : null}
    {state.status === "ready" ? <table className="connectors-table">
      <thead><tr><th scope="col">이름</th><th scope="col">종류</th><th scope="col">상태</th><th scope="col">마지막 확인</th><th scope="col">작업</th></tr></thead>
      <tbody>{state.connectors.map((connector) => <tr key={connector.connector_id}>
        <td>{connector.name}{connector.virtual ? <span className="connector-badge" title="시험용 가상 서버">가상</span> : null}</td>
        <td>{KIND_LABEL[connector.kind] ?? connector.kind}</td>
        <td><span className={`connector-status status-${connector.status}`}>{STATUS_LABEL[connector.status] ?? connector.status}</span>{connector.error_code ? <small> ({connector.error_code})</small> : null}</td>
        <td>{stamp(connector.last_checked_at)}</td>
        <td>
          <button type="button" aria-label={`${connector.name} 연결 확인`} disabled={busy === connector.connector_id} onClick={() => void verify(connector)}>
            {busy === connector.connector_id ? "확인 중…" : "연결 확인"}</button>
          <button type="button" aria-label={`${connector.name} 호출 한도`} onClick={() => setDialog({ type: "limits", connector, pending: false, error: null })}>한도</button>
          <button type="button" aria-label={`${connector.name} 해제`} onClick={() => setDialog({ type: "disconnect", connector, pending: false, error: null })}>해제</button>
        </td>
      </tr>)}</tbody>
    </table> : null}
    {dialog?.type === "register" ? <RegisterDialog pending={dialog.pending} error={dialog.error} onCancel={() => setDialog(null)} onSubmit={register} /> : null}
    {dialog?.type === "limits" ? <LimitsDialog connector={dialog.connector} pending={dialog.pending} error={dialog.error} onCancel={() => setDialog(null)} onSubmit={(limits) => void saveLimits(dialog.connector, limits)} /> : null}
    {dialog?.type === "disconnect" ? <section className="connector-dialog" role="dialog" aria-modal="true" aria-label="지식 연결 해제">
      <p>“{dialog.connector.name}” 연결을 해제할까요? 이 연결로 만든 산출물의 저장된 근거 스냅샷은 유지됩니다.</p>
      {dialog.error ? <p role="alert" className="inline-alert">{dialog.error}</p> : null}
      <button type="button" disabled={dialog.pending} onClick={() => setDialog(null)}>취소</button>
      <button type="button" disabled={dialog.pending} onClick={() => void disconnect(dialog.connector)}>해제 확인</button>
    </section> : null}
  </section>;
}

export default KnowledgeConnectorsPane;
