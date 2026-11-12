import { useEffect, useRef, useState } from "react";

// 노트북 왼쪽 패널의 Daon 승인 지식(WO-K2). 패널에는 선택한 업무 패키지만, 제목을 누르면 팝업에 승인된 전체 목록을 보여 준다.

const ERROR_TEXT = {
  KNOWLEDGE_CONNECTOR_NOT_CONFIGURED: "Daon2-RAG 연결이 준비되지 않았습니다. 관리자에게 지식 연결 확인을 요청해 주세요.",
  KNOWLEDGE_SERVER_UNAVAILABLE: "지식 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  CONNECTOR_EGRESS_DENIED: "외부 전송 정책에서 허용되지 않은 서버입니다. 관리자에게 문의해 주세요.",
  KNOWLEDGE_SCOPE_SELECTION_INVALID: "업무 패키지는 최대 8개까지 선택할 수 있습니다.",
  KNOWLEDGE_SCOPE_NOT_AVAILABLE: "더 이상 사용할 수 없는 업무 패키지가 있습니다. 목록을 다시 열어 주세요.",
};
const safeMessage = (error) => ERROR_TEXT[error?.code] ?? "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
const keyOf = (projectId, workPackageId) => JSON.stringify([projectId, workPackageId]);

// WO-K6: 패키지별로 쓸 수 있는 지식 종류를 한 줄로 보인다. Daon2 연결이 없으면(none) 문서만 보인다.
const KIND_LABEL = [["ontology", "온톨로지"], ["ruleset", "규칙"], ["approved", "승인 자산"]];
export function knowledgeKindsText(status) {
  if (!status?.kinds) return "";
  const kinds = status.kinds;
  const parts = [kinds.rag === "ready" ? `문서 ${status.document_count}건` : "문서 없음"];
  parts.push(...KIND_LABEL.filter(([key]) => kinds[key] === "ready").map(([, label]) => label));
  const notReady = KIND_LABEL.filter(([key]) => kinds[key] === "not_ready").map(([, label]) => label);
  if (notReady.length) parts.push(`${notReady.join("·")} 준비 안 됨`);
  const unknown = KIND_LABEL.filter(([key]) => kinds[key] === "unknown").map(([, label]) => label);
  if (unknown.length) parts.push(`${unknown.join("·")} 확인 못 함`);
  if (kinds.graphrag === "unknown" && (kinds.ontology === "ready" || kinds.ontology === "empty")) parts.push("GraphRAG 질문 때 확인");
  return parts.join(" · ");
}

export function DaonKnowledgeScopeSection({ adapter, onCountChange }) {
  const [items, setItems] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [statusByKey, setStatusByKey] = useState({});
  const [dialog, setDialog] = useState(null); // { status, projects, chosen: string[], error, pending }
  const dialogRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoadError(null);
    adapter.getNotebookKnowledgeScopes({ signal: controller.signal }).then((data) => setItems(data.items), (error) => {
      if (!controller.signal.aborted) setLoadError(safeMessage(error));
    });
    return () => controller.abort();
  }, [adapter]);

  useEffect(() => { onCountChange?.(items.length); }, [items.length, onCountChange]);

  // 상태는 보조 정보라 실패해도 알리지 않고 비워 둔다.
  const itemsKey = items.map((item) => keyOf(item.project_id, item.work_package_id)).join("|");
  useEffect(() => {
    if (!itemsKey || typeof adapter.getNotebookKnowledgeStatus !== "function") { setStatusByKey({}); return undefined; }
    const controller = new AbortController();
    adapter.getNotebookKnowledgeStatus({ signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setStatusByKey(Object.fromEntries(data.items.map((row) => [keyOf(row.project_id, row.work_package_id), row])));
    }, () => { if (!controller.signal.aborted) setStatusByKey({}); });
    return () => controller.abort();
  }, [adapter, itemsKey]);

  const opened = dialog !== null;
  useEffect(() => {
    if (opened) dialogRef.current?.focus?.();
  }, [opened]);

  const open = async () => {
    const chosen = items.map((item) => keyOf(item.project_id, item.work_package_id));
    setDialog({ status: "loading", projects: [], chosen, error: null, pending: false });
    try {
      const data = await adapter.listDaonKnowledgeScopes();
      setDialog((current) => current && { ...current, status: data.projects.length ? "ready" : "empty", projects: data.projects });
    } catch (error) {
      setDialog((current) => current && { ...current, status: "error", error: safeMessage(error) });
    }
  };

  const toggle = (key) => setDialog((current) => ({ ...current, chosen: current.chosen.includes(key) ? current.chosen.filter((item) => item !== key) : [...current.chosen, key] }));

  const apply = async () => {
    const chosen = new Set(dialog.chosen);
    const selection = dialog.projects.flatMap((project) => project.work_packages
      .filter((item) => chosen.has(keyOf(project.project_id, item.work_package_id)))
      .map((item) => ({ project_id: project.project_id, work_package_id: item.work_package_id })));
    setDialog((current) => ({ ...current, pending: true, error: null }));
    try {
      const data = await adapter.saveNotebookKnowledgeScopes(selection);
      setItems(data.items);
      setDialog(null);
    } catch (error) {
      setDialog((current) => current && { ...current, pending: false, error: safeMessage(error) });
    }
  };

  return <section className="source-group" aria-labelledby="approved-knowledge-title">
    <div className="source-group-heading">
      <h3 id="approved-knowledge-title"><button type="button" className="daon-scope-open" onClick={() => void open()}>Daon 승인 지식</button></h3>
      <span>{items.length}</span>
    </div>
    <ul className="source-list knowledge-list" aria-label="선택한 Daon 승인 지식">
      {items.map((item) => <li className="source-list-row knowledge-list-row" key={keyOf(item.project_id, item.work_package_id)}>
        <div className="daon-scope-row"><span className="source-file-icon knowledge-icon" aria-hidden="true">K</span>
          <span className="source-row-copy"><strong>{item.work_package_name}</strong><small>{item.project_name}</small>
            {knowledgeKindsText(statusByKey[keyOf(item.project_id, item.work_package_id)]) ? <small className="daon-scope-kinds">{knowledgeKindsText(statusByKey[keyOf(item.project_id, item.work_package_id)])}</small> : null}</span></div>
      </li>)}
    </ul>
    {loadError ? <div className="inline-alert compact" role="alert">{loadError}</div> : null}
    {dialog ? <div className="daon-scope-overlay">
      <section ref={dialogRef} tabIndex={-1} className="connector-dialog daon-scope-dialog" role="dialog" aria-modal="true" aria-label="Daon 승인 지식 선택"
        onKeyDown={(event) => { if (event.key === "Escape" && !dialog.pending) setDialog(null); }}>
        <h3>Daon 승인 지식 선택</h3>
        {dialog.status === "loading" ? <p role="status">불러오는 중…</p> : null}
        {dialog.status === "empty" ? <p>승인된 업무 패키지가 없습니다.</p> : null}
        <div className="daon-scope-projects">
          {dialog.projects.map((project) => <fieldset key={project.project_id}><legend>{project.project_name}</legend>
            {project.work_packages.map((item) => {
              const key = keyOf(project.project_id, item.work_package_id);
              return <label key={key} className="connector-tool"><input type="checkbox" aria-label={`${project.project_name} ${item.work_package_name} 선택`}
                checked={dialog.chosen.includes(key)} onChange={() => toggle(key)} />{item.work_package_name}</label>;
            })}
          </fieldset>)}
        </div>
        {dialog.error ? <p role="alert" className="inline-alert">{dialog.error}</p> : null}
        <div className="connector-dialog-actions">
          <button type="button" disabled={dialog.pending} onClick={() => setDialog(null)}>취소</button>
          <button type="button" disabled={dialog.pending || dialog.status !== "ready"} onClick={() => void apply()}>적용</button>
        </div>
      </section>
    </div> : null}
  </section>;
}

export default DaonKnowledgeScopeSection;
