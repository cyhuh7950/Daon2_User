"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { StudioIcon, STUDIO_TYPE_STYLE } from "./studio-icon.js";
import {
  TILE_ORDER, cardState, cardSubtitle, createStudioPanelState, menuItems, optimisticOutput, pollInterval, reduce, tileState, waitingOutputIds,
} from "./studio-panel-model.js";
import { msg, studioErrorMessage } from "./studio-messages.ko.js";
import { ConfirmDeleteDialog, EvidenceDialog, ExportStepUpDialog, ProvenanceDialog, SettingsDialog, ShareDialog } from "./studio-dialogs.jsx";
import { StudioViewer } from "./studio-viewers.jsx";
import { AuthoringWizard } from "./authoring-wizard.jsx";
import { EDITABLE_TYPES, StudioEditor } from "./studio-editor.jsx";
import "./studio-icon.css";
import "./studio-panel.css";

const MENU_ICONS = { share: "share", rename: "edit", download: "download", provenance: "info_sparkle", regenerate: "refresh", regenerate_with_settings: "settings_sliders", delete: "delete" };
const label = (type) => msg(`studio.tile.${type}`);

function CardMenu({ output, onAction, onClose }) {
  const ref = useRef(null);
  const items = menuItems(output);
  useEffect(() => {
    const first = ref.current?.querySelector?.("button:not(:disabled)");
    first?.focus();
    const outside = (event) => { if (ref.current && !ref.current.contains(event.target)) onClose(); };
    globalThis.document?.addEventListener("mousedown", outside);
    return () => globalThis.document?.removeEventListener("mousedown", outside);
  }, [onClose]);
  return <div ref={ref} className="studio-menu" role="menu" aria-label={msg("studio.card.more")}
    onKeyDown={(event) => {
      if (event.key === "Escape") { event.stopPropagation(); onClose(); return; }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const buttons = [...(ref.current?.querySelectorAll?.("button:not(:disabled)") ?? [])];
        const at = buttons.indexOf(globalThis.document.activeElement);
        buttons[(at + (event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length]?.focus();
      }
    }}>
    {items.map((item, index) => <div key={item.id}>
      {item.id === "delete" && <hr />}
      <button type="button" role="menuitem" disabled={item.disabled} data-danger={item.danger ? "true" : undefined} onClick={() => onAction(item.id)}>
        <StudioIcon name={MENU_ICONS[item.id]} size={20} />{msg(`studio.menu.${item.id}`)}
      </button>
    </div>)}
  </div>;
}

function Card({ output, now, waiting = false, menuOpen, renaming, onOpen, onToggleMenu, onMenuAction, onRename, onCancelRename, onCancel, onRetry }) {
  const state = cardState(output);
  const type = STUDIO_TYPE_STYLE[output.type_id] ?? STUDIO_TYPE_STYLE.report;
  const [title, setTitle] = useState(output.title);
  const generating = state === "generating";
  let subtitle = cardSubtitle(output, { now });
  // 동시 생성 한도 때문에 시작을 기다리는 산출물은 "대기 중"으로 구분한다(낙관적 카드와 실행 중 카드는 "생성 중").
  if (generating) subtitle = waiting ? msg("studio.card.queued") : msg("studio.card.generating");
  else if (state === "failed") subtitle = studioErrorMessage(output.error_code) || msg("studio.card.failed");
  else if (state === "cancelled") subtitle = msg("studio.card.cancelled");
  return <li className="studio-card" data-state={state}>
    <button type="button" className="studio-card__main" disabled={generating && output.optimistic} onClick={() => onOpen(output)} aria-label={`${msg("studio.card.open")}: ${output.title}`}>
      <StudioIcon name={generating ? "spinner" : state === "failed" ? "warning" : type.icon} accent={!generating && state !== "failed" ? output.type_id : false} size={24} />
      <span className="studio-card__text">
        {renaming
          ? null
          : <span className="studio-card__title">{output.title}</span>}
        <span className="studio-card__subtitle">{subtitle}{state === "stale" && <span className="studio-chip">{msg("studio.card.stale")}</span>}</span>
        {generating && <span className="studio-progress" aria-hidden="true"><span style={{ width: `${output.progress_pct ?? 20}%` }} /></span>}
      </span>
    </button>
    {renaming && <input className="studio-rename" aria-label={msg("studio.menu.rename")} value={title} maxLength={160} autoFocus
      onChange={(event) => setTitle(event.target.value)}
      onKeyDown={(event) => { if (event.key === "Enter" && title.trim()) onRename(title.trim()); if (event.key === "Escape") onCancelRename(); }} />}
    {generating && !output.optimistic && <button type="button" className="studio-btn" onClick={() => onCancel(output)}>{msg("studio.card.cancel")}</button>}
    {state === "failed" && <button type="button" className="studio-btn" onClick={() => onRetry(output)}>{msg("studio.card.retry")}</button>}
    <button type="button" className="studio-icon-button" aria-haspopup="menu" aria-expanded={menuOpen} aria-label={`${msg("studio.card.more")}: ${output.title}`}
      disabled={output.optimistic} onClick={() => onToggleMenu(output.output_id)}><StudioIcon name="more_vertical" size={20} /></button>
    {menuOpen && <CardMenu output={output} onAction={(id) => onMenuAction(id, output)} onClose={() => onToggleMenu(null)} />}
  </li>;
}

function Detail({ studio, outputId, onBack, onOpenEvidence, onAskAboutNode, onError }) {
  const [output, setOutput] = useState(null);
  const [error, setError] = useState(null);
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    let alive = true;
    studio.getOutput(outputId).then((data) => { if (alive) setOutput(data); }).catch((e) => { if (alive) setError(e?.code ?? "STUDIO_REQUEST_FAILED"); });
    return () => { alive = false; };
  }, [studio, outputId]);
  const loadImage = useCallback(() => studio.downloadExport(outputId, "png"), [studio, outputId]);
  const loadAudio = useCallback(() => studio.getAudio(outputId), [studio, outputId]);
  const loadVideo = useCallback(() => studio.getVideo(outputId), [studio, outputId]);
  const loadCaptions = useCallback(() => studio.downloadExport(outputId, "vtt"), [studio, outputId]);
  const [stepUp, setStepUp] = useState(null); // { format, pending, error } — 조직이 내보내기 추가 인증을 켠 경우
  const download = async (format, grant) => {
    try {
      const { bytes, contentType, disposition } = await studio.downloadExport(outputId, format, grant ? { stepUp: grant } : undefined);
      setStepUp(null);
      const blob = new Blob([bytes], { type: contentType });
      const url = globalThis.URL.createObjectURL(blob);
      const match = /filename\*=UTF-8''([^;]+)/u.exec(disposition) ?? /filename="([^"]+)"/u.exec(disposition);
      const anchor = globalThis.document.createElement("a");
      anchor.href = url; anchor.download = match ? decodeURIComponent(match[1]) : `studio.${format}`;
      globalThis.document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => globalThis.URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      if (e?.code === "STEP_UP_REQUIRED" && studio.issueExportStepUp) setStepUp({ format, pending: false, error: null });
      else onError(e?.code);
    }
    setDownloadOpen(false);
  };
  const submitStepUp = async (password) => {
    const { format } = stepUp;
    setStepUp({ format, pending: true, error: null });
    try {
      const grant = await studio.issueExportStepUp(outputId, password);
      await download(format, grant);
    } catch {
      setStepUp({ format, pending: false, error: msg("dialog.stepup.failed") });
    }
  };
  const exportFormats = output ? (studio.exportFormats?.(output.type_id) ?? []) : [];
  return <div className="studio-detail">
    <div className="studio-detail__bar">
      <button type="button" className="studio-icon-button" aria-label={msg("studio.back")} onClick={onBack}><StudioIcon name="chevron_right" size={20} className="studio-flip" style={{ transform: "rotate(180deg)" }} /></button>
      <h2 className="studio-detail__title">{output?.title ?? ""}</h2>
      {output && EDITABLE_TYPES.includes(output.type_id) && output.status === "completed" && !editing && output.revision?.content
        && <button type="button" className="studio-btn" onClick={() => setEditing(true)}>{msg("studio.edit")}</button>}
      {exportFormats.length > 0 && <span style={{ position: "relative" }}>
        <button type="button" className="studio-btn" aria-haspopup="menu" aria-expanded={downloadOpen} onClick={() => setDownloadOpen((v) => !v)}>{msg("studio.menu.download")}</button>
        {downloadOpen && <div className="studio-menu" role="menu" style={{ top: 44 }} onKeyDown={(event) => { if (event.key === "Escape") setDownloadOpen(false); }}>
          {exportFormats.map((format) => <button key={format} type="button" role="menuitem" onClick={() => download(format)}>{format.toUpperCase()}</button>)}</div>}
      </span>}
    </div>
    <div className="studio-detail__body">
      {stepUp && <ExportStepUpDialog pending={stepUp.pending} error={stepUp.error} onSubmit={(password) => void submitStepUp(password)} onCancel={() => setStepUp(null)} />}
      {error && <p className="studio-alert" role="alert">{studioErrorMessage(error)}</p>}
      {!output && !error && <p role="status">…</p>}
      {output && editing && <StudioEditor output={output} onCancel={() => setEditing(false)} onSave={async (content) => {
        await studio.createRevision(outputId, { content, changeReason: msg("studio.edit.reason") });
        setOutput(await studio.getOutput(outputId));  // 서버가 정리한 본문·새 리비전 번호로 다시 읽는다
        setEditing(false);
      }} />}
      {output && !editing && <StudioViewer output={output} onOpenEvidence={(ref) => onOpenEvidence(output, ref)} onAskAboutNode={onAskAboutNode}
        onLoadImage={loadImage} onLoadAudio={loadAudio} onLoadVideo={loadVideo} onLoadCaptions={loadCaptions}
        onAttempt={(kind, payload) => studio.recordLearningAttempt?.(outputId, { revisionNo: output.current_revision, kind, payload }).catch(() => {})}
        onSaveMemo={async (content) => { const saved = await studio.createRevision(outputId, { content }); setOutput((o) => ({ ...o, current_revision: saved.revision_no })); }} />}
    </div>
  </div>;
}

/**
 * Studio v2 패널. `studio`는 어댑터의 studioV2(노트북 범위가 이미 주입된 함수 묶음)이다.
 * sourceStats: { sourceCount, checkedCount, readySourceCount, processingCount }.
 */
export function StudioPanel({ studio, sourceStats = {}, sources = [], checkedSourceVersionIds = [], onToggleCollapse, onAskAboutNode, refreshToken = 0, now = () => Date.now() }) {
  const [state, dispatch] = useReducer(reduce, undefined, createStudioPanelState);
  const [menuFor, setMenuFor] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [authoringOpen, setAuthoringOpen] = useState(null);
  const waiting = waitingOutputIds(state.outputs, state.types?.limits?.userConcurrency);
  const stateRef = useRef(state);
  stateRef.current = state;

  const reload = useCallback(async () => {
    const [types, page] = await Promise.all([studio.listTypes(), studio.listOutputs({ limit: 50 })]);
    dispatch({ type: "LOADED", types, outputs: page.items, nextCursor: page.nextCursor });
  }, [studio]);

  useEffect(() => {
    let alive = true;
    reload().catch((error) => { if (alive) dispatch({ type: "ERROR", code: error?.code ?? "STUDIO_REQUEST_FAILED" }); });
    return () => { alive = false; };
  }, [reload]);

  // 셸의 "메모에 저장" 등 패널 밖 변경 뒤 목록을 다시 읽는다.
  useEffect(() => {
    if (refreshToken) reload().catch(() => {});
  }, [refreshToken, reload]);

  // 활성 작업이 있을 때만 폴링한다(1.5초, 숨김 탭은 10초).
  useEffect(() => {
    const interval = pollInterval(state.outputs, globalThis.document?.hidden === true);
    if (interval === null) return undefined;
    const timer = setTimeout(async () => {
      try { const page = await studio.listOutputs({ limit: 50 }); dispatch({ type: "POLL_RESULT", outputs: page.items }); } catch { /* 다음 주기에 다시 시도 */ }
    }, interval);
    return () => clearTimeout(timer);
  }, [state.outputs, studio]);

  const stats = { sourceCount: 0, checkedCount: checkedSourceVersionIds.length, readySourceCount: 0, processingCount: 0, ...sourceStats };
  const typeById = new Map(state.types.map((t) => [t.type_id, t]));

  const create = async (typeId, { formatId, settings } = {}) => {
    if (stateRef.current.pendingCreate.includes(typeId)) return;
    const placeholder = optimisticOutput(typeId, label(typeId), now());
    dispatch({ type: "CREATE_STARTED", typeId });
    dispatch({ type: "OUTPUT_UPDATED", output: placeholder });
    try {
      const receipt = await studio.createOutput({ typeId, formatId, settings, sourceVersionIds: typeId === "memo" ? undefined : checkedSourceVersionIds });
      dispatch({ type: "OUTPUT_REMOVED", outputId: placeholder.output_id });
      dispatch({ type: "OUTPUT_CREATED", typeId, output: { ...placeholder, output_id: receipt.output_id, status: receipt.status, optimistic: false } });
    } catch (error) {
      dispatch({ type: "OUTPUT_REMOVED", outputId: placeholder.output_id });
      dispatch({ type: "CREATE_FAILED", typeId, code: error?.code });
    }
  };

  const addMemo = async () => {
    try {
      const memo = await studio.createMemo({ markdown: "" });
      await reload();
      dispatch({ type: "SELECT", outputId: memo.output_id });
    } catch (error) { dispatch({ type: "ERROR", code: error?.code }); }
  };

  const doMenu = async (id, output) => {
    setMenuFor(null);
    if (id === "rename") setRenaming(output.output_id);
    else if (id === "delete") setDialog({ kind: "delete", output });
    else if (id === "share") setDialog({ kind: "share", output });
    else if (id === "provenance") setDialog({ kind: "provenance", output });
    else if (id === "download") dispatch({ type: "SELECT", outputId: output.output_id });
    else if (id === "regenerate" || id === "regenerate_with_settings") {
      if (id === "regenerate") await regenerate(output);
      else setDialog({ kind: "regenerate", output });
    }
  };

  const regenerate = async (output, settings) => {
    dispatch({ type: "BUSY", outputId: output.output_id, on: true });
    try {
      await studio.regenerateOutput(output.output_id, { settings });
      dispatch({ type: "OUTPUT_UPDATED", output: { ...output, status: "queued", error_code: null } });
    } catch (error) { dispatch({ type: "ERROR", code: error?.code }); }
    dispatch({ type: "BUSY", outputId: output.output_id, on: false });
  };

  const rename = async (output, title) => {
    try {
      const saved = await studio.renameOutput(output.output_id, title, { etag: `"studio-v2:${output.output_id}:${output.updated_at}"` });
      dispatch({ type: "OUTPUT_UPDATED", output: { ...output, title: saved.title, updated_at: saved.updated_at } });
    } catch (error) { dispatch({ type: "ERROR", code: error?.code }); }
    setRenaming(null);
  };

  const openEvidence = (output, ref) => setEvidence({ outputId: output.output_id, ref, revision: output.current_revision });

  const selected = state.selectedOutputId;
  return <section className="studio-panel" aria-label={msg("studio.title")} data-testid="studio-panel">
    <header className="studio-panel__header">
      <h2 className="studio-panel__title">{msg("studio.title")}</h2>
      {onToggleCollapse && <button type="button" className="studio-icon-button" aria-label={msg("studio.collapse")} onClick={onToggleCollapse}><StudioIcon name="panel_toggle" size={22} /></button>}
    </header>
    {state.error && <p className="studio-alert" role="alert">{studioErrorMessage(state.error)} <button type="button" className="studio-btn" onClick={() => dispatch({ type: "ERROR_CLEARED" })}>{msg("studio.dialog.close")}</button></p>}
    {authoringOpen ? <AuthoringWizard studio={studio} sources={sources} outputId={authoringOpen.outputId} onChanged={() => reload().catch(() => {})}
      onClose={() => { setAuthoringOpen(null); reload().catch(() => {}); }} /> : selected ? <Detail studio={studio} outputId={selected} onBack={() => { dispatch({ type: "SELECT", outputId: null }); reload().catch(() => {}); }}
      onOpenEvidence={openEvidence} onAskAboutNode={onAskAboutNode} onError={(code) => dispatch({ type: "ERROR", code })} /> : <>
      <div className="studio-v2-tiles" role="group" aria-label={msg("studio.create_group")}>
        {TILE_ORDER.map((typeId) => {
          const type = typeById.get(typeId) ?? { type_id: typeId, available: false };
          const tile = tileState(type, stats);
          const style = STUDIO_TYPE_STYLE[typeId];
          return <div key={typeId} style={{ position: "relative" }}>
            <button type="button" className="studio-tile" style={{ width: "100%" }} aria-disabled={!tile.enabled} aria-label={label(typeId)}
              aria-describedby={`studio-tip-${typeId}`} onClick={() => { if (tile.enabled) create(typeId); }}>
              <StudioIcon name={style.icon} accent={typeId} size={24} />
              <span className="studio-tile__label">{label(typeId)}</span>
              {typeId === "report" && type.new_until && Date.parse(type.new_until) > now() && <span className="studio-v2-badge">New</span>}
              <span id={`studio-tip-${typeId}`} role="tooltip" className="studio-tile__tooltip">{tile.enabled ? msg(`studio.tile.hint.${typeId}`) : msg(`studio.tile.disabled.${tile.reason}`)}</span>
            </button>
            {tile.enabled && type.settings_schema && <button type="button" className="studio-tile__edit" style={{ position: "absolute", right: 8, top: 12 }}
              aria-label={`${label(typeId)} ${msg("studio.tile.edit")}`} onClick={() => setDialog({ kind: "settings", typeId })}><StudioIcon name="edit" size={18} /></button>}
          </div>;
        })}
      </div>
      {studio.authoring && typeById.get("authored_document")?.available === true && <button type="button" className="studio-btn" style={{ alignSelf: "flex-start" }}
        onClick={() => setAuthoringOpen({ outputId: null })}><StudioIcon name="report" accent="report" size={18} /> {msg("studio.authoring.open")}</button>}
      <div className="studio-list-header"><span>{msg("studio.card.count", { count: state.outputs.length })}</span></div>
      {state.status === "loading" ? <p className="studio-empty" role="status">…</p> : state.outputs.length === 0
        ? <p className="studio-empty">{msg("studio.empty")}</p>
        : <ul className="studio-list">{state.outputs.map((output) => <Card key={output.output_id} output={output} now={now()} waiting={waiting.has(output.output_id)}
          menuOpen={menuFor === output.output_id} renaming={renaming === output.output_id}
          onOpen={(item) => {
            if (item.optimistic) return;
            if (item.type_id === "authored_document") { setAuthoringOpen({ outputId: item.output_id }); return; }
            if (cardState(item) !== "generating") dispatch({ type: "SELECT", outputId: item.output_id });
          }}
          onToggleMenu={(id) => setMenuFor((current) => (current === id ? null : id))} onMenuAction={doMenu}
          onRename={(title) => rename(output, title)} onCancelRename={() => setRenaming(null)}
          onCancel={async (item) => { try { await studio.cancelOutput(item.output_id); } catch (error) { dispatch({ type: "ERROR", code: error?.code }); } }}
          onRetry={(item) => regenerate(item)} />)}</ul>}
      <button type="button" className="studio-fab" onClick={addMemo}><StudioIcon name="add" size={20} />{msg("studio.memo.add")}</button>
    </>}
    {dialog?.kind === "delete" && <ConfirmDeleteDialog onCancel={() => setDialog(null)} onConfirm={async () => {
      const target = dialog.output; setDialog(null);
      try { await studio.deleteOutput(target.output_id); dispatch({ type: "OUTPUT_REMOVED", outputId: target.output_id }); } catch (error) { dispatch({ type: "ERROR", code: error?.code }); }
    }} />}
    {dialog?.kind === "settings" && <SettingsDialog type={typeById.get(dialog.typeId)} typeLabel={label(dialog.typeId)} onCancel={() => setDialog(null)}
      onSubmit={(values) => { const typeId = dialog.typeId; setDialog(null); create(typeId, values); }} />}
    {dialog?.kind === "regenerate" && <SettingsDialog type={typeById.get(dialog.output.type_id)} typeLabel={label(dialog.output.type_id)} initial={{}} onCancel={() => setDialog(null)}
      onSubmit={(values) => { const target = dialog.output; setDialog(null); regenerate(target, values.settings); }} />}
    {dialog?.kind === "provenance" && <ProvenanceDialog load={() => studio.getProvenance(dialog.output.output_id)} onClose={() => setDialog(null)}
      onOpenEvidence={(ref) => openEvidence(dialog.output, ref)} onRegenerate={(settings) => { const target = dialog.output; setDialog(null); regenerate(target, settings); }} />}
    {dialog?.kind === "share" && <ShareDialog load={() => studio.getSharing(dialog.output.output_id)} onClose={() => setDialog(null)} />}
    {evidence && <EvidenceDialog title={msg("studio.dialog.provenance.evidence")} onClose={() => setEvidence(null)}
      load={() => studio.getEvidenceContent(evidence.outputId, evidence.ref, { revision: evidence.revision })} />}
  </section>;
}

/**
 * v2가 켜져 있으면 StudioPanel, API가 v2를 제공하지 않으면(404 등) fallback(기존 Studio)을 보여준다.
 */
export function StudioPanelGate({ studio, fallback = null, ...props }) {
  const [mode, setMode] = useState("checking");
  useEffect(() => {
    let alive = true;
    studio.listTypes()
      .then(() => { if (alive) setMode("v2"); })
      .catch((error) => { if (alive) setMode(error?.status === 404 || error?.code === "RESOURCE_UNAVAILABLE" ? "legacy" : "v2"); });
    return () => { alive = false; };
  }, [studio]);
  if (mode === "checking") return <p className="studio-empty" role="status">…</p>;
  if (mode === "legacy") return fallback;
  return <StudioPanel studio={studio} {...props} />;
}

/** 셸용 진입점: 어댑터에 studioV2가 없으면 기존 Studio(fallback)를 그대로 보여준다. */
export function StudioFallbackGate({ adapter, sources = [], unchecked = new Set(), fallback = null, onAskAboutNode, refreshToken = 0 }) {
  const studio = adapter?.studioV2;
  if (!studio) return fallback;
  const ready = sources.filter((source) => source.ready);
  const checked = ready.filter((source) => !unchecked.has(source.sourceVersionId)).map((source) => source.sourceVersionId);
  const processing = sources.filter((source) => !source.ready && ["processing", "queued", "pending", "uploaded"].includes(source.sourceState)).length;
  return <StudioPanelGate studio={studio} fallback={fallback} onAskAboutNode={onAskAboutNode} refreshToken={refreshToken} sources={sources}
    checkedSourceVersionIds={checked} sourceStats={{ sourceCount: sources.length, checkedCount: checked.length, readySourceCount: ready.length, processingCount: processing }} />;
}

export default StudioPanel;
