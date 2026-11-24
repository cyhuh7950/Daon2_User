"use client";

// 소스 묶음(NB3-U2, WO-N1 N1-5, 결정 D-11 노트북 공유, 정정 C-4). 문구는 notebook-messages.ko.js의 notebook.source_groups.* 키만 쓴다.
// 셸의 Raw Source 목록 자리에 그린다. 소스 줄 자체는 셸이 renderRow(source, groupControl)로 그대로 그리고, 이 컴포넌트는
// 줄을 묶음별로 나누어 놓고 "묶음으로 이동" 단추(groupControl)만 건넨다. 기존 줄의 체크칸·선택·작업 메뉴·메모 표시는 바꾸지 않는다.
// 질문 범위는 바꾸지 않는다: 묶음 체크칸은 onSetChecked(안의 준비된 소스들, 체크 여부)를 부를 뿐이고, 셸은 이를 소스 하나씩
// 체크한 것과 똑같이 처리한다(uncheckedSourceVersionIds). 상한 8개 안내도 셸의 기존 질문 처리 그대로다.
// 서버 계약(NB3-F2 어댑터): listSourceGroups() → {groups, etag}. 변경은 마지막 ETag가 필요하고 {groups, etag}를 돌려준다.
// 412 SOURCE_GROUP_ETAG_MISMATCH → 다시 조회. 409 SOURCE_GROUP_LIMIT(50개). 422 SOURCE_NOT_IN_NOTEBOOK → 다시 조회. 403 → 변경 메뉴 숨김.
// 변경은 화면에 먼저 반영하고(이동이 바로 보이게) 실패하면 이전 묶음으로 되돌린 뒤 알린다. 한 번에 한 변경만 보낸다.
// 응답에 권한 값이 없으므로 canEdit(기본 true)이 거짓이거나 403을 받으면 만들기·묶음 메뉴·이동 단추를 숨긴다(notebook-overview와 같은 방식).
// 접힘 상태는 노트북별 브라우저 저장소(기본 localStorage)에 묶음 ID 목록으로 둔다. 읽기·쓰기 실패는 무시하고 이번 화면에서만 기억한다.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";
import { StudioIcon } from "./studio-icon.js";
import "./source-groups.css";

const STORAGE_PREFIX = "daon.source-groups.collapsed.";
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/u;

function defaultStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}
function readCollapsed(storage, notebookId) {
  if (!notebookId) return new Set();
  try {
    const value = JSON.parse(storage?.getItem?.(`${STORAGE_PREFIX}${notebookId}`) ?? "[]");
    return new Set(Array.isArray(value) ? value.filter((id) => typeof id === "string") : []);
  } catch { return new Set(); }
}
function writeCollapsed(storage, notebookId, collapsed) {
  if (!notebookId) return;
  try {
    if (collapsed.size) storage?.setItem?.(`${STORAGE_PREFIX}${notebookId}`, JSON.stringify([...collapsed]));
    else storage?.removeItem?.(`${STORAGE_PREFIX}${notebookId}`);
  } catch {
    // 저장이 막혀도 이번 화면에서는 접기가 동작한다.
  }
}

const validName = (name) => name.length >= 1 && name.length <= 80 && !CONTROL_CHARS.test(name);
const isForbidden = (error) => error?.code === "FORBIDDEN" || error?.status === 403;
const isConflict = (error) => error?.code === "SOURCE_GROUP_ETAG_MISMATCH" || error?.status === 412;
const defaultLabel = (source) => source?.filename ?? source?.sourceId ?? "";
const sortGroups = (groups) => [...groups].sort((a, b) => a.position - b.position);

// sourceId를 targetId 묶음 끝으로 옮긴다(targetId가 null이면 묶음 밖으로). 서버 PUT과 같은 결과를 화면에 먼저 보인다.
function moveLocal(groups, sourceId, targetId) {
  return groups.map((group) => {
    const without = group.source_ids.filter((id) => id !== sourceId);
    return { ...group, source_ids: group.group_id === targetId ? [...without, sourceId] : without };
  });
}

function GroupCheck({ label, state, disabled, onChange }) {
  return <input type="checkbox" className="source-use-check source-bundle__check" aria-label={label} aria-checked={state}
    checked={state === "true"} disabled={disabled} data-check-state={state}
    ref={(node) => { if (node) node.indeterminate = state === "mixed"; }} onChange={onChange} />;
}

export function SourceGroupsList({ studio, notebookId = null, sources = [], renderRow, isChecked, onSetChecked, refreshKey = null, canEdit = true,
  storage, sourceLabel = defaultLabel, listLabel = "Raw Source 목록" }) {
  const supported = typeof studio?.listSourceGroups === "function";
  const store = useMemo(() => (storage === undefined ? defaultStorage() : storage), [storage]);
  const [groups, setGroups] = useState(null);
  const [loadState, setLoadState] = useState("idle"); // idle | loading | loaded | error
  const [collapsed, setCollapsed] = useState(() => readCollapsed(store, notebookId));
  const [forbidden, setForbidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null); // { key, tone: "error" | "info" }
  const [editor, setEditor] = useState(null); // { mode: "create" | "rename" | "delete", groupId? }
  const [draft, setDraft] = useState("");
  const [nameError, setNameError] = useState(false);
  const [menu, setMenu] = useState(null); // { kind: "group" | "move", id }
  const [retryTick, setRetryTick] = useState(0);
  const etagRef = useRef(null);
  const groupsRef = useRef(null);
  const busyRef = useRef(false);
  const seqRef = useRef(0);
  const scopeRef = useRef(0);
  const mountedRef = useRef(true);
  const menuRef = useRef(null);
  const baseId = useId();
  groupsRef.current = groups;

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  // 노트북(또는 어댑터)이 바뀌면 이전 노트북의 묶음·권한 판단·안내를 버린다.
  useEffect(() => {
    scopeRef.current += 1;
    seqRef.current += 1;
    etagRef.current = null;
    busyRef.current = false;
    setGroups(null); setLoadState("idle"); setForbidden(false); setBusy(false); setNotice(null); setEditor(null); setMenu(null);
    setCollapsed(readCollapsed(store, notebookId));
  }, [studio, notebookId, store]);

  const load = async (signal) => {
    if (!supported) return false;
    const seq = ++seqRef.current;
    setLoadState((current) => (current === "loaded" ? current : "loading"));
    try {
      const result = await studio.listSourceGroups(signal ? { signal } : undefined);
      if (seq !== seqRef.current || !mountedRef.current) return false;
      etagRef.current = result.etag;
      setGroups(Array.isArray(result.groups) ? result.groups : []);
      setLoadState("loaded");
      return true;
    } catch {
      if (seq !== seqRef.current || !mountedRef.current || signal?.aborted) return false;
      setLoadState("error");
      return false;
    }
  };

  // 소스 목록이 바뀌면(떼어 내거나 삭제된 소스는 서버 조회에서 빠진다) 다시 읽는다.
  useEffect(() => {
    if (!supported) return undefined;
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    void load(controller?.signal);
    return () => controller?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studio, notebookId, refreshKey, retryTick, supported]);

  // 열린 메뉴 밖을 누르거나 Esc를 누르면 닫는다.
  useEffect(() => {
    if (!menu) return undefined;
    const doc = globalThis.document;
    const onDown = (event) => { if (menuRef.current && !menuRef.current.contains(event.target)) setMenu(null); };
    const onKey = (event) => { if (event.key === "Escape") setMenu(null); };
    doc?.addEventListener?.("mousedown", onDown);
    doc?.addEventListener?.("keydown", onKey);
    return () => { doc?.removeEventListener?.("mousedown", onDown); doc?.removeEventListener?.("keydown", onKey); };
  }, [menu]);

  const editable = supported && canEdit && !forbidden && loadState === "loaded" && typeof studio?.setSourceGroupMembers === "function";

  // 변경 한 번: optimistic(현재 묶음) → 화면에 먼저 보일 묶음, call(etag) → 어댑터 결과({groups, etag}) 또는 { reload: true }.
  const mutate = async (optimistic, call) => {
    if (busyRef.current || !groupsRef.current) return false;
    const scope = scopeRef.current;
    const before = groupsRef.current;
    busyRef.current = true;
    setBusy(true); setNotice(null); setMenu(null);
    if (optimistic) setGroups(optimistic(before));
    try {
      const result = await call(etagRef.current);
      if (scope !== scopeRef.current || !mountedRef.current) return false;
      if (result?.reload) await load();
      else if (result && Array.isArray(result.groups)) {
        seqRef.current += 1; // 앞서 보낸 조회의 늦은 응답이 이 결과를 덮지 않게 한다.
        etagRef.current = result.etag;
        setGroups(result.groups);
      }
      return true;
    } catch (error) {
      if (scope !== scopeRef.current || !mountedRef.current) return false;
      setGroups(before);
      if (isForbidden(error)) { setForbidden(true); setEditor(null); setNotice({ key: "notebook.source_groups.error.forbidden", tone: "error" }); }
      else if (isConflict(error)) { await load(); setNotice({ key: "notebook.source_groups.error.conflict", tone: "info" }); }
      else if (error?.code === "SOURCE_NOT_IN_NOTEBOOK") { await load(); setNotice({ key: "notebook.source_groups.error.not_in_notebook", tone: "error" }); }
      else if (error?.code === "SOURCE_GROUP_LIMIT") setNotice({ key: "notebook.source_groups.error.limit", tone: "error" });
      else setNotice({ key: "notebook.source_groups.error.save", tone: "error" });
      return false;
    } finally {
      if (scope === scopeRef.current) { busyRef.current = false; if (mountedRef.current) setBusy(false); }
    }
  };

  const moveSource = (source, target, current) => {
    const sourceId = source.sourceId;
    if (target) {
      const ids = [...target.source_ids.filter((id) => id !== sourceId), sourceId];
      void mutate((list) => moveLocal(list, sourceId, target.group_id),
        (etag) => studio.setSourceGroupMembers(target.group_id, ids, { etag }));
    } else if (current) {
      const ids = current.source_ids.filter((id) => id !== sourceId);
      void mutate((list) => moveLocal(list, sourceId, null),
        (etag) => studio.setSourceGroupMembers(current.group_id, ids, { etag }));
    }
  };

  const openEditor = (mode, group = null) => {
    setMenu(null); setNameError(false); setNotice(null);
    setDraft(mode === "rename" ? group.name : "");
    setEditor({ mode, groupId: group?.group_id ?? null });
  };
  const closeEditor = () => { setEditor(null); setNameError(false); };
  const submitName = async () => {
    if (!editor || busyRef.current) return;
    const name = draft.trim();
    if (!validName(name)) { setNameError(true); return; }
    setNameError(false);
    const ok = editor.mode === "create"
      ? await mutate(null, async () => { await studio.createSourceGroup(name); return { reload: true }; })
      : await mutate((list) => list.map((group) => (group.group_id === editor.groupId ? { ...group, name } : group)),
        (etag) => studio.updateSourceGroup(editor.groupId, { name, etag }));
    if (ok && mountedRef.current) closeEditor();
  };
  const confirmDelete = async () => {
    if (!editor || editor.mode !== "delete") return;
    const groupId = editor.groupId;
    const ok = await mutate((list) => list.filter((group) => group.group_id !== groupId),
      (etag) => studio.deleteSourceGroup(groupId, { etag }));
    if (ok && mountedRef.current) closeEditor();
  };

  const toggleCollapsed = (groupId) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(groupId)) next.delete(groupId); else next.add(groupId);
      writeCollapsed(store, notebookId, next);
      return next;
    });
  };

  const checked = (source) => (typeof isChecked === "function" ? Boolean(isChecked(source)) : false);
  const sorted = groups ? sortGroups(groups) : [];
  const bySourceId = new Map();
  for (const source of sources) {
    const list = bySourceId.get(source.sourceId) ?? [];
    list.push(source);
    bySourceId.set(source.sourceId, list);
  }
  const groupOf = new Map();
  for (const group of sorted) for (const id of group.source_ids) groupOf.set(id, group);

  const moveControl = (source) => {
    if (!editable || sorted.length === 0) return null;
    const current = groupOf.get(source.sourceId) ?? null;
    const key = `${source.sourceId}:${source.sourceVersionId}`;
    const open = menu?.kind === "move" && menu.id === key;
    const targets = sorted.filter((group) => group.group_id !== current?.group_id);
    return <span className="source-bundle__anchor" ref={open ? menuRef : undefined}>
      <button type="button" className="source-action-trigger source-bundle__move" title={msg("notebook.source_groups.move_menu")}
        aria-label={msg("notebook.source_groups.move", { name: sourceLabel(source) })} aria-haspopup="menu" aria-expanded={open} disabled={busy}
        onClick={() => setMenu(open ? null : { kind: "move", id: key })}><StudioIcon name="source_stack" size={18} /></button>
      {open ? <div className="source-bundle__menu" role="menu" aria-label={msg("notebook.source_groups.move_menu")}>
        {targets.map((group) => <button key={group.group_id} type="button" role="menuitem" onClick={() => moveSource(source, group, current)}>{group.name}</button>)}
        {current ? <button type="button" role="menuitem" className="source-bundle__menu-out" onClick={() => moveSource(source, null, current)}>{msg("notebook.source_groups.move_out")}</button> : null}
      </div> : null}
    </span>;
  };
  const row = (source) => renderRow(source, moveControl(source));

  const nameEditor = (mode) => <div className="source-bundle__editor" role="group" aria-label={msg(mode === "create" ? "notebook.source_groups.create" : "notebook.source_groups.rename")}>
    <input type="text" aria-label={msg("notebook.source_groups.name")} placeholder={msg("notebook.source_groups.name_placeholder")} value={draft} maxLength={80}
      autoFocus disabled={busy} onChange={(event) => { setDraft(event.target.value); setNameError(false); }}
      onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void submitName(); } else if (event.key === "Escape") closeEditor(); }} />
    <button type="button" className="primary-button" disabled={busy} onClick={() => void submitName()}>
      {msg(mode === "create" ? "notebook.source_groups.create_submit" : "notebook.source_groups.rename_submit")}</button>
    <button type="button" className="secondary-button" disabled={busy} onClick={closeEditor}>{msg("notebook.source_groups.cancel")}</button>
    {nameError ? <p className="source-bundles__notice is-error" role="alert">{msg("notebook.source_groups.name_invalid")}</p> : null}
  </div>;

  const toolbar = editable ? <div className="source-bundles__toolbar">
    <button type="button" className="source-bundles__create" disabled={busy} onClick={() => openEditor("create")}>
      <StudioIcon name="add" size={16} />{msg("notebook.source_groups.create")}</button>
  </div> : null;
  const notices = <>
    {editor?.mode === "create" && editable ? nameEditor("create") : null}
    {loadState === "error" ? <div className="source-bundles__notice is-error" role="alert">
      <span>{msg("notebook.source_groups.error.load")}</span>
      <button type="button" onClick={() => setRetryTick((value) => value + 1)}>{msg("notebook.source_groups.retry")}</button>
    </div> : null}
    {notice ? <div className={`source-bundles__notice ${notice.tone === "error" ? "is-error" : "is-info"}`} role={notice.tone === "error" ? "alert" : "status"}>
      <span>{msg(notice.key)}</span>
      <button type="button" className="source-bundles__dismiss" aria-label={msg("notebook.source_groups.dismiss")} onClick={() => setNotice(null)}>×</button>
    </div> : null}
    {busy ? <p className="source-bundles__saving" role="status">{msg("notebook.source_groups.saving")}</p> : null}
  </>;

  // 묶음이 없거나(또는 쓸 수 없으면) 기존 평면 목록 그대로.
  if (!supported || sorted.length === 0) {
    return <>
      {supported ? <>{toolbar}{notices}</> : null}
      <ul className="source-list" aria-label={listLabel}>{sources.map((source) => renderRow(source, null))}</ul>
    </>;
  }

  const ungrouped = sources.filter((source) => !groupOf.has(source.sourceId));
  return <div className="source-bundles">
    {toolbar}
    {notices}
    {sorted.map((group, index) => {
      const members = group.source_ids.flatMap((id) => bySourceId.get(id) ?? []);
      const ready = members.filter((source) => source.ready);
      const count = ready.filter(checked).length;
      const state = ready.length === 0 || count === 0 ? "false" : count === ready.length ? "true" : "mixed";
      const isCollapsed = collapsed.has(group.group_id);
      const listId = `${baseId}-group-${index}`;
      const menuOpen = menu?.kind === "group" && menu.id === group.group_id;
      return <section key={group.group_id} className="source-bundle" data-source-group-id={group.group_id}>
        <div className="source-bundle__header">
          <GroupCheck label={msg("notebook.source_groups.check", { name: group.name })} state={state} disabled={ready.length === 0}
            onChange={() => onSetChecked?.(ready, state !== "true")} />
          <button type="button" className="source-bundle__toggle" aria-expanded={!isCollapsed} aria-controls={listId}
            aria-label={msg(isCollapsed ? "notebook.source_groups.expand" : "notebook.source_groups.collapse", { name: group.name })}
            onClick={() => toggleCollapsed(group.group_id)}>
            <StudioIcon name={isCollapsed ? "chevron_right" : "chevron_down"} size={16} />
            <span className="source-bundle__name">{group.name}</span>
            <span className="source-bundle__count">{msg("notebook.source_groups.count", { count: members.length })}</span>
          </button>
          {editable ? <span className="source-bundle__anchor" ref={menuOpen ? menuRef : undefined}>
            <button type="button" className="source-action-trigger" aria-label={msg("notebook.source_groups.menu", { name: group.name })}
              aria-haspopup="menu" aria-expanded={menuOpen} disabled={busy} onClick={() => setMenu(menuOpen ? null : { kind: "group", id: group.group_id })}>
              <StudioIcon name="more_vertical" size={18} /></button>
            {menuOpen ? <div className="source-bundle__menu" role="menu" aria-label={msg("notebook.source_groups.menu", { name: group.name })}>
              <button type="button" role="menuitem" onClick={() => openEditor("rename", group)}>{msg("notebook.source_groups.rename")}</button>
              <button type="button" role="menuitem" className="is-danger" onClick={() => openEditor("delete", group)}>{msg("notebook.source_groups.delete")}</button>
            </div> : null}
          </span> : null}
        </div>
        {editable && editor?.mode === "rename" && editor.groupId === group.group_id ? nameEditor("rename") : null}
        {editable && editor?.mode === "delete" && editor.groupId === group.group_id ? <div className="source-bundle__editor" role="group" aria-label={msg("notebook.source_groups.delete")}>
          <p>{msg("notebook.source_groups.delete_confirm", { name: group.name })}</p>
          <button type="button" className="primary-button is-danger" disabled={busy} onClick={() => void confirmDelete()}>{msg("notebook.source_groups.delete_submit")}</button>
          <button type="button" className="secondary-button" disabled={busy} onClick={closeEditor}>{msg("notebook.source_groups.cancel")}</button>
        </div> : null}
        {isCollapsed ? null : members.length
          ? <ul className="source-list source-bundle__list" id={listId} aria-label={msg("notebook.source_groups.list", { name: group.name })}>{members.map(row)}</ul>
          : <p className="source-bundle__empty" id={listId}>{msg("notebook.source_groups.empty")}</p>}
      </section>;
    })}
    <div className="source-bundle__ungrouped"><h4>{msg("notebook.source_groups.ungrouped")}</h4><span>{ungrouped.length}</span></div>
    <ul className="source-list" aria-label={listLabel}>{ungrouped.map(row)}</ul>
  </div>;
}
