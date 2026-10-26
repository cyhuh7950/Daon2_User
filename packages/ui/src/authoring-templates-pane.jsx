"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";
import { SAMPLE_TEMPLATE } from "./authoring-template-sample.js";

// 조직 작성 템플릿 관리 화면(WO-A3 S5-05). api는 apps/web/lib/authoring-templates-api.js 와 같은 모양을 주입한다.

const errorText = (error) => {
  switch (error?.code) {
    case "AUTHORING_TEMPLATE_INVALID": return error.reason ? msg("authtpl.error.invalid", { reason: error.reason }) : msg("authtpl.error.invalid_plain");
    case "AUTHORING_TEMPLATE_EXISTS": return msg("authtpl.error.exists");
    case "AUTHORING_TEMPLATE_VERSION_CONFLICT": return msg("authtpl.error.conflict");
    default: return msg("authtpl.error.generic");
  }
};

function EditorDialog({ initial, editing, pending, error, onSubmit, onCancel }) {
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2));
  const [localError, setLocalError] = useState(null);
  const parsed = (() => {
    try {
      const value = JSON.parse(text);
      return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
    } catch {
      return null;
    }
  })();
  const patch = (key, value) => { if (parsed) setText(JSON.stringify({ ...parsed, [key]: value }, null, 2)); };
  const submit = () => {
    if (!parsed) { setLocalError(msg("authtpl.error.json")); return; }
    setLocalError(null);
    onSubmit(parsed);
  };
  const readFile = async (event) => {
    const file = event.target.files?.[0];
    if (file) setText(await file.text());
  };
  const label = editing ? msg("authtpl.dialog.edit") : msg("authtpl.dialog.new");
  return <section className="connector-dialog" role="dialog" aria-modal="true" aria-label={label}>
    <h3>{label}</h3>
    <label>{msg("authtpl.field.title")}<input type="text" aria-label={msg("authtpl.field.title")} maxLength={120} value={parsed?.title ?? ""} disabled={!parsed} onChange={(event) => patch("title", event.target.value)} /></label>
    <label>{msg("authtpl.field.description")}<input type="text" aria-label={msg("authtpl.field.description")} maxLength={500} value={parsed?.description ?? ""} disabled={!parsed} onChange={(event) => patch("description", event.target.value)} /></label>
    <label>{msg("authtpl.field.json")}<textarea aria-label={msg("authtpl.field.json")} rows={16} spellCheck={false} value={text} style={{ width: "100%", fontFamily: "monospace" }}
      onChange={(event) => { setText(event.target.value); setLocalError(null); }} /></label>
    <label>{msg("authtpl.file")}<input type="file" aria-label={msg("authtpl.file")} accept="application/json,.json" onChange={readFile} /></label>
    {!editing ? <button type="button" onClick={() => setText(JSON.stringify(SAMPLE_TEMPLATE, null, 2))}>{msg("authtpl.sample")}</button> : null}
    {localError || error ? <p role="alert" className="inline-alert">{localError ?? error}</p> : null}
    <div className="connector-dialog-actions">
      <button type="button" onClick={onCancel} disabled={pending}>{msg("authtpl.cancel")}</button>
      <button type="button" disabled={pending} onClick={submit}>{msg("authtpl.save")}</button>
    </div>
  </section>;
}

function defaultDownload(filename, text) {
  const url = globalThis.URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const anchor = globalThis.document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  globalThis.document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => globalThis.URL.revokeObjectURL(url), 60_000);
}

export function AuthoringTemplatesPane({ api, download = defaultDownload }) {
  const [state, setState] = useState({ status: "loading", templates: [], error: null });
  const [dialog, setDialog] = useState(null); // { template?, initial, pending, error }
  const [notice, setNotice] = useState(null);
  const alive = useRef(true);

  const reload = useCallback(async () => {
    try {
      const templates = await api.list();
      if (alive.current) setState({ status: templates.length ? "ready" : "empty", templates, error: null });
    } catch (error) {
      if (alive.current) setState({ status: error?.status === 403 ? "forbidden" : "error", templates: [], error: errorText(error) });
    }
  }, [api]);

  useEffect(() => {
    alive.current = true;
    void reload();
    return () => { alive.current = false; };
  }, [reload]);

  const save = async (definition) => {
    setDialog((current) => ({ ...current, pending: true, error: null }));
    try {
      const saved = dialog.template ? await api.update(dialog.template.template_id, dialog.template.version, definition) : await api.register(definition);
      setDialog(null);
      setNotice(msg("authtpl.saved", { title: saved.title, version: saved.version }));
      await reload();
    } catch (error) {
      setDialog((current) => (current ? { ...current, pending: false, error: errorText(error) } : current));
    }
  };

  const edit = async (template) => {
    try {
      const initial = await api.export(template.template_id);
      setDialog({ template, initial, pending: false, error: null });
    } catch (error) {
      setNotice(`${template.title}: ${errorText(error)}`);
    }
  };

  const toggle = async (template) => {
    try {
      await api.setStatus(template.template_id, template.status !== "active");
      await reload();
    } catch (error) {
      setNotice(`${template.title}: ${errorText(error)}`);
    }
  };

  const exportJson = async (template) => {
    try {
      download(`${template.template_id}.json`, JSON.stringify(await api.export(template.template_id), null, 2));
    } catch (error) {
      setNotice(`${template.title}: ${errorText(error)}`);
    }
  };

  return <section className="connectors-pane" aria-labelledby="authtpl-title">
    <header className="connectors-header">
      <h2 id="authtpl-title">{msg("authtpl.title")}</h2>
      <button type="button" disabled={state.status === "forbidden"} onClick={() => setDialog({ initial: SAMPLE_TEMPLATE, pending: false, error: null })}>{msg("authtpl.new")}</button>
    </header>
    <p>{msg("authtpl.help")}</p>
    {notice ? <p role="status" className="context-selection-status">{notice}</p> : null}
    {state.status === "loading" ? <p role="status">{msg("authtpl.loading")}</p> : null}
    {state.status === "forbidden" ? <p role="alert">{msg("authtpl.forbidden")}</p> : null}
    {state.status === "error" ? <p role="alert">{state.error}</p> : null}
    {state.status === "empty" ? <p>{msg("authtpl.empty")}</p> : null}
    {state.status === "ready" ? <table className="connectors-table">
      <thead><tr><th scope="col">{msg("authtpl.col.title")}</th><th scope="col">{msg("authtpl.col.id")}</th><th scope="col">{msg("authtpl.col.version")}</th>
        <th scope="col">{msg("authtpl.col.status")}</th><th scope="col">{msg("authtpl.col.sections")}</th><th scope="col">{msg("authtpl.col.actions")}</th></tr></thead>
      <tbody>{state.templates.map((template) => <tr key={template.template_id}>
        <td>{template.title}</td><td>{template.template_id}</td><td>{template.version}</td>
        <td>{template.status === "active" ? msg("authtpl.status.active") : msg("authtpl.status.disabled")}</td><td>{template.sections}</td>
        <td>
          <button type="button" aria-label={msg("authtpl.edit.label", { title: template.title })} onClick={() => void edit(template)}>{msg("authtpl.edit")}</button>
          <button type="button" aria-label={msg(template.status === "active" ? "authtpl.disable.label" : "authtpl.enable.label", { title: template.title })} onClick={() => void toggle(template)}>
            {template.status === "active" ? msg("authtpl.disable") : msg("authtpl.enable")}</button>
          <button type="button" aria-label={msg("authtpl.export.label", { title: template.title })} onClick={() => void exportJson(template)}>{msg("authtpl.export")}</button>
        </td>
      </tr>)}</tbody>
    </table> : null}
    {dialog ? <EditorDialog initial={dialog.initial} editing={!!dialog.template} pending={dialog.pending} error={dialog.error} onCancel={() => setDialog(null)} onSubmit={(definition) => void save(definition)} /> : null}
  </section>;
}

export default AuthoringTemplatesPane;
