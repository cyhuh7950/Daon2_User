"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { StudioIcon } from "./studio-icon.js";
import { msg, studioErrorMessage } from "./studio-messages.ko.js";
import "./studio-icon.css";
import "./studio-panel.css";

const STATE_LABEL = { collecting: msg("authoring.state.collecting"), analyzing: msg("authoring.state.analyzing"), review: msg("authoring.state.review"), generating: msg("authoring.state.generating"), completed: msg("authoring.state.completed"), failed: msg("authoring.state.failed"), cancelled: msg("authoring.state.cancelled") };
const STEPS = ["collecting", "analyzing", "review", "generating", "completed"];
const STATUS_LABEL = { covered: msg("authoring.coverage.covered"), partial: msg("authoring.coverage.partial"), missing: msg("authoring.coverage.missing") };
const POLL_MS = 3000;
const DOCUMENT_GROUP_LABEL = { proposal: msg("authoring.group.proposal"), insurance_terms: msg("authoring.group.insurance_terms"), contract: msg("authoring.group.contract") };
const DIFF_LABEL = { unchanged: msg("authoring.diff.unchanged"), modified: msg("authoring.diff.modified"), new: msg("authoring.diff.new") };
const RELATION_LABEL = { related: msg("authoring.relation.related"), possible_conflict: msg("authoring.relation.possible_conflict") };
const PLACEHOLDER = msg("authoring.placeholder");

function StepBar({ state }) {
  const current = Math.max(0, STEPS.indexOf(state === "failed" || state === "cancelled" ? "generating" : state));
  return <ol className="studio-row" aria-label={msg("authoring.steps")} style={{ listStyle: "none", padding: 0 }}>
    {STEPS.map((step, index) => <li key={step} aria-current={index === current ? "step" : undefined}
      className="studio-chip" style={{ fontWeight: index === current ? 700 : 400, opacity: index <= current ? 1 : 0.55 }}>{index + 1}. {STATE_LABEL[step]}</li>)}
  </ol>;
}

function Questions({ session, sources, adapter, onSubmit, busy }) {
  const [values, setValues] = useState({});
  const [connectors, setConnectors] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [picked, setPicked] = useState([]);
  const [scopeIndex, setScopeIndex] = useState(0);
  const [connectorId, setConnectorId] = useState("");
  const scopeChosenByUser = useRef(false);
  const knowledgeQuestion = session.pending_questions.find((q) => q.kind === "knowledge_ref");
  const documentType = knowledgeQuestion?.document_type ?? "proposal";
  const needsKnowledge = session.pending_questions.some((q) => q.kind === "knowledge_ref");
  useEffect(() => {
    if (!needsKnowledge) return undefined;
    let alive = true;
    adapter.listConnectors().then((list) => { if (alive) { const rag = list.filter((c) => c.kind === "daon2_rag"); setConnectors(rag); if (rag[0]) setConnectorId(rag[0].connector_id); } })
      .catch(() => { if (alive) setConnectors([]); });
    return () => { alive = false; };
  }, [adapter, needsKnowledge]);
  const connector = (connectors ?? []).find((c) => c.connector_id === connectorId);
  const scope = connector?.allowed_scopes?.[scopeIndex];
  useEffect(() => {
    if (!connector || !scope) { setDocuments([]); return undefined; }
    let alive = true;
    adapter.listDocuments(connector.connector_id, { projectId: scope.project_id, workPackageId: scope.work_package_id, documentType })
      .then((list) => {
        if (!alive) return;
        // 사용자가 컬렉션을 고르지 않았다면, 해당 문서 종류가 있는 첫 컬렉션으로 자동 이동한다.
        if (list.length === 0 && !scopeChosenByUser.current && scopeIndex + 1 < (connector.allowed_scopes ?? []).length) { setScopeIndex(scopeIndex + 1); return; }
        setDocuments(list);
      }).catch(() => { if (alive) setDocuments([]); });
    return () => { alive = false; };
  }, [adapter, connector, scope, documentType, scopeIndex]);
  const submit = (event, skipRemaining = false) => {
    event.preventDefault();
    const answers = [];
    for (const q of session.pending_questions) {
      if (q.kind === "source_ref" && values[q.key]) answers.push({ key: q.key, source_version_id: values[q.key] });
      else if (q.kind === "knowledge_ref" && picked.length && connector && scope) {
        answers.push({ key: q.key, knowledge_ref: { connector_id: connector.connector_id, project_id: scope.project_id, work_package_id: scope.work_package_id, document_ids: picked } });
      } else if ((q.kind === "text" || q.kind === "structured") && values[q.key]?.trim()) answers.push({ key: q.key, value: values[q.key] });
      else if (q.kind === "choice" && values[q.key]) answers.push({ key: q.key, value: values[q.key] });
    }
    onSubmit(answers, skipRemaining);
  };
  const onlyOptional = session.pending_questions.every((q) => !q.required);
  return <form onSubmit={submit} aria-label={msg("authoring.questions")}>
    {session.pending_questions.map((q) => <fieldset key={q.key} style={{ border: 0, padding: 0, margin: "12px 0" }}>
      <legend><strong>{q.question}</strong>{q.required ? <span aria-label={msg("authoring.required")}> *</span> : <span> {msg("authoring.optional")}</span>}</legend>
      {q.kind === "source_ref" && <div role="radiogroup" aria-label={q.question}>{sources.filter((s) => s.ready).map((s) => <label key={s.sourceVersionId} style={{ display: "block" }}>
        <input type="radio" name={q.key} checked={values[q.key] === s.sourceVersionId} onChange={() => setValues((v) => ({ ...v, [q.key]: s.sourceVersionId }))} /> {s.filename ?? s.sourceId}</label>)}
        {sources.every((s) => !s.ready) && <p>{msg("authoring.no_ready_source")}</p>}</div>}
      {q.kind === "knowledge_ref" && <div>
        {connectors === null ? <p role="status">…</p> : connectors.length === 0 ? <p>{msg("authoring.no_connectors")}</p> : <>
          <label>{msg("authoring.connector")} <select value={connectorId} onChange={(event) => { setConnectorId(event.target.value); setScopeIndex(0); setPicked([]); }}>
            {connectors.map((c) => <option key={c.connector_id} value={c.connector_id}>{c.name}{c.virtual ? ` ${msg("authoring.virtual")}` : ""}</option>)}</select></label>
          {(connector?.allowed_scopes ?? []).length > 1 && <label> {msg("authoring.scope")} <select value={scopeIndex} onChange={(event) => { scopeChosenByUser.current = true; setScopeIndex(Number(event.target.value)); setPicked([]); }}>
            {connector.allowed_scopes.map((s, i) => <option key={i} value={i}>{s.project_id} / {s.work_package_id}</option>)}</select></label>}
          <div role="group" aria-label={DOCUMENT_GROUP_LABEL[documentType] ?? msg("authoring.group.default")}>{documents.map((d) => <label key={d.document_id} style={{ display: "block" }}>
            <input type="checkbox" checked={picked.includes(d.document_id)} onChange={() => setPicked((list) => list.includes(d.document_id) ? list.filter((x) => x !== d.document_id) : [...list, d.document_id].slice(0, 10))} /> {d.title}</label>)}
            {documents.length === 0 && <p>{msg("authoring.no_documents")}</p>}</div></>}</div>}
      {(q.kind === "text" || q.kind === "structured") && <textarea rows={3} maxLength={4000} value={values[q.key] ?? ""} aria-label={q.question} style={{ width: "100%" }}
        onChange={(event) => setValues((v) => ({ ...v, [q.key]: event.target.value }))} />}
      {q.kind === "choice" && <select value={values[q.key] ?? ""} onChange={(event) => setValues((v) => ({ ...v, [q.key]: event.target.value }))}>
        <option value="">{msg("authoring.choose")}</option>{q.choices.map((c) => <option key={c} value={c}>{c}</option>)}</select>}
    </fieldset>)}
    <div className="studio-row">
      <button type="submit" className="studio-btn studio-btn--primary" disabled={busy}>{msg("authoring.next")}</button>
      {onlyOptional && <button type="button" className="studio-btn" disabled={busy} onClick={(event) => submit(event, true)}>{msg("authoring.skip")}</button>}
    </div>
  </form>;
}

function Review({ session, onConfirm, busy }) {
  const [requirements, setRequirements] = useState(session.requirements);
  const [sections, setSections] = useState(session.plan?.sections ?? []);
  const [formats, setFormats] = useState(session.output_formats ?? ["docx"]);
  const baseOnly = session.analysis === "base_document";
  const choices = session.output_choices ?? ["docx", "pptx"];
  const move = (index, delta) => setSections((list) => { const next = list.slice(); const j = index + delta; if (j < 0 || j >= next.length) return list; [next[index], next[j]] = [next[j], next[index]]; return next; });
  return <div>
    {baseOnly ? <p><small>{msg("authoring.review.base_only")}</small></p> : <>
    <h3>{msg("authoring.review.requirements", { count: requirements.length })}</h3>
    <p><small>{msg("authoring.review.requirements_help")}</small></p>
    <div style={{ overflowX: "auto" }}><table className="studio-table"><thead><tr><th>ID</th><th>{msg("authoring.review.col.requirement")}</th><th>{msg("authoring.review.col.mandatory")}</th><th><span className="sr-only">{msg("authoring.review.col.delete")}</span></th></tr></thead>
      <tbody>{requirements.map((r, i) => <tr key={r.id}><td>{r.id}</td>
        <td><input aria-label={msg("authoring.review.req.content", { id: r.id })} value={r.text} maxLength={1000} style={{ width: "100%" }} onChange={(event) => setRequirements((list) => list.map((x, j) => j === i ? { ...x, text: event.target.value } : x))} /></td>
        <td><input type="checkbox" aria-label={msg("authoring.review.req.mandatory", { id: r.id })} checked={r.mandatory} onChange={() => setRequirements((list) => list.map((x, j) => j === i ? { ...x, mandatory: !x.mandatory } : x))} /></td>
        <td><button type="button" className="studio-icon-button" aria-label={msg("authoring.review.req.delete", { id: r.id })} onClick={() => setRequirements((list) => list.filter((_, j) => j !== i))}><StudioIcon name="delete" size={18} /></button></td></tr>)}</tbody></table></div>
    <button type="button" className="studio-btn" onClick={() => setRequirements((list) => [...list, { id: `REQ-${String(list.length + 1).padStart(3, "0")}-N`, text: msg("authoring.review.req.new"), mandatory: true, category: "", refs: [] }])}>{msg("authoring.review.req.add")}</button></>}
    <h3>{msg("authoring.review.plan")}</h3>
    <ol>{sections.map((s, i) => <li key={s.key}><strong>{s.title}</strong> {baseOnly ? null : <small>{msg("authoring.review.plan.requirements", { count: s.requirement_ids.length })}</small>}
      <button type="button" className="studio-icon-button" aria-label={msg("authoring.review.plan.up", { title: s.title })} disabled={i === 0} onClick={() => move(i, -1)}><StudioIcon name="chevron_down" size={16} style={{ transform: "rotate(180deg)" }} /></button>
      <button type="button" className="studio-icon-button" aria-label={msg("authoring.review.plan.down", { title: s.title })} disabled={i === sections.length - 1} onClick={() => move(i, 1)}><StudioIcon name="chevron_down" size={16} /></button>
      <button type="button" className="studio-icon-button" aria-label={msg("authoring.review.plan.delete", { title: s.title })} disabled={sections.length <= 1} onClick={() => setSections((list) => list.filter((_, j) => j !== i))}><StudioIcon name="delete" size={16} /></button></li>)}</ol>
    <fieldset style={{ border: 0, padding: 0 }}><legend>{msg("authoring.review.formats")}</legend>{choices.map((f) => <label key={f} style={{ marginRight: 12 }}>
      <input type="checkbox" checked={formats.includes(f)} onChange={() => setFormats((list) => list.includes(f) ? list.filter((x) => x !== f) : [...list, f])} /> {f.toUpperCase()}</label>)}</fieldset>
    <div className="studio-row"><button type="button" className="studio-btn studio-btn--primary" disabled={busy || (!baseOnly && requirements.length === 0) || formats.length === 0}
      onClick={() => onConfirm({ requirements, planSections: sections, outputFormats: formats })}>{msg("authoring.review.confirm")}</button></div>
  </div>;
}

const tabEntry = (id) => [id, msg(`authoring.tab.${id}`)];
const RESULT_TABS = {
  proposal: [tabEntry("body"), tabEntry("coverage"), tabEntry("checks"), tabEntry("open")],
  terms: [tabEntry("body"), tabEntry("diff"), tabEntry("checks"), tabEntry("open")],
  contract: [tabEntry("body"), tabEntry("law"), tabEntry("checks"), tabEntry("open")],
};

function Result({ document, formats = ["docx", "pptx"], onDownload }) {
  const [tab, setTab] = useState("body");
  const style = document.style ?? "proposal";
  const tabs = RESULT_TABS[style] ?? RESULT_TABS.proposal;
  const lawCheck = (document.checks ?? []).find((c) => c.id === "law_crosscheck");
  return <div>
    <p className="studio-chip" role="note">{document.notice}</p>
    <div className="studio-row" role="tablist" aria-label={msg("authoring.result")}>{tabs.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={tab === id} className="studio-btn" onClick={() => setTab(id)}>{label}</button>)}</div>
    {tab === "body" && document.sections.map((s) => <section key={s.key}><h3>{s.title}</h3>{s.paragraphs.map((p, i) => <p key={i}>{p.text.split(PLACEHOLDER).flatMap((part, j, arr) => j < arr.length - 1 ? [part, <mark key={j}>{PLACEHOLDER}</mark>] : [part])}
      {p.refs.length ? <small> {p.refs.map((r) => `[${r}]`).join("")}</small> : <span className="studio-warning">{msg("authoring.new_sentence")}</span>}</p>)}</section>)}
    {tab === "diff" && document.sections.map((s) => <section key={s.key}><h3>{s.title}</h3>
      {s.paragraphs.map((p, i) => <p key={i}>{(p.diff?.sentences ?? [{ text: p.text, tag: "new" }]).map((sentence, j) => <span key={j} data-diff={sentence.tag} title={sentence.base ? msg("authoring.diff.base", { text: sentence.base }) : undefined}>
        <mark className="studio-chip" aria-label={DIFF_LABEL[sentence.tag]}>{DIFF_LABEL[sentence.tag]}</mark> {sentence.text} </span>)}</p>)}
      {s.delete_suggested?.length ? <div role="note"><strong>{msg("authoring.delete_suggested")}</strong><ul>{s.delete_suggested.map((text, k) => <li key={k}><del>{text}</del></li>)}</ul></div> : null}</section>)}
    {tab === "law" && (lawCheck?.rows?.length ? <div><p role="note">{lawCheck.notice}</p><table className="studio-table"><thead><tr><th>{msg("authoring.law.col.clause")}</th><th>{msg("authoring.law.col.law")}</th><th>{msg("authoring.law.col.judgement")}</th><th>{msg("authoring.law.col.memo")}</th></tr></thead>
      <tbody>{lawCheck.rows.map((r, i) => <tr key={i}><td>{r.section_title}</td><td>{r.law}</td><td>{RELATION_LABEL[r.relation] ?? r.relation}</td><td>{r.note}</td></tr>)}</tbody></table></div>
      : <p>{msg("authoring.law.none", { reason: lawCheck?.reason ? `(${lawCheck.reason})` : "" })}</p>)}
    {tab === "coverage" && <table className="studio-table"><thead><tr><th>ID</th><th>{msg("authoring.review.col.requirement")}</th><th>{msg("authoring.coverage.col.state")}</th></tr></thead><tbody>{document.coverage.map((c) => <tr key={c.requirement_id}><td>{c.requirement_id}</td><td>{c.text}</td><td>{STATUS_LABEL[c.status]}</td></tr>)}</tbody></table>}
    {tab === "checks" && document.checks.map((c) => <section key={c.id}><h3>{c.title}</h3>{c.status === "skipped" ? <p>{msg("authoring.check.skipped", { reason: c.reason })}</p>
      : c.results ? <ul>{c.results.map((r) => <li key={r.rule_id}>{r.status === "pass" ? msg("authoring.rule.pass") : r.status === "fail" ? msg("authoring.rule.fail") : msg("authoring.rule.review")} — {r.message}</li>)}</ul>
        : c.id === "evidence_integrity" ? <><p>{msg("authoring.check.evidence", { verified: c.summary?.verified ?? 0, unverified: c.summary?.unverified ?? 0 })}</p>{(c.items ?? []).length > 0 && <ul>{c.items.map((item, i) => <li key={i}><span className="studio-badge">{msg("authoring.badge.unverified")}</span> {item.section_title} — {item.text}</li>)}</ul>}</>
        : c.id === "term_consistency" ? <><p>{msg("authoring.check.terms", { mixed: c.summary?.mixed ?? 0, synonym_only: c.summary?.synonym_only ?? 0 })}</p>{(c.items ?? []).length > 0 && <ul>{c.items.map((item, i) => <li key={i}>{item.kind === "mixed" ? msg("authoring.term.mixed") : msg("authoring.term.review")} — {msg("authoring.term.item", { found: item.found, count: item.count, preferred: item.preferred })}</li>)}</ul>}</>
        : c.id === "terms_change_summary" ? <p>{msg("authoring.check.change_summary", { unchanged: c.summary?.unchanged ?? 0, modified: c.summary?.modified ?? 0, new: c.summary?.new ?? 0, delete_suggested: c.summary?.delete_suggested ?? 0 })}</p>
        : c.id === "law_crosscheck" ? <p>{msg("authoring.check.law_summary", { related: c.summary?.related ?? 0, conflict: c.summary?.possible_conflict ?? 0 })} <small>{msg("authoring.check.law_hint")}</small></p>
        : <p>{msg("authoring.check.coverage_summary", { covered: c.summary?.covered ?? 0, partial: c.summary?.partial ?? 0, missing: c.summary?.missing ?? 0 })}</p>}</section>)}
    {tab === "open" && <ul>{document.open_items.map((o, i) => <li key={i}>{o}</li>)}</ul>}
    <div className="studio-row">{[...formats.filter((f) => f !== "pdf"), "pdf"].map((f) => <button key={f} type="button" className="studio-btn" onClick={() => onDownload(f)}>{msg("authoring.download", { format: f.toUpperCase() })}</button>)}</div>
  </div>;
}

/** 작성 마법사: 세션을 만들거나 이어서 열고, 상태에 맞는 화면을 보여 준다. authoring = adapter.studioV2.authoring */
export function AuthoringWizard({ studio, sources = [], outputId = null, onClose, onChanged }) {
  const authoring = studio.authoring;
  const [session, setSession] = useState(null);
  const [id, setId] = useState(outputId);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [templates, setTemplates] = useState(null);
  const timer = useRef(null);
  const fail = useCallback((e) => { setError(e?.code ?? "STUDIO_REQUEST_FAILED"); setBusy(false); }, []);

  useEffect(() => { if (id) return undefined; let alive = true; authoring.listTemplates().then((t) => { if (alive) setTemplates(t); }).catch(fail); return () => { alive = false; }; }, [authoring, id, fail]);

  const load = useCallback(async () => { if (!id) return; try { setSession(await authoring.getSession(id)); } catch (e) { fail(e); } }, [authoring, id, fail]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!session) return undefined;
    const waiting = (session.state === "analyzing" || session.state === "generating") || session.job_status === "queued" || session.job_status === "generating";
    if (!waiting) return undefined;
    timer.current = setTimeout(load, POLL_MS);
    return () => clearTimeout(timer.current);
  }, [session, load]);

  const start = async (templateId) => {
    setBusy(true);
    try { const created = await authoring.createSession({ templateId }); setId(created.output_id); setSession(created); onChanged?.(); } catch (e) { fail(e); }
    setBusy(false);
  };
  const submit = async (answers, skipRemaining) => {
    setBusy(true); setError(null);
    try { await authoring.answer(id, { expectedRevision: session.revision_no, answers, skipRemaining }); await load(); onChanged?.(); } catch (e) { fail(e); }
    setBusy(false);
  };
  const confirm = async (edit) => {
    setBusy(true); setError(null);
    try { await authoring.review(id, { expectedRevision: session.revision_no, ...edit, confirm: true }); await load(); onChanged?.(); } catch (e) { fail(e); }
    setBusy(false);
  };
  const download = async (format) => {
    try {
      const { bytes, contentType, disposition } = await studio.downloadExport(id, format);
      const url = globalThis.URL.createObjectURL(new Blob([bytes], { type: contentType }));
      const match = /filename\*=UTF-8''([^;]+)/u.exec(disposition);
      const a = globalThis.document.createElement("a");
      a.href = url; a.download = match ? decodeURIComponent(match[1]) : `authored.${format}`;
      globalThis.document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => globalThis.URL.revokeObjectURL(url), 60_000);
    } catch (e) { fail(e); }
  };

  return <section className="studio-detail" aria-label={msg("authoring.title")}>
    <div className="studio-detail__bar">
      <button type="button" className="studio-icon-button" aria-label={msg("authoring.back")} onClick={onClose}><StudioIcon name="chevron_right" size={20} style={{ transform: "rotate(180deg)" }} /></button>
      <h2 className="studio-detail__title">{msg("authoring.title")}</h2>
    </div>
    {error && <p className="studio-alert" role="alert">{studioErrorMessage(error)}</p>}
    <div className="studio-detail__body">
      {!id && (templates === null ? <p role="status">…</p> : <div role="list" aria-label={msg("authoring.templates")}>{templates.map((t) => <div key={t.template_id} role="listitem" className="studio-card">
        <div className="studio-card__main"><span className="studio-card__text"><span className="studio-card__title">{t.title}</span><span className="studio-card__subtitle">{t.description}</span></span></div>
        <button type="button" className="studio-btn studio-btn--primary" disabled={busy} onClick={() => start(t.template_id)}>{msg("authoring.start")}</button></div>)}</div>)}
      {id && !session && !error && <p role="status">…</p>}
      {session && <>
        <StepBar state={session.state} />
        {session.state === "collecting" && <Questions session={session} sources={sources} adapter={authoring} busy={busy} onSubmit={submit} />}
        {(session.state === "analyzing" || session.state === "generating") && <p role="status"><StudioIcon name="spinner" size={18} /> {session.state === "analyzing" ? (session.analysis === "base_document" ? msg("authoring.wait.base") : msg("authoring.wait.rfp")) : msg("authoring.wait.generating")}</p>}
        {session.state === "review" && <Review session={session} busy={busy} onConfirm={confirm} />}
        {session.state === "completed" && session.document && <Result document={session.document} formats={session.output_choices ?? ["docx", "pptx"]} onDownload={download} />}
        {session.state === "failed" && <p role="alert">{studioErrorMessage(session.error_code)}</p>}
      </>}
    </div>
  </section>;
}

export default AuthoringWizard;
