"use client";

import { useEffect, useRef, useState } from "react";
import { focusInitialModalControl, trapModalTab } from "./workspace-interaction.js";
import { msg, studioErrorMessage } from "./studio-messages.ko.js";
import { evidenceExcerptView } from "./studio-evidence-view.js";
import { tableSourceKind } from "./studio-panel-model.js";

const FORMAT_LABELS = { summary: msg("dialog.preset.summary"), briefing: msg("dialog.preset.briefing"), blog: msg("dialog.preset.blog"), study_guide: msg("dialog.preset.study_guide"), custom: msg("dialog.preset.custom") };
const DIFFICULTY = [["easy", msg("dialog.difficulty.easy")], ["normal", msg("dialog.difficulty.normal")], ["hard", msg("dialog.difficulty.hard")]];
const LENGTHS = [["short", msg("dialog.length.short")], ["normal", msg("dialog.length.normal")], ["long", msg("dialog.length.long")]];

function Modal({ labelledBy, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => { focusInitialModalControl(ref.current); }, []);
  return <div className="studio-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
    <div ref={ref} className="studio-dialog" role="dialog" aria-modal="true" aria-labelledby={labelledBy}
      onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); onClose?.(); } else trapModalTab(ref.current, event); }}>
      {children}
    </div>
  </div>;
}

// 내보내기 추가 인증(ST-T27): 조직 정책이 켜진 경우에만 열린다. 비밀번호는 서버에 한 번 보내고 화면에 남기지 않는다.
export function ExportStepUpDialog({ pending, error, onSubmit, onCancel }) {
  const ref = useRef(null);
  return <Modal labelledBy="studio-stepup-title" onClose={onCancel}>
    <h2 id="studio-stepup-title">{msg("dialog.stepup.title")}</h2>
    <p>{msg("dialog.stepup.body")}</p>
    <label htmlFor="studio-stepup-password">{msg("dialog.stepup.password")}</label>
    <input ref={ref} id="studio-stepup-password" type="password" autoComplete="current-password" disabled={pending} />
    {error ? <p role="alert">{error}</p> : null}
    <footer>
      <button type="button" className="studio-btn" disabled={pending} onClick={onCancel}>{msg("studio.dialog.settings.cancel")}</button>
      <button type="button" className="studio-btn studio-btn--primary" disabled={pending} onClick={() => { const value = ref.current?.value ?? ""; if (value) onSubmit(value); }}>{msg("dialog.stepup.submit")}</button>
    </footer>
  </Modal>;
}

export function ConfirmDeleteDialog({ onConfirm, onCancel }) {
  return <Modal labelledBy="studio-confirm-title" onClose={onCancel}>
    <h2 id="studio-confirm-title">{msg("studio.confirm.delete.title")}</h2>
    <p>{msg("studio.confirm.delete.body")}</p>
    <footer>
      <button type="button" className="studio-btn" onClick={onCancel}>{msg("studio.confirm.delete.cancel")}</button>
      <button type="button" className="studio-btn studio-btn--primary" onClick={onConfirm}>{msg("studio.confirm.delete.confirm")}</button>
    </footer>
  </Modal>;
}

// 유형별 settings_schema로 입력란을 만든다. 모두 선택 입력이며 빈 값은 보내지 않는다.
export function SettingsDialog({ type, typeLabel, initial = {}, loading = false, onSubmit, onCancel }) {
  const properties = type?.settings_schema?.properties ?? {};
  const [focus, setFocus] = useState(String(initial.focus ?? ""));
  const [language, setLanguage] = useState(String(initial.language ?? "ko"));
  const [format, setFormat] = useState(String(initial.format_id ?? type?.default_format ?? ""));
  const [count, setCount] = useState(initial.count === undefined ? "" : String(initial.count));
  const [difficulty, setDifficulty] = useState(String(initial.difficulty ?? ""));
  const [length, setLength] = useState(String(initial.length ?? ""));
  const [custom, setCustom] = useState(String(initial.custom_instruction ?? ""));
  const [pageRequest, setPageRequest] = useState(String(initial.page_request ?? ""));
  const pageRequestTouched = useRef(false);
  // 다시 만들기: 출력 상세를 읽어 온 뒤 지난 요청 글을 한 번 채운다(직접 입력했으면 덮어쓰지 않는다).
  useEffect(() => { if (!pageRequestTouched.current) setPageRequest(String(initial.page_request ?? "")); }, [initial.page_request]);
  const [confirmOutline, setConfirmOutline] = useState(initial.confirm_outline === "yes");
  const [engine, setEngine] = useState(String(initial.engine ?? ""));
  const [voiceA, setVoiceA] = useState(String(initial.voice_a ?? ""));
  const [voiceB, setVoiceB] = useState(String(initial.voice_b ?? ""));
  const submit = (event) => {
    event.preventDefault();
    const settings = {};
    if (focus.trim()) settings.focus = focus.trim();
    if (language && language !== "ko") settings.language = language;
    if (count !== "") settings.count = Number(count);
    if (difficulty) settings.difficulty = difficulty;
    if (length) settings.length = length;
    if (engine) settings.engine = engine;
    if (voiceA) settings.voice_a = voiceA;
    if (voiceB) settings.voice_b = voiceB;
    if (properties.page_request && pageRequest.trim()) settings.page_request = pageRequest.trim();
    if (format === "custom" && custom.trim()) settings.custom_instruction = custom.trim();
    // 구성 확인을 켜면 지난 확정 목록을 지운다(빈 값 = 지움). 남아 있으면 서버가 확정 목록을 먼저 써서 다시 멈추지 않는다.
    if (confirmOutline) { settings.confirm_outline = "yes"; settings.confirmed_outline = ""; }
    onSubmit({ formatId: format || undefined, settings });
  };
  const countRule = properties.count;
  const pageRequestMissing = Boolean(properties.page_request) && !pageRequest.trim();
  return <Modal labelledBy="studio-settings-title" onClose={onCancel}>
    <form onSubmit={submit}>
      <h2 id="studio-settings-title">{msg("studio.dialog.settings.title", { type: typeLabel })}</h2>
      {properties.confirm_outline && <label><input type="checkbox" checked={confirmOutline} onChange={(event) => setConfirmOutline(event.target.checked)} /> {msg(type?.type_id === "report" ? "studio.dialog.settings.confirm_outline" : "studio.dialog.settings.confirm_outline_make")}</label>}
      {(type?.presets ?? []).length > 0 && <>
        <label htmlFor="studio-format">{msg("studio.dialog.settings.format")}</label>
        <select id="studio-format" value={format} onChange={(event) => setFormat(event.target.value)}>
          {type.presets.map((preset) => <option key={preset} value={preset}>{FORMAT_LABELS[preset] ?? preset}</option>)}
        </select>
        {format === "custom" && <>
          <label htmlFor="studio-custom">{msg("dialog.custom_instruction")}</label>
          <textarea id="studio-custom" maxLength={1000} required value={custom} onChange={(event) => setCustom(event.target.value)} />
        </>}
      </>}
      {properties.page_request && <>
        <label htmlFor="studio-page-request">{msg("studio.web_page.request")}</label>
        <textarea id="studio-page-request" maxLength={2000} required value={pageRequest} onChange={(event) => { pageRequestTouched.current = true; setPageRequest(event.target.value); }} aria-describedby="studio-page-request-hint" />
        <small id="studio-page-request-hint">{msg("studio.web_page.request.hint")} ({pageRequest.length}/2000)</small>
      </>}
      {countRule && <>
        <label htmlFor="studio-count">{msg("studio.dialog.settings.count")}</label>
        <input id="studio-count" type="number" min={countRule.minimum} max={countRule.maximum} value={count} placeholder={msg("dialog.auto")}
          onChange={(event) => setCount(event.target.value)} />
      </>}
      {properties.difficulty && <>
        <label htmlFor="studio-difficulty">{msg("studio.dialog.settings.difficulty")}</label>
        <select id="studio-difficulty" value={difficulty} onChange={(event) => setDifficulty(event.target.value)}>
          <option value="">{msg("dialog.auto")}</option>{DIFFICULTY.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </>}
      {properties.length && <>
        <label htmlFor="studio-length">{msg("studio.dialog.settings.length")}</label>
        <select id="studio-length" value={length} onChange={(event) => setLength(event.target.value)}>
          <option value="">{msg("dialog.auto")}</option>{LENGTHS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </>}
      {properties.engine?.enum && <>
        <label htmlFor="studio-tts-engine">{msg("dialog.tts.engine")}</label>
        <select id="studio-tts-engine" value={engine} onChange={(event) => setEngine(event.target.value)}>
          <option value="">{msg("dialog.auto")}</option>{properties.engine.enum.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </>}
      {properties.voice_a?.enum && <>
        <label htmlFor="studio-tts-voice-a">{msg(type?.type_id === "video_overview" ? "dialog.tts.narrator" : "dialog.tts.voice_a")}</label>
        <select id="studio-tts-voice-a" value={voiceA} onChange={(event) => setVoiceA(event.target.value)}>
          <option value="">{msg("dialog.auto")}</option>{properties.voice_a.enum.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </>}
      {properties.voice_b?.enum && <>
        <label htmlFor="studio-tts-voice-b">{msg("dialog.tts.voice_b")}</label>
        <select id="studio-tts-voice-b" value={voiceB} onChange={(event) => setVoiceB(event.target.value)}>
          <option value="">{msg("dialog.auto")}</option>{properties.voice_b.enum.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </>}
      <label htmlFor="studio-language">{msg("studio.dialog.settings.language")}</label>
      <select id="studio-language" value={language} onChange={(event) => setLanguage(event.target.value)}>
        <option value="ko">{msg("dialog.language.ko")}</option><option value="en">English</option>
      </select>
      <label htmlFor="studio-focus">{msg("studio.dialog.settings.focus")}</label>
      <textarea id="studio-focus" maxLength={500} value={focus} onChange={(event) => setFocus(event.target.value)} aria-describedby="studio-focus-hint" />
      <small id="studio-focus-hint">{msg("studio.dialog.settings.focus.hint")} ({focus.length}/500)</small>
      <footer>
        <button type="button" className="studio-btn" onClick={onCancel}>{msg("studio.dialog.settings.cancel")}</button>
        <button type="submit" className="studio-btn studio-btn--primary" disabled={pageRequestMissing || loading}>{msg("studio.dialog.settings.submit")}</button>
      </footer>
    </form>
  </Modal>;
}

export const AGGREGATION_REQUEST_MAX = 2000;
const validHeaderRow = (value) => /^\d{1,2}$/u.test(String(value)) && Number(value) >= 1 && Number(value) <= 50;

// 데이터 집계(WO-N9) 설정 창: 요청 글(필수·2000자) + 표 소스(XLSX·CSV만) + 시트(XLSX만, 표 정보에서) + 머리글 행(1~50).
// sources는 이미 고를 수 있는 표 소스만 받는다. loadProfile({ sourceVersionId, sheet, headerRow })는 표 정보(시트·열·행 수)를 돌려준다.
// lockSource: 설정 변경 후 다시 생성에서는 표 소스를 바꿀 수 없다(지금 소스를 보이고 잠근다, 검토 Ruling).
export function AggregationSettingsDialog({ typeLabel, sources = [], initial = {}, loading = false, lockSource = false, loadProfile, onSubmit, onCancel }) {
  const [request, setRequest] = useState(String(initial.aggregation_request ?? ""));
  // 다시 생성(lockSource)은 지난 표 소스만 쓴다. 읽지 못했으면 첫 소스로 채우지 않는다(서버도 출력 소스와 다른 표는 거부한다).
  const [sourceId, setSourceId] = useState(String(initial.table_source_version_id ?? (lockSource ? "" : sources[0]?.sourceVersionId ?? "")));
  const [sheet, setSheet] = useState(String(initial.sheet ?? ""));
  const [headerRow, setHeaderRow] = useState(String(initial.header_row ?? 1));
  const [profile, setProfile] = useState({ status: "idle", data: null, error: null });
  // 시트 목록은 표 정보 오류(고른 시트를 못 읽음·503)가 나도 남겨 다른 시트를 고를 수 있게 한다. 소스가 바뀔 때만 비운다.
  const [sheetList, setSheetList] = useState([]);
  const [retry, setRetry] = useState(0);
  const touched = useRef(false);
  const skipKey = useRef(null);
  // 다시 만들기: 출력 상세를 읽은 뒤 지난 설정을 한 번 채운다(직접 바꿨으면 덮어쓰지 않는다).
  useEffect(() => {
    if (loading || touched.current) return;
    if (initial.aggregation_request !== undefined) setRequest(String(initial.aggregation_request ?? ""));
    if (initial.table_source_version_id) setSourceId(String(initial.table_source_version_id));
    if (initial.sheet !== undefined) setSheet(String(initial.sheet ?? ""));
    if (initial.header_row !== undefined) setHeaderRow(String(initial.header_row));
  }, [loading, initial.aggregation_request, initial.table_source_version_id, initial.sheet, initial.header_row]);
  const touch = (setter) => (event) => { touched.current = true; setter(event.target.value); };
  const source = sources.find((item) => item.sourceVersionId === sourceId) ?? null;
  const kind = tableSourceKind(source);
  const headerOk = validHeaderRow(headerRow);
  useEffect(() => {
    if (loading || !source || !headerOk || typeof loadProfile !== "function") { setProfile({ status: "idle", data: null, error: null }); return undefined; }
    const requestSheet = kind === "xlsx" ? sheet : "";
    const key = `${sourceId}|${requestSheet}|${Number(headerRow)}`;
    if (skipKey.current === key) { skipKey.current = null; return undefined; }
    let alive = true;
    setProfile((current) => ({ status: "loading", data: current.data, error: null }));
    const timer = setTimeout(() => {
      Promise.resolve(loadProfile({ sourceVersionId: sourceId, sheet: requestSheet || undefined, headerRow: Number(headerRow) }))
        .then((data) => {
          if (!alive) return;
          setProfile({ status: "ready", data, error: null });
          const sheets = Array.isArray(data?.sheets) ? data.sheets : [];
          setSheetList(sheets);
          // 시트를 아직 고르지 않았으면 서버가 읽은 첫 시트를 고른 것으로 보인다(같은 표라 다시 읽지 않는다).
          if (kind === "xlsx" && !requestSheet && sheets.length) { skipKey.current = `${sourceId}|${sheets[0]}|${Number(headerRow)}`; setSheet(sheets[0]); }
        })
        .catch((error) => { if (alive) setProfile({ status: "error", data: null, error: error?.code ?? "STUDIO_REQUEST_FAILED" }); });
    }, 300);
    return () => { alive = false; clearTimeout(timer); };
  }, [loading, sourceId, sheet, headerRow, kind, retry, loadProfile]);
  const sheets = sheetList;
  const requestMissing = !request.trim();
  const profileLoading = profile.status === "loading";
  // 고른 시트를 표로 못 읽음(TABLE_*): 만들기를 끈다. 503 바쁨(status error)은 다시 읽기만 보이고 만들기는 끄지 않는다.
  const tableError = profile.status === "ready" && typeof profile.data?.error_code === "string" ? profile.data.error_code : null;
  const sourceUnknown = lockSource && !loading && !source;
  const blocked = requestMissing || !source || !headerOk || profileLoading || loading || Boolean(tableError);
  const submit = (event) => {
    event.preventDefault();
    if (blocked) return;
    // sheet는 CSV면 빈 값으로 보내 지난 시트 설정을 지운다(서버는 빈 값을 저장하지 않는다).
    onSubmit({ formatId: undefined, settings: { aggregation_request: request.trim(), table_source_version_id: sourceId,
      sheet: kind === "xlsx" ? sheet : "", header_row: Number(headerRow) } });
  };
  return <Modal labelledBy="studio-settings-title" onClose={onCancel}>
    <form onSubmit={submit} data-aggregation-settings="">
      <h2 id="studio-settings-title">{msg("studio.dialog.settings.title", { type: typeLabel })}</h2>
      <label htmlFor="studio-aggregation-request">{msg("studio.aggregation.request")}</label>
      <textarea id="studio-aggregation-request" maxLength={AGGREGATION_REQUEST_MAX} required value={request} onChange={touch(setRequest)} aria-describedby="studio-aggregation-request-hint" />
      <small id="studio-aggregation-request-hint">{msg("studio.aggregation.request.hint")} ({request.length}/{AGGREGATION_REQUEST_MAX})</small>
      <label htmlFor="studio-aggregation-source">{msg("studio.aggregation.source")}</label>
      {sources.length === 0
        ? <p role="note">{msg("studio.aggregation.source.none")}</p>
        : <select id="studio-aggregation-source" required disabled={lockSource} value={source || lockSource ? sourceId : ""}
          onChange={(event) => { touched.current = true; setSourceId(event.target.value); setSheet(""); setSheetList([]); }}>
          {!source && !lockSource && <option value="">{msg("studio.aggregation.source.choose")}</option>}
          {!source && lockSource && <option value={sourceId}>{sourceId || "-"}</option>}
          {sources.map((item) => <option key={item.sourceVersionId} value={item.sourceVersionId}>{item.filename ?? item.sourceVersionId}</option>)}
        </select>}
      {sourceUnknown && <p role="alert">{msg("studio.aggregation.source.unknown")}</p>}
      {kind === "xlsx" && <>
        <label htmlFor="studio-aggregation-sheet">{msg("studio.aggregation.sheet")}</label>
        <select id="studio-aggregation-sheet" value={sheet} disabled={sheets.length === 0} onChange={touch(setSheet)}>
          {(sheets.length === 0 || (sheet && !sheets.includes(sheet))) && <option value={sheet}>{sheet}</option>}
          {sheets.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </>}
      <label htmlFor="studio-aggregation-header-row">{msg("studio.aggregation.header_row")}</label>
      <input id="studio-aggregation-header-row" type="number" min={1} max={50} step={1} required value={headerRow} onChange={touch(setHeaderRow)} />
      {profileLoading && <p role="status">{msg("studio.aggregation.profile.loading")}</p>}
      {tableError && <p role="alert">{studioErrorMessage(tableError)}</p>}
      {profile.status === "ready" && !tableError && Array.isArray(profile.data?.columns) && <p role="status">{msg("studio.aggregation.profile.summary", { columns: profile.data.columns.length, rows: profile.data.row_count })}</p>}
      {profile.status === "error" && <p role="alert">{studioErrorMessage(profile.error)} <button type="button" className="studio-btn" onClick={() => setRetry((n) => n + 1)}>{msg("studio.aggregation.profile.retry")}</button></p>}
      <footer>
        <button type="button" className="studio-btn" onClick={onCancel}>{msg("studio.dialog.settings.cancel")}</button>
        <button type="submit" className="studio-btn studio-btn--primary" disabled={blocked}>{msg("studio.dialog.settings.submit")}</button>
      </footer>
    </form>
  </Modal>;
}

export function ProvenanceDialog({ load, onOpenEvidence, onRegenerate, onClose }) {
  const [state, setState] = useState({ status: "loading", data: null, error: null });
  useEffect(() => {
    let alive = true;
    load().then((data) => { if (alive) setState({ status: "ready", data, error: null }); })
      .catch((error) => { if (alive) setState({ status: "error", data: null, error: error?.code }); });
    return () => { alive = false; };
  }, [load]);
  const data = state.data;
  return <Modal labelledBy="studio-prov-title" onClose={onClose}>
    <h2 id="studio-prov-title">{msg("studio.dialog.provenance.title")}</h2>
    {state.status === "loading" && <p role="status">…</p>}
    {state.status === "error" && <p role="alert">{studioErrorMessage(state.error)}</p>}
    {data && <dl>
      <dt>{msg("dialog.prov.type_format")}</dt><dd>{data.type_id}{data.format_id ? ` · ${FORMAT_LABELS[data.format_id] ?? data.format_id}` : ""}</dd>
      <dt>{msg("studio.dialog.provenance.instruction")}</dt>
      <dd>{data.instruction?.focus ? msg("dialog.prov.focus", { focus: data.instruction.focus }) : msg("dialog.prov.no_focus")}{data.instruction?.customization_applied ? ` · ${msg("dialog.prov.customization")}` : ""}</dd>
      <dt>{msg("dialog.prov.settings")}</dt><dd>{Object.keys(data.settings ?? {}).length ? JSON.stringify(data.settings) : msg("dialog.prov.default_settings")}</dd>
      <dt>{msg("studio.dialog.provenance.sources")}</dt>
      <dd>{data.sources.length === 0 ? msg("dialog.none") : <ul>{data.sources.map((source) => <li key={source.source_version_id}>
        {source.name ?? source.source_version_id}{source.changed && <span className="studio-warning">{msg("studio.dialog.provenance.changed")}</span>}</li>)}</ul>}</dd>
      <dt>{msg("studio.dialog.provenance.evidence")}</dt>
      <dd>{data.evidence.length === 0 ? msg("dialog.none") : <ul>{data.evidence.map((item) => <li key={item.ref_id}>
        <button type="button" className="studio-ref" style={{ verticalAlign: "baseline" }} onClick={() => onOpenEvidence?.(item.ref_id)}>[{item.ref_id}]</button>
        {" "}{item.locator_kind === "page" ? msg("dialog.page_suffix", { n: item.locator_value }) : item.locator_value ?? ""}</li>)}</ul>}</dd>
    </dl>}
    <footer>
      {data && onRegenerate && <button type="button" className="studio-btn" onClick={() => onRegenerate(data.settings ?? {})}>{msg("studio.dialog.provenance.regenerate")}</button>}
      <button type="button" className="studio-btn studio-btn--primary" onClick={onClose}>{msg("studio.dialog.close")}</button>
    </footer>
  </Modal>;
}

export function ShareDialog({ load, onClose }) {
  const [sharing, setSharing] = useState(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => { let alive = true; load?.().then((data) => { if (alive) setSharing(data); }).catch(() => {}); return () => { alive = false; }; }, [load]);
  const copy = async () => {
    try { await globalThis.navigator?.clipboard?.writeText(globalThis.location?.href ?? ""); setCopied(true); } catch { setCopied(false); }
  };
  return <Modal labelledBy="studio-share-title" onClose={onClose}>
    <h2 id="studio-share-title">{msg("studio.dialog.share.title")}</h2>
    <p>{msg("studio.dialog.share.body")}</p>
    {sharing?.public_link === false && <p><small>{msg("dialog.share.no_public_link")}</small></p>}
    <footer>
      <button type="button" className="studio-btn" onClick={copy}>{copied ? msg("dialog.copied") : msg("studio.dialog.share.copy")}</button>
      <button type="button" className="studio-btn studio-btn--primary" onClick={onClose}>{msg("studio.dialog.close")}</button>
    </footer>
  </Modal>;
}

export function EvidenceDialog({ load, title, onClose }) {
  const [state, setState] = useState({ status: "loading", content: null, error: null });
  const urlRef = useRef(null);
  useEffect(() => {
    let alive = true;
    load().then((content) => { if (alive) setState({ status: "ready", content, error: null }); })
      .catch((error) => { if (alive) setState({ status: "error", content: null, error: error?.code }); });
    return () => { alive = false; if (urlRef.current) globalThis.URL?.revokeObjectURL?.(urlRef.current); };
  }, [load]);
  const { content } = state;
  let body = <p role="status">…</p>;
  if (state.status === "error") body = <p role="alert">{studioErrorMessage(state.error)}</p>;
  else if (content?.kind === "excerpt") {
    const view = evidenceExcerptView(content);
    body = <>{view.title && <p><strong>{view.title}</strong></p>}{view.label && <p>{view.label}</p>}<pre style={{ whiteSpace: "pre-wrap" }}>{view.text || msg("dialog.none")}</pre></>;
  }
  else if (content?.kind === "binary") {
    const blob = new Blob([content.bytes], { type: content.contentType });
    urlRef.current = globalThis.URL.createObjectURL(blob);
    body = <p><a href={`${urlRef.current}${content.page ? `#page=${content.page}` : ""}`} target="_blank" rel="noopener noreferrer">{msg("dialog.open_original")}{content.page ? ` (${msg("dialog.page_suffix", { n: content.page })})` : ""}</a></p>;
  }
  return <Modal labelledBy="studio-evidence-title" onClose={onClose}>
    <h2 id="studio-evidence-title">{title}</h2>
    {body}
    <footer><button type="button" className="studio-btn studio-btn--primary" onClick={onClose}>{msg("studio.dialog.close")}</button></footer>
  </Modal>;
}
