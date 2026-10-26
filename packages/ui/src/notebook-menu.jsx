"use client";

import { useEffect, useRef, useState } from "react";
import { secureUuid } from "./secure-uuid.js";
import { focusInitialModalControl, trapModalTab } from "./workspace-interaction.js";
import { msg } from "./studio-messages.ko.js";

// 상단 바의 노트북 도구(S3-01~S3-03): "+ 노트북 만들기", 공유, ⋮ 메뉴, 맞춤설정 입력 화면.
// 복사·채팅 기록 삭제·공유는 서버 기능(F3-02/F3-03)이 준비되기 전까지 "준비 중"으로 표시한다. 애널리틱스는 1차에서 표시하지 않는다.

export const CUSTOMIZATION_MAX = 4000;

export function CustomizationDialog({ studio, onClose }) {
  const [state, setState] = useState({ loading: true, text: "", etag: null, saving: false, error: null, saved: false });
  const areaRef = useRef(null);
  const dialogRef = useRef(null);
  useEffect(() => {
    let alive = true;
    studio.getCustomization().then((data) => {
      if (alive) setState((s) => ({ ...s, loading: false, text: data.instruction ?? "", etag: data.etag ?? null }));
    }).catch((error) => { if (alive) setState((s) => ({ ...s, loading: false, error: error?.code ?? "STUDIO_REQUEST_FAILED" })); });
    return () => { alive = false; };
  }, [studio]);
  useEffect(() => { if (!state.loading) areaRef.current?.focus(); else focusInitialModalControl(dialogRef.current); }, [state.loading]);
  const save = async () => {
    setState((s) => ({ ...s, saving: true, error: null, saved: false }));
    try {
      const data = await studio.saveCustomization(state.text.trim(), { etag: state.etag });
      setState((s) => ({ ...s, saving: false, saved: true, text: data.instruction ?? "", etag: data.etag ?? s.etag }));
    } catch (error) {
      setState((s) => ({ ...s, saving: false, error: error?.code ?? "STUDIO_REQUEST_FAILED" }));
    }
  };
  const conflict = state.error === "STUDIO_VERSION_CONFLICT";
  return <div className="workspace-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className="workspace-modal notebook-customization" role="dialog" aria-modal="true" aria-labelledby="notebook-customization-title"
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } else trapModalTab(dialogRef.current, event); }}>
      <header className="workspace-modal-header"><div><span className="section-kicker">NOTEBOOK</span><h2 id="notebook-customization-title">{msg("notebook.customization.title")}</h2></div>
        <button type="button" onClick={onClose} aria-label={msg("notebook.customization.close")}>{msg("studio.dialog.close")}</button></header>
      <div className="workspace-modal-content">
        <p>{msg("notebook.customization.help")}</p>
        <label>{msg("notebook.customization.field")}<textarea ref={areaRef} aria-label={msg("notebook.customization.field")} rows={8} maxLength={CUSTOMIZATION_MAX} disabled={state.loading || state.saving}
          value={state.text} placeholder={msg("notebook.customization.placeholder")}
          onChange={(event) => setState((s) => ({ ...s, text: event.target.value, saved: false }))} style={{ width: "100%" }} /></label>
        <small>{msg("notebook.customization.count", { count: state.text.length, max: CUSTOMIZATION_MAX })}</small>
        {state.loading ? <div role="status">{msg("notebook.customization.loading")}</div> : null}
        {state.saved ? <div role="status">{msg("notebook.customization.saved")}</div> : null}
        {state.error ? <div role="alert">{conflict ? msg("notebook.customization.conflict") : msg("notebook.customization.failed", { code: state.error })}</div> : null}
        <button type="button" disabled={state.loading || state.saving || conflict} onClick={save}>{msg("notebook.customization.save")}</button>
      </div>
    </section>
  </div>;
}

// 공통 대화상자 틀: 이름·aria-modal·Esc 닫기·포커스 가둠(S6-01).
function ModalFrame({ titleId, title, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => { focusInitialModalControl(ref.current); }, []);
  return <div className="workspace-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={ref} className="workspace-modal" role="dialog" aria-modal="true" aria-labelledby={titleId}
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } else trapModalTab(ref.current, event); }}>
      <header className="workspace-modal-header"><div><span className="section-kicker">NOTEBOOK</span><h2 id={titleId}>{title}</h2></div>
        <button type="button" onClick={onClose} aria-label={msg("notebook.dialog.close")}>{msg("studio.dialog.close")}</button></header>
      <div className="workspace-modal-content">{children}</div>
    </section>
  </div>;
}

// 노트북 복사(S3-04, ST-T20): 복사할 범위를 고르고 새 노트북으로 이동한다. 같은 대화상자의 재시도는 같은 멱등 키를 쓴다.
export function CopyDialog({ studio, title = "", counts = {}, onClose, onCopied = (id) => window.location.assign(`/notebooks/${encodeURIComponent(id)}`) }) {
  const [include, setInclude] = useState({ sources: false, memos: true, outputs: true, customization: true });
  const [name, setName] = useState(title ? msg("notebook.copy.default_title", { title }).slice(0, 160) : "");
  const [state, setState] = useState({ busy: false, error: null, result: null });
  const keyRef = useRef(`studio-v2-${secureUuid()}`);
  const toggle = (key) => setInclude((value) => ({ ...value, [key]: !value[key] }));
  const submit = async () => {
    setState({ busy: true, error: null, result: null });
    try {
      const result = await studio.copyNotebook({ title: name.trim() || undefined, include, idempotencyKey: keyRef.current });
      const skipped = Object.values(result.skipped ?? {}).reduce((sum, n) => sum + (Number.isSafeInteger(n) ? n : 0), 0);
      if (skipped > 0) setState({ busy: false, error: null, result });
      else onCopied(result.notebook_id);
    } catch (error) {
      setState({ busy: false, error: error?.code ?? "STUDIO_REQUEST_FAILED", result: null });
    }
  };
  const rows = [["sources", "notebook.copy.sources"], ["memos", "notebook.copy.memos"], ["outputs", "notebook.copy.outputs"], ["customization", "notebook.copy.customization"]];
  const tooLarge = state.error === "NOTEBOOK_COPY_TOO_LARGE";
  return <ModalFrame titleId="notebook-copy-title" title={msg("notebook.copy.title")} onClose={onClose}>
    <label>{msg("notebook.copy.name")}<input aria-label={msg("notebook.copy.name")} value={name} maxLength={160} disabled={state.busy || !!state.result}
      onChange={(event) => setName(event.target.value)} style={{ width: "100%" }} /></label>
    <fieldset disabled={state.busy || !!state.result} style={{ border: 0, padding: 0 }}><legend>{msg("notebook.copy.include")}</legend>
      {rows.map(([key, label]) => <label key={key} style={{ display: "block" }}>
        <input type="checkbox" checked={include[key]} disabled={key === "sources"} onChange={() => toggle(key)} /> {msg(label)}{Number.isSafeInteger(counts[key]) ? ` (${counts[key]})` : ""}
        {key === "sources" ? <small> {msg("notebook.copy.sources_pending")}</small> : null}</label>)}
    </fieldset>
    <p><small>{msg("notebook.copy.note")}</small></p>
    {state.error ? <div role="alert">{tooLarge ? msg("notebook.copy.too_large") : msg("notebook.copy.failed", { code: state.error })}</div> : null}
    {state.result ? <div role="status">{msg("notebook.copy.skipped", { count: Object.values(state.result.skipped).reduce((a, b) => a + b, 0) })}
      <button type="button" onClick={() => onCopied(state.result.notebook_id)}>{msg("notebook.copy.open")}</button></div> : null}
    {!state.result ? <button type="button" disabled={state.busy || !Object.values(include).some(Boolean)} onClick={submit}>{msg("notebook.copy.submit")}</button> : null}
  </ModalFrame>;
}

// 채팅 기록 삭제(S3-05, ST-T19): 내 기록만 비운다. 메모·산출물은 그대로다.
export function ClearHistoryDialog({ studio, onClose, onCleared = () => window.location.reload() }) {
  const [state, setState] = useState({ busy: false, error: null });
  const submit = async () => {
    setState({ busy: true, error: null });
    try { await studio.clearChatHistory(); onCleared(); } catch (error) { setState({ busy: false, error: error?.code ?? "STUDIO_REQUEST_FAILED" }); }
  };
  return <ModalFrame titleId="notebook-clear-title" title={msg("notebook.clear.title")} onClose={onClose}>
    <p>{msg("notebook.clear.body")}</p>
    {state.error ? <div role="alert">{msg("notebook.clear.failed", { code: state.error })}</div> : null}
    <div className="studio-row">
      <button type="button" disabled={state.busy} onClick={submit}>{msg("notebook.clear.confirm")}</button>
      <button type="button" disabled={state.busy} onClick={onClose}>{msg("studio.dialog.settings.cancel")}</button>
    </div>
  </ModalFrame>;
}

export function NotebookTools({ studio, title = "", counts = {}, onCreateNotebook = () => window.location.assign("/notebooks"), onOpenChatSettings = null, onNotebookCopied = undefined, onChatCleared = undefined }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [dialog, setDialog] = useState(null);
  const anchorRef = useRef(null);
  const closeDialog = () => { setDialog(null); setTimeout(() => anchorRef.current?.querySelector?.("button")?.focus?.(), 0); };
  useEffect(() => {
    if (!menuOpen) return undefined;
    const close = (event) => { if (!anchorRef.current?.contains(event.target)) setMenuOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);
  return <div className="notebook-tools">
    <button type="button" className="notebook-create" onClick={onCreateNotebook}>{msg("notebook.create")}</button>
    <button type="button" className="notebook-share" disabled title={msg("notebook.share.pending")}>{msg("notebook.share")}</button>
    <div className="settings-menu-anchor" ref={anchorRef}>
      <button type="button" aria-haspopup="menu" aria-expanded={menuOpen} aria-label={msg("notebook.menu")} onClick={() => setMenuOpen((open) => !open)}>⋮</button>
      {menuOpen ? <div className="settings-menu" role="menu" aria-label={msg("notebook.menu")}>
        <button type="button" role="menuitem" disabled={!onOpenChatSettings} onClick={() => { setMenuOpen(false); onOpenChatSettings?.(); }}><span><strong>{msg("notebook.menu.chat_settings")}</strong><small>{msg("notebook.menu.chat_settings.hint")}</small></span></button>
        <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); setDialog("customization"); }}><span><strong>{msg("notebook.menu.customization")}</strong><small>{msg("notebook.menu.customization.hint")}</small></span></button>
        <button type="button" role="menuitem" disabled={!studio?.copyNotebook} onClick={() => { setMenuOpen(false); setDialog("copy"); }}><span><strong>{msg("notebook.menu.copy")}</strong><small>{msg("notebook.menu.copy.hint")}</small></span></button>
        <button type="button" role="menuitem" disabled={!studio?.clearChatHistory} onClick={() => { setMenuOpen(false); setDialog("clear"); }}><span><strong>{msg("notebook.menu.clear_history")}</strong><small>{msg("notebook.menu.clear_history.hint")}</small></span></button>
      </div> : null}
    </div>
    {dialog === "customization" && studio ? <CustomizationDialog studio={studio} onClose={closeDialog} /> : null}
    {dialog === "copy" && studio ? <CopyDialog studio={studio} title={title} counts={counts} onCopied={onNotebookCopied} onClose={closeDialog} /> : null}
    {dialog === "clear" && studio ? <ClearHistoryDialog studio={studio} onCleared={onChatCleared} onClose={closeDialog} /> : null}
  </div>;
}

export default NotebookTools;
