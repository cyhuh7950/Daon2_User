"use client";

import { useEffect, useRef, useState } from "react";
import { focusInitialModalControl, trapModalTab } from "./workspace-interaction.js";
import { msg, studioErrorMessage } from "./studio-messages.ko.js";

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
export function SettingsDialog({ type, typeLabel, initial = {}, onSubmit, onCancel }) {
  const properties = type?.settings_schema?.properties ?? {};
  const [focus, setFocus] = useState(String(initial.focus ?? ""));
  const [language, setLanguage] = useState(String(initial.language ?? "ko"));
  const [format, setFormat] = useState(String(initial.format_id ?? type?.default_format ?? ""));
  const [count, setCount] = useState(initial.count === undefined ? "" : String(initial.count));
  const [difficulty, setDifficulty] = useState(String(initial.difficulty ?? ""));
  const [length, setLength] = useState(String(initial.length ?? ""));
  const [custom, setCustom] = useState(String(initial.custom_instruction ?? ""));
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
    if (format === "custom" && custom.trim()) settings.custom_instruction = custom.trim();
    onSubmit({ formatId: format || undefined, settings });
  };
  const countRule = properties.count;
  return <Modal labelledBy="studio-settings-title" onClose={onCancel}>
    <form onSubmit={submit}>
      <h2 id="studio-settings-title">{msg("studio.dialog.settings.title", { type: typeLabel })}</h2>
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
        <button type="submit" className="studio-btn studio-btn--primary">{msg("studio.dialog.settings.submit")}</button>
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
  else if (content?.kind === "excerpt") body = <>{content.filename && <p><strong>{content.filename}</strong></p>}<pre style={{ whiteSpace: "pre-wrap" }}>{content.text ?? JSON.stringify(content.snapshot ?? {}, null, 2)}</pre></>;
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
