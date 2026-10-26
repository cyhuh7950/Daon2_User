import { useCallback, useEffect, useRef, useState } from "react";

// TTS 엔진 관리 화면(WO-F7T). api는 apps/web/lib/tts-engines-api.js 와 같은 모양을 주입한다.
// 규칙: API 키는 화면에 남기지 않는다(등록·교체 후 입력칸 비움, 목록에는 "키 있음"만). 기본 주소·예시는 두지 않는다.

const STATUS_LABEL = { verified: "연결됨", unverified: "확인 전", failed: "확인 실패", disabled: "사용 안 함", deployment: "배포 설정" };
const KIND_LABEL = { external_api: "외부 API", server_internal: "서버 내부", local: "로컬", local_runtime: "로컬 런타임" };
const ERROR_TEXT = {
  TTS_ENGINE_SLUG_INVALID: "식별자는 영문 소문자·숫자·-·_ 로 1~32자여야 합니다.",
  TTS_ENGINE_SLUG_EXISTS: "같은 식별자의 엔진이 이미 있습니다.",
  TTS_ENGINE_LABEL_INVALID: "이름을 1~60자로 입력해 주세요.",
  TTS_ENGINE_ENDPOINT_INVALID: "서버 주소 형식을 확인해 주세요(http 또는 https, 계정·쿼리 없음).",
  TTS_ENGINE_ENDPOINT_PRIVATE_DENIED: "사설·내부 주소는 이 환경에서 연결할 수 없습니다.",
  TTS_ENGINE_KIND_INVALID: "지원하지 않는 전송 구분입니다.",
  TTS_ENGINE_TIMEOUT_INVALID: "제한 시간은 5~600초여야 합니다.",
  TTS_ENGINE_VOICE_INVALID: "목소리 이름을 확인해 주세요(영문·숫자·._- 40자 이내).",
  TTS_ENGINE_CREDENTIAL_INVALID: "API 키는 8자 이상이어야 합니다.",
  TTS_ENGINE_VERSION_CONFLICT: "다른 곳에서 먼저 수정되었습니다. 새로고침 후 다시 시도해 주세요.",
  TTS_ENGINE_DISABLED: "사용 안 함 상태의 엔진은 기본으로 지정할 수 없습니다.",
  TTS_ENGINE_NOT_FOUND: "엔진을 찾을 수 없습니다.",
  TTS_ENGINE_CREDENTIAL_UNAVAILABLE: "저장된 키를 읽을 수 없습니다. 키를 다시 입력해 주세요.",
  TTS_ENGINE_UNREACHABLE: "음성 서버에 연결하지 못했습니다.",
  TTS_ENGINE_AUTH_FAILED: "음성 서버가 키를 거부했습니다.",
  TTS_VOICE_UNKNOWN: "서버에 없는 목소리가 선택되어 있습니다.",
  TTS_TIMEOUT: "음성 서버 응답이 늦습니다.",
};
const safeMessage = (error) => ERROR_TEXT[error?.code] ?? "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
// 외부 전송 정책의 "허용 목적지"에 넣어야 하는 호스트 이름(주소에서 뽑는다). 서버 내부 엔진은 정책 판정이 없다.
const policyHost = (engine) => {
  if (engine.provider_kind !== "external_api") return null;
  try { return new URL(engine.base_url).hostname; } catch { return null; }
};
const stamp = (value) => (value ? String(value).replace("T", " ").slice(0, 16) : "—");
const emptyForm = () => ({ slug: "", label: "", baseUrl: "", apiKey: "", providerKind: "external_api", timeoutSeconds: "120", voiceA: "", voiceB: "" });

function EngineDialog({ engine, onSubmit, onCancel, pending, error }) {
  const editing = Boolean(engine);
  const [form, setForm] = useState(() => (editing
    ? { ...emptyForm(), slug: engine.slug, label: engine.label, baseUrl: engine.base_url, providerKind: engine.provider_kind, timeoutSeconds: String(engine.timeout_seconds),
        voiceA: engine.voices.A, voiceB: engine.voices.B }
    : emptyForm()));
  const set = (patch) => setForm((current) => ({ ...current, ...patch }));
  const choices = editing ? engine.voice_choices : [];
  const valid = form.slug.trim() && form.label.trim() && form.baseUrl.trim() && form.voiceA.trim() && form.voiceB.trim();
  const voiceField = (label, key) => (choices.length > 0
    ? <label>{label}<select aria-label={label} value={form[key]} onChange={(event) => set({ [key]: event.target.value })}>
      {[...new Set([...choices, form[key]])].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
    : <label>{label}<input type="text" aria-label={label} maxLength={40} value={form[key]} onChange={(event) => set({ [key]: event.target.value })} /></label>);
  return <section className="connector-dialog" role="dialog" aria-modal="true" aria-label={editing ? "TTS 엔진 수정" : "TTS 엔진 등록"}>
    <h3>{editing ? "TTS 엔진 수정" : "TTS 엔진 등록"}</h3>
    <label>식별자<input type="text" aria-label="식별자" maxLength={32} disabled={editing} value={form.slug} onChange={(event) => set({ slug: event.target.value })} /></label>
    <label>이름<input type="text" aria-label="이름" maxLength={60} value={form.label} onChange={(event) => set({ label: event.target.value })} /></label>
    <label>서버 주소<input type="url" aria-label="서버 주소" autoComplete="off" value={form.baseUrl} onChange={(event) => set({ baseUrl: event.target.value })} /></label>
    <label>{editing ? "API 키 교체(비워 두면 유지)" : "API 키"}<input type="password" aria-label={editing ? "API 키 교체" : "API 키"} autoComplete="new-password" maxLength={4096}
      value={form.apiKey} onChange={(event) => set({ apiKey: event.target.value })} /></label>
    <label>전송 구분<select aria-label="전송 구분" value={form.providerKind} onChange={(event) => set({ providerKind: event.target.value })}>
      <option value="external_api">외부 API — 조직 외부 전송 정책의 허용 목적지에 서버 주소가 있어야 합니다</option>
      <option value="server_internal">서버 내부 — 조직이 직접 운영하는 서버(정책 판정 없이 허용)</option></select></label>
    <label>제한 시간(초)<input type="number" aria-label="제한 시간(초)" min={5} max={600} value={form.timeoutSeconds} onChange={(event) => set({ timeoutSeconds: event.target.value })} /></label>
    {voiceField("화자 A(진행자) 기본 목소리", "voiceA")}
    {voiceField("화자 B(설명자) 기본 목소리", "voiceB")}
    {editing ? null : <small>등록 후 “연결 확인”을 누르면 서버가 알려 주는 목소리 목록이 선택지에 채워집니다.</small>}
    {error ? <p role="alert" className="inline-alert">{error}</p> : null}
    <div className="connector-dialog-actions">
      <button type="button" onClick={onCancel} disabled={pending}>취소</button>
      <button type="button" disabled={!valid || pending} onClick={() => onSubmit(form)}>{editing ? "저장" : "등록"}</button>
    </div>
  </section>;
}

export function TtsEnginesPane({ api }) {
  const [state, setState] = useState({ status: "loading", engines: [], error: null });
  const [dialog, setDialog] = useState(null); // { type: "register" | "edit" | "disconnect", engine?, pending, error }
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const alive = useRef(true);

  const reload = useCallback(async () => {
    try {
      const engines = await api.list();
      if (alive.current) setState({ status: engines.length ? "ready" : "empty", engines, error: null });
    } catch (error) {
      if (alive.current) setState({ status: error?.status === 403 ? "forbidden" : "error", engines: [], error: safeMessage(error) });
    }
  }, [api]);

  useEffect(() => {
    alive.current = true;
    void reload();
    return () => { alive.current = false; };
  }, [reload]);

  const run = async (action, doneNotice) => {
    setDialog((current) => (current ? { ...current, pending: true, error: null } : current));
    try {
      await action();
      setDialog(null);
      if (doneNotice) setNotice(doneNotice);
      await reload();
    } catch (error) {
      setDialog((current) => (current ? { ...current, pending: false, error: safeMessage(error) } : current));
    }
  };

  const register = (form) => run(() => api.register({
    slug: form.slug, label: form.label, baseUrl: form.baseUrl, apiKey: form.apiKey, providerKind: form.providerKind,
    timeoutSeconds: form.timeoutSeconds, voiceA: form.voiceA, voiceB: form.voiceB }), "TTS 엔진을 등록했습니다. “연결 확인”을 실행해 주세요.");

  const edit = (engine, form) => run(() => {
    const patch = { label: form.label, voiceA: form.voiceA, voiceB: form.voiceB, providerKind: form.providerKind, timeoutSeconds: form.timeoutSeconds };
    if (form.baseUrl.trim() !== engine.base_url) patch.baseUrl = form.baseUrl;
    if (form.apiKey) patch.apiKey = form.apiKey;
    return api.update(engine.engine_id, engine.version, patch);
  }, `${engine.label}: 저장했습니다.${form.apiKey || form.baseUrl.trim() !== engine.base_url ? " 주소·키가 바뀌어 다시 확인이 필요합니다." : ""}`);

  const quick = async (engine, patch, message) => {
    setBusy(engine.engine_id);
    setNotice(null);
    try {
      await api.update(engine.engine_id, engine.version, patch);
      setNotice(message);
    } catch (error) {
      setNotice(`${engine.label}: ${safeMessage(error)}`);
    } finally {
      setBusy(null);
      await reload();
    }
  };

  const verify = async (engine) => {
    setBusy(engine.engine_id);
    setNotice(null);
    try {
      const result = await api.verify(engine.engine_id);
      setNotice(result.status === "verified"
        ? `${engine.label}: 연결을 확인했습니다. 합성이 되는지는 오디오 개요를 만들어 확인하세요.`
        : `${engine.label}: 연결을 확인하지 못했습니다 — ${ERROR_TEXT[result.error_code] ?? result.error_code ?? "원인 미상"}`);
    } catch (error) {
      setNotice(`${engine.label}: ${safeMessage(error)}`);
    } finally {
      setBusy(null);
      await reload();
    }
  };

  return <section className="connectors-pane" aria-labelledby="tts-engines-title">
    <header className="connectors-header">
      <h2 id="tts-engines-title">TTS 엔진</h2>
      <button type="button" onClick={() => setDialog({ type: "register", pending: false, error: null })} disabled={state.status === "forbidden"}>엔진 추가</button>
    </header>
    <p><small>오디오·동영상 개요의 음성 합성에 쓰는 서버입니다. 기본 엔진이 생성 설정의 기본값이 되고, 사용자는 생성할 때 엔진과 목소리를 고를 수 있습니다.</small></p>
    {notice ? <p role="status" className="context-selection-status">{notice}</p> : null}
    {state.status === "loading" ? <p role="status">불러오는 중…</p> : null}
    {state.status === "forbidden" ? <p role="alert">관리자만 TTS 엔진을 관리할 수 있습니다.</p> : null}
    {state.status === "error" ? <p role="alert">{state.error}</p> : null}
    {state.status === "empty" ? <p>등록된 TTS 엔진이 없습니다. “엔진 추가”로 음성 서버를 등록하면 오디오·동영상 개요를 만들 수 있습니다.</p> : null}
    {state.status === "ready" ? <table className="connectors-table">
      <thead><tr><th scope="col">이름</th><th scope="col">서버</th><th scope="col">상태</th><th scope="col">목소리 A / B</th><th scope="col">마지막 확인</th><th scope="col">작업</th></tr></thead>
      <tbody>{state.engines.map((engine) => {
        const managed = engine.source === "settings";
        const label = engine.label;
        return <tr key={engine.engine_id ?? `deployment-${engine.slug}`}>
          <td>{label}{engine.is_default ? <span className="connector-badge" title="생성 설정의 기본 엔진">기본</span> : null}<br /><small>{engine.slug}</small></td>
          <td><small>{engine.base_url}</small><br /><small>{KIND_LABEL[engine.provider_kind] ?? engine.provider_kind}{engine.has_credential ? " · 키 있음" : " · 키 없음"}</small>{policyHost(engine) ? <><br /><small title="설정 > 조직 > 외부 전송 정책 > 허용 목적지">허용 목적지 필요: {policyHost(engine)}</small></> : null}</td>
          <td><span className={`connector-status status-${engine.status}`}>{STATUS_LABEL[engine.status] ?? engine.status}</span>{engine.error_code ? <small> ({engine.error_code})</small> : null}</td>
          <td>{engine.voices.A} / {engine.voices.B}</td>
          <td>{stamp(engine.last_checked_at)}</td>
          <td>{managed ? <>
            <button type="button" aria-label={`${label} 연결 확인`} disabled={busy === engine.engine_id || engine.status === "disabled"} onClick={() => void verify(engine)}>
              {busy === engine.engine_id ? "처리 중…" : "연결 확인"}</button>
            {engine.is_default || engine.status === "disabled" ? null
              : <button type="button" aria-label={`${label} 기본으로 지정`} disabled={busy === engine.engine_id} onClick={() => void quick(engine, { isDefault: true }, `${label}: 기본 엔진으로 지정했습니다.`)}>기본으로</button>}
            <button type="button" aria-label={`${label} 수정`} onClick={() => setDialog({ type: "edit", engine, pending: false, error: null })}>수정</button>
            <button type="button" aria-label={`${label} ${engine.status === "disabled" ? "사용" : "사용 안 함"}`} disabled={busy === engine.engine_id}
              onClick={() => void quick(engine, { enabled: engine.status === "disabled" }, engine.status === "disabled" ? `${label}: 다시 사용합니다. 연결 확인을 실행해 주세요.` : `${label}: 사용을 중지했습니다.`)}>
              {engine.status === "disabled" ? "사용" : "사용 안 함"}</button>
            <button type="button" aria-label={`${label} 해제`} onClick={() => setDialog({ type: "disconnect", engine, pending: false, error: null })}>해제</button>
          </> : <small>배포 설정(수정 불가)</small>}</td>
        </tr>;
      })}</tbody>
    </table> : null}
    {dialog?.type === "register" ? <EngineDialog pending={dialog.pending} error={dialog.error} onCancel={() => setDialog(null)} onSubmit={(form) => void register(form)} /> : null}
    {dialog?.type === "edit" ? <EngineDialog engine={dialog.engine} pending={dialog.pending} error={dialog.error} onCancel={() => setDialog(null)} onSubmit={(form) => void edit(dialog.engine, form)} /> : null}
    {dialog?.type === "disconnect" ? <section className="connector-dialog" role="dialog" aria-modal="true" aria-label="TTS 엔진 해제">
      <p>“{dialog.engine.label}” 엔진을 해제할까요? 이미 만든 오디오·동영상 산출물은 유지되고, 새로 만들 때 이 엔진은 쓸 수 없습니다.</p>
      {dialog.error ? <p role="alert" className="inline-alert">{dialog.error}</p> : null}
      <button type="button" disabled={dialog.pending} onClick={() => setDialog(null)}>취소</button>
      <button type="button" disabled={dialog.pending} onClick={() => void run(() => api.disconnect(dialog.engine.engine_id), `${dialog.engine.label} 엔진을 해제했습니다.`)}>해제 확인</button>
    </section> : null}
  </section>;
}

export default TtsEnginesPane;
