"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { StudioIcon, STUDIO_TYPE_STYLE } from "./studio-icon.js";
import {
  TILE_ORDER, cardState, cardSubtitle, createStudioPanelState, menuItems, optimisticOutput, pollInterval, progressPercent, reduce, researchProgress, tileState, waitingOutputIds,
} from "./studio-panel-model.js";
import { msg, studioErrorMessage } from "./studio-messages.ko.js";
import { ConfirmDeleteDialog, EvidenceDialog, ExportStepUpDialog, ProvenanceDialog, SettingsDialog, ShareDialog } from "./studio-dialogs.jsx";
import { StudioViewer } from "./studio-viewers.jsx";
import { AuthoringWizard } from "./authoring-wizard.jsx";
import { EDITABLE_TYPES, StudioEditor } from "./studio-editor.jsx";
import { CHAT_EDIT_TYPES, StudioChatEdit } from "./studio-chat-edit.jsx";
import { ResearchSourcesPanel } from "./source-discovery.jsx";
import "./studio-icon.css";
import "./studio-panel.css";

const MENU_ICONS = { share: "share", rename: "edit", download: "download", provenance: "info_sparkle", regenerate: "refresh", regenerate_with_settings: "settings_sliders", delete: "delete" };
const label = (type) => msg(`studio.tile.${type}`);
// 생성 전 구성 확인에서 멈출 수 있는 유형(보고서 WO-K4, 슬라이드·동영상 WO-N1 NB3-F1).
const OUTLINE_TYPES = new Set(["report", "slides", "video_overview"]);
const inOutlineReview = (output) => Boolean(output?.revision?.content?.body?.outline_review?.length);
// 심층 조사 보고서(NB4-U2): 보고서 본문에서 실제로 인용한 근거 라벨(S1…) 목록.
const citedRefs = (content) => [...new Set((content?.body?.sections ?? []).flatMap((section) => (section?.blocks ?? []).flatMap((block) => (Array.isArray(block?.refs) ? block.refs : []))))];

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

function Card({ output, now, waiting = false, outlinePending = false, confirmedOutline = false, focused = false, menuOpen, renaming, onOpen, onToggleMenu, onMenuAction, onRename, onCancelRename, onCancel, onRetry }) {
  const state = cardState(output);
  const type = STUDIO_TYPE_STYLE[output.type_id] ?? STUDIO_TYPE_STYLE.report;
  const [title, setTitle] = useState(output.title);
  const generating = state === "generating";
  let subtitle = cardSubtitle(output, { now });
  // 동시 생성 한도 때문에 시작을 기다리는 산출물은 "대기 중"으로 구분한다(낙관적 카드와 실행 중 카드는 "생성 중").
  // 심층 조사(NB4-U2)는 서버 진행 메모로 단계(계획 → 찾기 n/m → 작성)를 보인다. 조사는 구성 확인을 쓰지 않아 확정 문구와 겹치지 않는다.
  const research = generating && !waiting ? researchProgress(output) : null;
  if (generating) subtitle = waiting ? msg("studio.card.queued") : research ? msg(`studio.research.progress.${research.step}`, research)
    : confirmedOutline ? msg("studio.card.generating_confirmed") : msg("studio.card.generating");
  else if (state === "failed") subtitle = studioErrorMessage(output.error_code) || msg("studio.card.failed");
  else if (state === "cancelled") subtitle = msg("studio.card.cancelled");
  const needsReview = outlinePending && (state === "ready" || state === "stale");
  return <li className="studio-card" data-state={state} data-outline={needsReview ? "review" : undefined} data-output-id={output.output_id}
    data-research-step={research?.step} data-focused={focused ? "true" : undefined}>
    <button type="button" className="studio-card__main" disabled={generating && output.optimistic} onClick={() => onOpen(output)} aria-label={`${msg("studio.card.open")}: ${output.title}`}>
      <StudioIcon name={generating ? "spinner" : state === "failed" ? "warning" : type.icon} accent={!generating && state !== "failed" ? output.type_id : false} size={24} />
      <span className="studio-card__text">
        {renaming
          ? null
          : <span className="studio-card__title">{output.title}</span>}
        <span className="studio-card__subtitle">{subtitle}{needsReview && <span className="studio-chip">{msg("studio.card.outline_needed")}</span>}{state === "stale" && <span className="studio-chip">{msg("studio.card.stale")}</span>}</span>
        {generating && <span className="studio-progress" aria-hidden="true"><span style={{ width: `${progressPercent(output)}%` }} /></span>}
        {focused && <span className="sr-only">{msg("studio.card.focused")}</span>}
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

// 메모를 소스로(NB1-U2): 이 오류 뒤에는 서버의 연결 상태가 화면과 다를 수 있어 메모를 다시 읽는다.
const MEMO_SOURCE_RELOAD_CODES = new Set(["MEMO_SOURCE_EXISTS", "MEMO_SOURCE_UNCHANGED", "MEMO_SOURCE_NOT_LINKED"]);

function Detail({ studio, outputId, canEdit = true, onBack, onOpenEvidence, onAskAboutNode, onError, onMemoSourceChanged, onOutlineConfirmed, onDiscoveryAdded }) {
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
  // 편집 권한이 있고 어댑터·서버가 메모-소스 계약을 줄 때만 버튼을 보인다(서버도 보기 권한이면 403).
  const memoSourceAvailable = canEdit && output?.type_id === "memo" && output.source_link !== undefined
    && typeof studio.createMemoSource === "function" && typeof studio.reflectMemoSource === "function";
  const runMemoSource = async (kind) => {
    try {
      const result = kind === "created" ? await studio.createMemoSource(outputId) : await studio.reflectMemoSource(outputId);
      setOutput(await studio.getOutput(outputId));
      onMemoSourceChanged?.({ kind, sourceId: result.source_id, outputId });
    } catch (error) {
      if (MEMO_SOURCE_RELOAD_CODES.has(error?.code)) { try { setOutput(await studio.getOutput(outputId)); } catch { /* 이전 상태를 유지한다 */ } }
      throw error;
    }
  };
  const reviewing = inOutlineReview(output);
  // 구성 확정(보고서·슬라이드·동영상 공통): 확정 목록으로 다시 생성하고 목록으로 돌아가 카드가 생성 중이 된다. 422 OUTLINE_INVALID는 검토 화면이 문구로 보인다.
  const confirmOutline = async (confirmed_outline) => {
    await studio.regenerateOutput(outputId, { settings: { confirm_outline: "no", confirmed_outline } });
    if (onOutlineConfirmed) onOutlineConfirmed(outputId);
    else setOutput(await studio.getOutput(outputId));
  };
  const memoSource = memoSourceAvailable ? { link: output.source_link, onCreate: () => runMemoSource("created"), onReflect: () => runMemoSource("reflected") } : null;
  // 심층 조사 보고서(NB4-U2): 어댑터의 researchOf(=studioResearchOf)가 조사 정보를 줄 때만 근거 라벨·사용한 자료를 보인다.
  const research = output && output.type_id === "report" && !reviewing && typeof studio.researchOf === "function" ? studio.researchOf(output) : null;
  return <div className="studio-detail">
    <div className="studio-detail__bar">
      <button type="button" className="studio-icon-button" aria-label={msg("studio.back")} onClick={onBack}><StudioIcon name="chevron_right" size={20} className="studio-flip" style={{ transform: "rotate(180deg)" }} /></button>
      <h2 className="studio-detail__title">{output?.title ?? ""}</h2>
      {output && EDITABLE_TYPES.includes(output.type_id) && output.status === "completed" && !editing && !reviewing && output.revision?.content
        && <button type="button" className="studio-btn" onClick={() => setEditing(true)}>{msg("studio.edit")}</button>}
      {exportFormats.length > 0 && !reviewing && <span style={{ position: "relative" }}>
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
      {output && !editing && <StudioViewer output={output} research={Boolean(research)} onConfirmOutline={confirmOutline} onCancelOutline={onBack} onOpenEvidence={(ref) => onOpenEvidence(output, ref)} onAskAboutNode={onAskAboutNode}
        onLoadImage={loadImage} onLoadAudio={loadAudio} onLoadVideo={loadVideo} onLoadCaptions={loadCaptions}
        onAttempt={(kind, payload) => studio.recordLearningAttempt?.(outputId, { revisionNo: output.current_revision, kind, payload }).catch(() => {})}
        memoSource={memoSource}
        onSaveMemo={async (content) => {
          const saved = await studio.createRevision(outputId, { content });
          // 새 리비전이 반영 리비전과 다르면 "소스에 반영"으로 바뀐다(D-10: 반영 버튼으로만 새 소스 버전).
          setOutput((o) => ({ ...o, current_revision: saved.revision_no,
            ...(o.source_link ? { source_link: { ...o.source_link, outdated: saved.revision_no !== o.source_link.reflected_revision_no } } : {}) }));
        }} />}
      {output && !editing && research && <ResearchSourcesPanel studio={studio} research={research} citedRefs={citedRefs(output.revision?.content)} canEdit={canEdit} onAdded={onDiscoveryAdded} />}
      {output && !editing && !reviewing && output.status === "completed" && CHAT_EDIT_TYPES.includes(output.type_id) && typeof studio.listEditTurns === "function"
        && <StudioChatEdit studio={studio} outputId={outputId} onApplied={async () => setOutput(await studio.getOutput(outputId))} />}
    </div>
  </div>;
}

/**
 * Studio v2 패널. `studio`는 어댑터의 studioV2(노트북 범위가 이미 주입된 함수 묶음)이다.
 * sourceStats: { sourceCount, checkedCount, readySourceCount, processingCount }.
 */
export function StudioPanel({ studio, sourceStats = {}, sources = [], checkedSourceVersionIds = [], onToggleCollapse, onAskAboutNode, refreshToken = 0, now = () => Date.now(),
  canEdit = true, onMemoSourceChanged, openOutputRequest = null, focusOutputRequest = null, onDiscoveryAdded }) {
  const [state, dispatch] = useReducer(reduce, undefined, createStudioPanelState);
  const [menuFor, setMenuFor] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [authoringOpen, setAuthoringOpen] = useState(null);
  const waiting = waitingOutputIds(state.outputs, state.types?.limits?.userConcurrency);
  const stateRef = useRef(state);
  stateRef.current = state;
  // 구성 확인(NB3-U1): 목록 응답에는 멈춤 표시가 없어, 멈출 수 있는 유형의 완료 산출물만 상세를 한 번 읽어 확인한다(리비전·수정 시각이 바뀔 때만 다시).
  const outlineProbed = useRef(new Map());
  const [outlinePending, setOutlinePending] = useState(() => new Set());
  const [confirmedOutlines, setConfirmedOutlines] = useState(() => new Set());

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

  // 패널 밖(소스 줄의 "메모" 표시 등)에서 산출물 보기를 열어 달라는 요청. nonce가 바뀔 때마다 한 번 연다.
  useEffect(() => {
    if (!openOutputRequest?.outputId) return;
    setAuthoringOpen(null);
    dispatch({ type: "SELECT", outputId: openOutputRequest.outputId });
  }, [openOutputRequest?.outputId, openOutputRequest?.nonce]);

  // 새 카드로 이동(NB4-U2 심층 조사 시작): 보기·작성 마법사를 닫고 목록을 다시 읽은 뒤, 그 카드가 목록에 나타나면 스크롤하고 강조한다.
  const [focusTarget, setFocusTarget] = useState(null);
  const [focusedId, setFocusedId] = useState(null);
  const listRef = useRef(null);
  useEffect(() => {
    if (!focusOutputRequest?.outputId) return;
    setAuthoringOpen(null);
    setMenuFor(null);
    dispatch({ type: "SELECT", outputId: null });
    setFocusTarget(focusOutputRequest.outputId);
    reload().catch(() => {});
  }, [focusOutputRequest?.outputId, focusOutputRequest?.nonce, reload]);
  useEffect(() => {
    if (!focusTarget || state.selectedOutputId || !state.outputs.some((o) => o.output_id === focusTarget)) return;
    const node = [...(listRef.current?.childNodes ?? [])].find((child) => child.getAttribute?.("data-output-id") === focusTarget);
    if (!node) return;
    node.scrollIntoView?.({ block: "nearest" });
    setFocusedId(focusTarget);
    setFocusTarget(null);
  }, [focusTarget, state.outputs, state.selectedOutputId]);

  useEffect(() => {
    const mark = (id, on) => setOutlinePending((current) => {
      if (current.has(id) === on) return current;
      const next = new Set(current);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
    for (const output of state.outputs) {
      const id = output.output_id;
      if (!OUTLINE_TYPES.has(output.type_id) || output.optimistic) continue;
      if (output.status !== "completed" || !(output.current_revision > 0)) { if (output.status !== "completed") mark(id, false); continue; }
      const key = `${output.current_revision}:${output.updated_at}`;
      if (outlineProbed.current.get(id) === key) continue;
      outlineProbed.current.set(id, key);
      Promise.resolve(studio.getOutput(id)).then((detail) => mark(id, inOutlineReview(detail))).catch(() => { outlineProbed.current.delete(id); });
    }
  }, [state.outputs, studio]);

  const outlineConfirmed = (outputId) => {
    setConfirmedOutlines((current) => new Set(current).add(outputId));
    setOutlinePending((current) => { const next = new Set(current); next.delete(outputId); return next; });
    if (stateRef.current.outputs.some((o) => o.output_id === outputId)) dispatch({ type: "OUTPUT_UPDATED", output: { output_id: outputId, status: "queued", error_code: null } });
    dispatch({ type: "SELECT", outputId: null });
  };

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

  const regenerate = async (output, settings, formatId) => {
    dispatch({ type: "BUSY", outputId: output.output_id, on: true });
    try {
      await studio.regenerateOutput(output.output_id, formatId ? { settings, formatId } : { settings });
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
      onClose={() => { setAuthoringOpen(null); reload().catch(() => {}); }} /> : selected ? <Detail key={selected} studio={studio} outputId={selected} canEdit={canEdit} onMemoSourceChanged={onMemoSourceChanged} onOutlineConfirmed={outlineConfirmed} onDiscoveryAdded={onDiscoveryAdded} onBack={() => { dispatch({ type: "SELECT", outputId: null }); reload().catch(() => {}); }}
      onOpenEvidence={openEvidence} onAskAboutNode={onAskAboutNode} onError={(code) => dispatch({ type: "ERROR", code })} /> : <>
      <div className="studio-v2-tiles" role="group" aria-label={msg("studio.create_group")}>
        {TILE_ORDER.map((typeId) => {
          const type = typeById.get(typeId) ?? { type_id: typeId, available: false };
          const tile = tileState(type, stats);
          const style = STUDIO_TYPE_STYLE[typeId];
          return <div key={typeId} className="studio-tile-wrap" style={{ position: "relative" }}>
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
        : <ul className="studio-list" ref={listRef}>{state.outputs.map((output) => <Card key={output.output_id} output={output} now={now()} waiting={waiting.has(output.output_id)}
          focused={focusedId === output.output_id}
          outlinePending={outlinePending.has(output.output_id)} confirmedOutline={confirmedOutlines.has(output.output_id)}
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
      try { await studio.deleteOutput(target.output_id); dispatch({ type: "OUTPUT_REMOVED", outputId: target.output_id });
        // 메모를 지우면 그 메모로 만든 소스 줄이 "원본 메모 없음"으로 바뀌도록 셸이 소스 목록을 다시 읽게 한다(N1-B06).
        if (target.type_id === "memo") onMemoSourceChanged?.({ kind: "deleted", outputId: target.output_id }); } catch (error) { dispatch({ type: "ERROR", code: error?.code }); }
    }} />}
    {dialog?.kind === "settings" && <SettingsDialog type={typeById.get(dialog.typeId)} typeLabel={label(dialog.typeId)} onCancel={() => setDialog(null)}
      onSubmit={(values) => { const typeId = dialog.typeId; setDialog(null); create(typeId, values); }} />}
    {dialog?.kind === "regenerate" && <SettingsDialog type={typeById.get(dialog.output.type_id)} typeLabel={label(dialog.output.type_id)} initial={{ format_id: dialog.output.format_id }} onCancel={() => setDialog(null)}
      onSubmit={(values) => { const target = dialog.output; setDialog(null); regenerate(target, values.settings, values.formatId); }} />}
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
export function StudioFallbackGate({ adapter, sources = [], unchecked = new Set(), fallback = null, onAskAboutNode, refreshToken = 0, knowledgeCount = 0,
  canEdit = true, onMemoSourceChanged, openOutputRequest = null, focusOutputRequest = null, onDiscoveryAdded }) {
  const studio = adapter?.studioV2;
  if (!studio) return fallback;
  const ready = sources.filter((source) => source.ready);
  const checked = ready.filter((source) => !unchecked.has(source.sourceVersionId)).map((source) => source.sourceVersionId);
  const processing = sources.filter((source) => !source.ready && ["processing", "queued", "pending", "uploaded"].includes(source.sourceState)).length;
  return <StudioPanelGate studio={studio} fallback={fallback} onAskAboutNode={onAskAboutNode} refreshToken={refreshToken} sources={sources}
    canEdit={canEdit} onMemoSourceChanged={onMemoSourceChanged} openOutputRequest={openOutputRequest} focusOutputRequest={focusOutputRequest} onDiscoveryAdded={onDiscoveryAdded}
    checkedSourceVersionIds={checked} sourceStats={{ sourceCount: sources.length, checkedCount: checked.length, readySourceCount: ready.length, processingCount: processing, knowledgeCount }} />;
}

export default StudioPanel;
