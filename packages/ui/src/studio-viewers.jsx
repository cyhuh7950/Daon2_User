"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";

const LEVEL_COLORS = ["#3b6fd8", "#3fa37a", "#8e5bd1", "#b57b00", "#2a8ea3", "#c0453f"];

// 근거 번호 [S#]를 클릭 가능한 각주로 렌더한다. 근거가 없는 사실 문장은 "근거 미확인"으로 표시한다.
export function Refs({ refs = [], evidence = [], onOpen }) {
  const names = new Map(evidence.map((item) => [item.ref_id, item]));
  return <>{refs.map((ref, index) => {
    const item = names.get(ref);
    const label = msg("studio.evidence.label", { n: index + 1, name: item?.source_name ?? "", where: item?.locator_kind === "page" ? msg("dialog.page_suffix", { n: item.locator_value }) : item?.locator_value ?? "" }).trim();
    return <button key={ref} type="button" className="studio-ref" aria-label={label} onClick={() => onOpen?.(ref)}>[{index + 1}]</button>;
  })}</>;
}

const Unverified = ({ warnings, path }) => warnings?.some((w) => w.code === "UNVERIFIED_CLAIM" && w.path === path)
  ? <span className="studio-warning">{msg("studio.evidence.unverified")}</span> : null;

export function ReportViewer({ content, evidence, onOpenEvidence }) {
  const body = content.body ?? {};
  const warnings = content.warnings ?? [];
  return <article className="studio-report">
    {body.title && <h2 style={{ fontSize: 18 }}>{body.title}</h2>}
    {body.summary && <p>{body.summary}</p>}
    {(body.sections ?? []).map((section, si) => <section key={si}>
      <h3>{section.heading}</h3>
      {section.blocks.map((block, bi) => {
        const path = `sections[${si}].blocks[${bi}]`;
        if (block.type === "bullets") return <ul key={bi}>{block.items.map((item, ii) => <li key={ii}>{item}{ii === block.items.length - 1 && <><Refs refs={block.refs} evidence={evidence} onOpen={onOpenEvidence} /><Unverified warnings={warnings} path={path} /></>}</li>)}</ul>;
        if (block.type === "table") return <table key={bi} className="studio-table"><tbody>{block.rows.map((row, ri) => <tr key={ri}>{row.map((cell, ci) => ri === 0 ? <th key={ci}>{cell}</th> : <td key={ci}>{cell}</td>)}</tr>)}</tbody></table>;
        return <p key={bi}>{block.text}<Refs refs={block.refs} evidence={evidence} onOpen={onOpenEvidence} /><Unverified warnings={warnings} path={path} /></p>;
      })}
    </section>)}
  </article>;
}

export function TableViewer({ content, evidence, onOpenEvidence }) {
  const body = content.body ?? {};
  const columns = body.columns ?? [];
  const [sort, setSort] = useState({ key: null, dir: 1 });
  const [hidden, setHidden] = useState([]);
  const rows = useMemo(() => {
    const list = (body.rows ?? []).slice();
    if (!sort.key) return list;
    const numeric = columns.find((c) => c.key === sort.key)?.type === "number";
    const value = (row) => { const raw = row.cells?.[sort.key]?.value ?? ""; return numeric ? Number(String(raw).replaceAll(",", "")) || 0 : String(raw); };
    return list.sort((a, b) => (value(a) > value(b) ? 1 : value(a) < value(b) ? -1 : 0) * sort.dir);
  }, [body.rows, columns, sort]);
  const visible = columns.filter((c) => !hidden.includes(c.key));
  return <div>
    {body.title && <h2 style={{ fontSize: 18 }}>{body.title}</h2>}
    <div className="studio-row" role="group" aria-label={msg("viewer.columns")}>
      {columns.map((c) => <label key={c.key}><input type="checkbox" checked={!hidden.includes(c.key)}
        onChange={() => setHidden((list) => list.includes(c.key) ? list.filter((k) => k !== c.key) : [...list, c.key])} /> {c.label}</label>)}
    </div>
    <div style={{ overflowX: "auto" }}>
      <table className="studio-table">
        <thead><tr>{visible.map((c) => <th key={c.key} aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
          <button type="button" onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? -s.dir : 1 }))}>{c.label}</button></th>)}</tr></thead>
        <tbody>{rows.map((row, ri) => <tr key={ri}>{visible.map((c) => <td key={c.key}>{row.cells?.[c.key]?.value}
          <Refs refs={row.cells?.[c.key]?.refs} evidence={evidence} onOpen={onOpenEvidence} /></td>)}</tr>)}</tbody>
      </table>
    </div>
    {(body.notes ?? []).map((note, i) => <p key={i}><small>{note}</small></p>)}
  </div>;
}

// 가로 트리 배치(서버 layout_tree와 같은 규칙): x = 깊이 × 260, y = 잎 순서 × 64.
export function layoutTree(nodes) {
  const ids = new Set(nodes.map((n) => n.id));
  const children = new Map();
  for (const node of nodes) {
    const parent = ids.has(node.parent) ? node.parent : null;
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(node.id);
  }
  const positions = new Map();
  let cursor = 0;
  const place = (id, depth) => {
    const kids = children.get(id) ?? [];
    let y;
    if (kids.length === 0) { y = cursor * 64; cursor += 1; } else { const ys = kids.map((k) => place(k, depth + 1)); y = ys.reduce((a, b) => a + b, 0) / ys.length; }
    positions.set(id, { x: depth * 260, y, depth });
    return y;
  };
  for (const root of children.get(null) ?? []) place(root, 0);
  return positions;
}

export function MindMapViewer({ content, evidence, onOpenEvidence, onAskAboutNode }) {
  const nodes = content.body?.nodes ?? [];
  const positions = useMemo(() => layoutTree(nodes), [nodes]);
  const [collapsed, setCollapsed] = useState([]);
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState({ x: 20, y: 20, k: 1 });
  const drag = useRef(null);
  const childrenOf = useMemo(() => { const map = new Map(); nodes.forEach((n) => { if (n.parent) { if (!map.has(n.parent)) map.set(n.parent, []); map.get(n.parent).push(n.id); } }); return map; }, [nodes]);
  const hiddenIds = useMemo(() => {
    const out = new Set();
    const walk = (id) => (childrenOf.get(id) ?? []).forEach((k) => { out.add(k); walk(k); });
    collapsed.forEach(walk);
    return out;
  }, [collapsed, childrenOf]);
  const visibleNodes = nodes.filter((n) => !hiddenIds.has(n.id) && positions.has(n.id));
  const chosen = nodes.find((n) => n.id === selected);
  return <div>
    <div className="studio-row">
      <button type="button" className="studio-btn" onClick={() => setView((v) => ({ ...v, k: Math.min(2.5, v.k * 1.2) }))} aria-label={msg("viewer.zoom_in")}>＋</button>
      <button type="button" className="studio-btn" onClick={() => setView((v) => ({ ...v, k: Math.max(0.4, v.k / 1.2) }))} aria-label={msg("viewer.zoom_out")}>－</button>
      <button type="button" className="studio-btn" onClick={() => setView({ x: 20, y: 20, k: 1 })}>{msg("viewer.fit")}</button>
    </div>
    <svg className="studio-mindmap" role="img" aria-label={msg("viewer.mindmap")}
      onWheel={(event) => setView((v) => ({ ...v, k: Math.min(2.5, Math.max(0.4, v.k * (event.deltaY < 0 ? 1.1 : 0.9))) }))}
      onPointerDown={(event) => { drag.current = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y }; }}
      onPointerMove={(event) => { if (drag.current) setView((v) => ({ ...v, x: drag.current.vx + event.clientX - drag.current.x, y: drag.current.vy + event.clientY - drag.current.y })); }}
      onPointerUp={() => { drag.current = null; }}>
      <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
        {visibleNodes.map((n) => { const p = positions.get(n.id); const q = n.parent && positions.get(n.parent); return q && !hiddenIds.has(n.parent)
          ? <path key={`e-${n.id}`} d={`M${q.x + 200},${q.y + 20} C${q.x + 240},${q.y + 20} ${p.x - 20},${p.y + 20} ${p.x},${p.y + 20}`} fill="none" stroke="#9aa3b5" strokeWidth="2" /> : null; })}
        {visibleNodes.map((n) => { const p = positions.get(n.id); return <g key={n.id} transform={`translate(${p.x},${p.y})`} tabIndex={0} role="button"
          aria-label={`${n.label}${(childrenOf.get(n.id) ?? []).length ? (collapsed.includes(n.id) ? ` ${msg("viewer.collapsed")}` : "") : ""}`}
          onClick={() => setSelected(n.id)} onDoubleClick={() => setCollapsed((list) => list.includes(n.id) ? list.filter((x) => x !== n.id) : [...list, n.id])}
          onKeyDown={(event) => { if (event.key === "Enter") setSelected(n.id); if (event.key === " ") { event.preventDefault(); setCollapsed((list) => list.includes(n.id) ? list.filter((x) => x !== n.id) : [...list, n.id]); } }}>
          <rect width="200" height="40" rx="12" fill={LEVEL_COLORS[p.depth % LEVEL_COLORS.length]} stroke={selected === n.id ? "#ffffff" : "none"} strokeWidth="3" />
          <text x="100" y="25" textAnchor="middle">{n.label}</text></g>; })}
      </g>
    </svg>
    {chosen && <div className="studio-mindmap-detail">
      <strong>{chosen.label}</strong>{chosen.summary && <p>{chosen.summary}</p>}
      <Refs refs={chosen.refs} evidence={evidence} onOpen={onOpenEvidence} />
      <div className="studio-row">
        <button type="button" className="studio-btn" onClick={() => setCollapsed((list) => list.includes(chosen.id) ? list.filter((x) => x !== chosen.id) : [...list, chosen.id])}>{collapsed.includes(chosen.id) ? msg("viewer.expand") : msg("viewer.collapse")}</button>
        {onAskAboutNode && <button type="button" className="studio-btn studio-btn--primary"
          onClick={() => onAskAboutNode({ label: chosen.label, sourceVersionIds: (chosen.refs ?? []).map((r) => evidence.find((e) => e.ref_id === r)?.source_version_id).filter(Boolean) })}>{msg("viewer.ask_concept")}</button>}
      </div>
    </div>}
  </div>;
}

export function FlashcardsViewer({ content, evidence, onOpenEvidence, onAttempt }) {
  const original = content.body?.cards ?? [];
  const [order, setOrder] = useState(() => original.map((_, i) => i));
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [known, setKnown] = useState([]);
  const [unknown, setUnknown] = useState([]);
  const [only, setOnly] = useState(false);
  const list = only ? order.filter((i) => unknown.includes(i)) : order;
  const card = original[list[index]];
  const go = (delta) => { setIndex((i) => Math.max(0, Math.min(list.length - 1, i + delta))); setFlipped(false); };
  const mark = (isKnown) => {
    const idx = list[index];
    const nextKnown = isKnown ? [...new Set([...known, idx])] : known.filter((x) => x !== idx);
    const nextUnknown = isKnown ? unknown.filter((x) => x !== idx) : [...new Set([...unknown, idx])];
    setKnown(nextKnown); setUnknown(nextUnknown);
    onAttempt?.({ known: nextKnown, unknown: nextUnknown });
    if (index < list.length - 1) go(1);
  };
  if (!card) return <p>{only ? msg("viewer.cards.none_unknown") : msg("viewer.cards.none")}</p>;
  return <div onKeyDown={(event) => { if (event.key === "ArrowRight") go(1); if (event.key === "ArrowLeft") go(-1); }}>
    <button type="button" className="studio-card-face" aria-label={flipped ? msg("viewer.cards.back_label") : msg("viewer.cards.front_label")} onClick={() => setFlipped((v) => !v)}>
      {flipped ? card.back : card.front}
    </button>
    <p aria-live="polite">{msg("viewer.cards.progress", { index: index + 1, total: list.length, known: known.length, unknown: unknown.length })}</p>
    {flipped && <div><Refs refs={card.refs} evidence={evidence} onOpen={onOpenEvidence} /></div>}
    <div className="studio-row">
      <button type="button" className="studio-btn" onClick={() => go(-1)} disabled={index === 0}>{msg("viewer.prev")}</button>
      <button type="button" className="studio-btn" onClick={() => go(1)} disabled={index >= list.length - 1}>{msg("viewer.next")}</button>
      <button type="button" className="studio-btn" onClick={() => { setOrder((o) => o.slice().sort(() => Math.random() - 0.5)); setIndex(0); setFlipped(false); }}>{msg("viewer.shuffle")}</button>
      <button type="button" className="studio-btn studio-btn--primary" onClick={() => mark(true)}>{msg("viewer.known")}</button>
      <button type="button" className="studio-btn" onClick={() => mark(false)}>{msg("viewer.unknown")}</button>
      <label><input type="checkbox" checked={only} onChange={(event) => { setOnly(event.target.checked); setIndex(0); setFlipped(false); }} /> {msg("viewer.only_unknown")}</label>
    </div>
  </div>;
}

export function QuizViewer({ content, evidence, onOpenEvidence, onAttempt }) {
  const all = content.body?.questions ?? [];
  const [wrongOnly, setWrongOnly] = useState(false);
  const [wrong, setWrong] = useState([]);
  const questions = wrongOnly ? all.map((q, i) => ({ q, i })).filter(({ i }) => wrong.includes(i)) : all.map((q, i) => ({ q, i }));
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState(null);
  const [submitted, setSubmitted] = useState(false);
  const [answers, setAnswers] = useState([]);
  const current = questions[step];
  const finished = step >= questions.length;
  const submit = () => {
    const correct = selected === current.q.answer_index;
    setSubmitted(true);
    setAnswers((list) => [...list, { q_index: current.i, selected, correct }]);
  };
  const next = () => {
    const done = step + 1 >= questions.length;
    setStep((s) => s + 1); setSelected(null); setSubmitted(false);
    if (done) {
      const all2 = answers;
      const score = all2.filter((a) => a.correct).length;
      setWrong(all2.filter((a) => !a.correct).map((a) => a.q_index));
      onAttempt?.({ answers: all2, score, total: all2.length });
    }
  };
  if (questions.length === 0) return <p>{wrongOnly ? msg("viewer.quiz.none_wrong") : msg("viewer.quiz.none")}</p>;
  if (finished) {
    const score = answers.filter((a) => a.correct).length;
    return <div><h3>{msg("viewer.quiz.result", { score, total: answers.length })}</h3>
      <div className="studio-row">
        <button type="button" className="studio-btn" onClick={() => { setStep(0); setAnswers([]); setWrongOnly(false); }}>{msg("viewer.quiz.restart")}</button>
        {wrong.length > 0 && <button type="button" className="studio-btn studio-btn--primary" onClick={() => { setWrongOnly(true); setStep(0); setAnswers([]); }}>{msg("viewer.quiz.retry_wrong")}</button>}
      </div></div>;
  }
  return <div>
    <p><strong>{step + 1} / {questions.length}.</strong> {current.q.q}</p>
    {current.q.options.map((option, index) => <button key={index} type="button" className="studio-option" aria-pressed={selected === index} disabled={submitted}
      data-state={submitted ? (index === current.q.answer_index ? "correct" : selected === index ? "wrong" : undefined) : undefined} onClick={() => setSelected(index)}>
      {"①②③④"[index]} {option}</button>)}
    {submitted && <p role="status">{selected === current.q.answer_index ? msg("viewer.quiz.correct") : msg("viewer.quiz.incorrect")}{" "}{current.q.explanation}<Refs refs={current.q.refs} evidence={evidence} onOpen={onOpenEvidence} /></p>}
    <div className="studio-row">
      {!submitted ? <button type="button" className="studio-btn studio-btn--primary" disabled={selected === null} onClick={submit}>{msg("viewer.quiz.submit")}</button>
        : <button type="button" className="studio-btn studio-btn--primary" onClick={next}>{step + 1 >= questions.length ? msg("viewer.quiz.show_result") : msg("viewer.next")}</button>}
    </div>
  </div>;
}

export function SlidesViewer({ content, evidence, onOpenEvidence }) {
  const slides = content.body?.slides ?? [];
  const [index, setIndex] = useState(0);
  const [notes, setNotes] = useState(false);
  const slide = slides[index];
  if (!slide) return <p>{msg("viewer.slides.none")}</p>;
  return <div className="studio-slides">
    <div className="studio-thumbs" role="list">{slides.map((s, i) => <button key={i} role="listitem" type="button" className="studio-thumb" aria-current={i === index ? "true" : undefined} onClick={() => setIndex(i)}>{i + 1}. {s.title}</button>)}</div>
    <div>
      <div className="studio-slide" style={slide.layout === "title" ? { display: "flex", flexDirection: "column", justifyContent: "center", textAlign: "center" } : undefined}>
        <h4>{slide.title}</h4>
        {slide.layout === "table" && slide.table
          ? <table className="studio-table"><thead><tr>{slide.table.columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead><tbody>{slide.table.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table>
          : <ul style={slide.layout === "two_column" ? { columns: 2 } : slide.layout === "title" ? { listStyle: "none", padding: 0 } : undefined}>{slide.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>}
        <Refs refs={slide.refs} evidence={evidence} onOpen={onOpenEvidence} />
      </div>
      <div className="studio-row">
        <button type="button" className="studio-btn" disabled={index === 0} onClick={() => setIndex(index - 1)}>{msg("viewer.prev")}</button>
        <button type="button" className="studio-btn" disabled={index >= slides.length - 1} onClick={() => setIndex(index + 1)}>{msg("viewer.next")}</button>
        <button type="button" className="studio-btn" aria-pressed={notes} onClick={() => setNotes((v) => !v)}>{msg("viewer.slides.notes_toggle")}</button>
      </div>
      {notes && <p>{slide.notes || msg("viewer.slides.no_notes")}</p>}
    </div>
  </div>;
}

// 메모: 마크다운 텍스트 + 미리보기. 1.5초 디바운스로 자동 저장(새 리비전).
export function MemoViewer({ content, onSave }) {
  const initial = String(content.body?.markdown ?? "");
  const [text, setText] = useState(initial);
  const [state, setState] = useState("saved");
  const timer = useRef(null);
  const latest = useRef(initial);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const change = (value) => {
    setText(value); setState("pending");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try { await onSave?.({ ...content, body: { ...content.body, markdown: value } }); latest.current = value; setState("saved"); } catch { setState("error"); }
    }, 1500);
  };
  return <div className="studio-memo">
    <label htmlFor="studio-memo-text">{msg("viewer.memo.label")}</label>
    <textarea id="studio-memo-text" value={text} onChange={(event) => change(event.target.value)} />
    <small role="status">{state === "saved" ? msg("viewer.memo.saved") : state === "pending" ? msg("viewer.memo.pending") : msg("viewer.memo.failed")}</small>
    <pre aria-label={msg("viewer.memo.preview")}>{text}</pre>
  </div>;
}

// 인포그래픽(F7-01): 서버가 그린 PNG를 받아 이미지로 보여 준다(확대·축소·맞춤). 근거는 섹션별 각주로 이어진다.
export function InfographicViewer({ content, evidence, onOpenEvidence, onLoadImage }) {
  const body = content.body ?? {};
  const [image, setImage] = useState({ url: null, error: false });
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    let alive = true;
    let objectUrl = null;
    Promise.resolve(onLoadImage?.()).then((file) => {
      if (!alive || !file) return;
      objectUrl = globalThis.URL.createObjectURL(new Blob([file.bytes], { type: file.contentType || "image/png" }));
      setImage({ url: objectUrl, error: false });
    }).catch(() => { if (alive) setImage({ url: null, error: true }); });
    return () => { alive = false; if (objectUrl) globalThis.URL.revokeObjectURL(objectUrl); };
  }, [onLoadImage]);
  return <div className="studio-infographic">
    <div className="studio-row" role="group" aria-label={msg("viewer.image_controls")}>
      <button type="button" className="studio-btn" onClick={() => setZoom((z) => Math.min(3, z * 1.25))} aria-label={msg("viewer.zoom_in")}>＋</button>
      <button type="button" className="studio-btn" onClick={() => setZoom((z) => Math.max(0.4, z / 1.25))} aria-label={msg("viewer.zoom_out")}>－</button>
      <button type="button" className="studio-btn" onClick={() => setZoom(1)}>{msg("viewer.fit")}</button>
    </div>
    {image.error && <p role="alert">{msg("viewer.image_failed")}</p>}
    {!image.url && !image.error && <p role="status">{msg("viewer.image_loading")}</p>}
    {image.url && <div style={{ overflow: "auto", maxHeight: "70vh" }}>
      <img src={image.url} alt={body.title ? msg("viewer.infographic_alt", { title: body.title }) : msg("viewer.infographic")} style={{ width: `${zoom * 100}%`, maxWidth: "none" }} />
    </div>}
    <ol className="studio-infographic__sources">{(body.sections ?? []).map((section, index) => <li key={index}>
      <strong>{section.headline}</strong> <Refs refs={section.refs} evidence={evidence} onOpen={onOpenEvidence} />
    </li>)}</ol>
  </div>;
}

// 오디오 개요(F7-03·S2-13): mp3를 받아 재생기(재생·속도·구간 이동)와 스크립트 동기 표시를 보여 준다.
// 스크립트는 자막이자 접근성 대안이므로 항상 보인다. 줄을 누르면 그 줄부터 재생한다.
const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

export function activeLineIndex(script, currentMs) {
  let found = -1;
  for (let i = 0; i < script.length; i += 1) {
    if (typeof script[i].start_ms === "number" && script[i].start_ms <= currentMs) found = i;
    else break;
  }
  return found;
}

export function AudioViewer({ content, evidence, onOpenEvidence, onLoadAudio }) {
  const body = content.body ?? {};
  const script = body.script ?? [];
  const audioRef = useRef(null);
  const [audio, setAudio] = useState({ url: null, error: false });
  const [speed, setSpeed] = useState(1);
  const [active, setActive] = useState(-1);
  useEffect(() => {
    let alive = true;
    let objectUrl = null;
    Promise.resolve(onLoadAudio?.()).then((file) => {
      if (!alive || !file) return;
      objectUrl = globalThis.URL.createObjectURL(new Blob([file.bytes], { type: file.contentType || "audio/mpeg" }));
      setAudio({ url: objectUrl, error: false });
    }).catch(() => { if (alive) setAudio({ url: null, error: true }); });
    return () => { alive = false; if (objectUrl) globalThis.URL.revokeObjectURL(objectUrl); };
  }, [onLoadAudio]);
  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = speed; }, [speed, audio.url]);
  const seek = (line) => {
    const element = audioRef.current;
    if (!element || typeof line.start_ms !== "number") return;
    element.currentTime = line.start_ms / 1000;
    element.play?.().catch?.(() => {});
  };
  const total = Math.round((body.duration_ms ?? 0) / 1000);
  return <div className="studio-audio">
    {total > 0 && <small>{msg("viewer.audio.duration", { minutes: Math.floor(total / 60), seconds: total % 60 })}</small>}
    {audio.error && <p role="alert">{msg("viewer.audio.failed")}</p>}
    {!audio.url && !audio.error && <p role="status">{msg("viewer.audio.loading")}</p>}
    {audio.url && <div className="studio-row">
      <audio ref={audioRef} controls preload="metadata" src={audio.url} aria-label={msg("viewer.audio.player")}
        onTimeUpdate={(event) => setActive(activeLineIndex(script, event.currentTarget.currentTime * 1000))} />
      <label>{msg("viewer.audio.speed")}{" "}
        <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
          {SPEEDS.map((value) => <option key={value} value={value}>{value}×</option>)}
        </select>
      </label>
    </div>}
    <h3>{msg("viewer.audio.script")}</h3>
    <ol className="studio-audio__script">{script.map((line, index) => <li key={index} aria-current={index === active ? "true" : undefined}
      data-speaker={line.speaker} style={index === active ? { fontWeight: 700 } : undefined}>
      <strong>{msg(line.speaker === "B" ? "viewer.audio.speaker_b" : "viewer.audio.speaker_a")}</strong>{" "}
      <button type="button" className="studio-btn" onClick={() => seek(line)} disabled={!audio.url} aria-label={`${msg("viewer.audio.seek")}: ${line.text}`}>{line.text}</button>{" "}
      <Refs refs={line.refs} evidence={evidence} onOpen={onOpenEvidence} />
    </li>)}</ol>
  </div>;
}

// 동영상 개요(F7-05·S2-14): mp4를 받아 재생기(재생·속도)와 자막 트랙, 챕터 목록(현재 챕터 강조·클릭 이동)을 보여 준다.
export function activeChapterIndex(chapters, currentMs) {
  let found = -1;
  for (let i = 0; i < chapters.length; i += 1) {
    if (typeof chapters[i].start_ms === "number" && chapters[i].start_ms <= currentMs) found = i;
    else break;
  }
  return found;
}

export function VideoViewer({ content, evidence, onOpenEvidence, onLoadVideo, onLoadCaptions }) {
  const body = content.body ?? {};
  const scenes = body.scenes ?? [];
  const chapters = body.chapters ?? scenes.map((s) => ({ title: s.title, start_ms: s.start_ms }));
  const videoRef = useRef(null);
  const [media, setMedia] = useState({ url: null, captions: null, error: false });
  const [speed, setSpeed] = useState(1);
  const [active, setActive] = useState(-1);
  useEffect(() => {
    let alive = true;
    const urls = [];
    Promise.all([Promise.resolve(onLoadVideo?.()), Promise.resolve(onLoadCaptions?.()).catch(() => null)]).then(([file, captions]) => {
      if (!alive || !file) return;
      const url = globalThis.URL.createObjectURL(new Blob([file.bytes], { type: file.contentType || "video/mp4" }));
      urls.push(url);
      let captionUrl = null;
      if (captions) {
        captionUrl = globalThis.URL.createObjectURL(new Blob([captions.bytes], { type: "text/vtt" }));
        urls.push(captionUrl);
      }
      setMedia({ url, captions: captionUrl, error: false });
    }).catch(() => { if (alive) setMedia({ url: null, captions: null, error: true }); });
    return () => { alive = false; urls.forEach((u) => globalThis.URL.revokeObjectURL(u)); };
  }, [onLoadVideo, onLoadCaptions]);
  useEffect(() => { if (videoRef.current) videoRef.current.playbackRate = speed; }, [speed, media.url]);
  const seek = (chapter) => {
    const element = videoRef.current;
    if (!element || typeof chapter.start_ms !== "number") return;
    element.currentTime = chapter.start_ms / 1000;
    element.play?.().catch?.(() => {});
  };
  const total = Math.round((body.duration_ms ?? 0) / 1000);
  return <div className="studio-video">
    {total > 0 && <small>{msg("viewer.audio.duration", { minutes: Math.floor(total / 60), seconds: total % 60 })}</small>}
    {media.error && <p role="alert">{msg("viewer.video.failed")}</p>}
    {!media.url && !media.error && <p role="status">{msg("viewer.video.loading")}</p>}
    {media.url && <div>
      <video ref={videoRef} controls preload="metadata" src={media.url} aria-label={msg("viewer.video.player")} style={{ width: "100%", maxHeight: "60vh" }}
        onTimeUpdate={(event) => setActive(activeChapterIndex(chapters, event.currentTarget.currentTime * 1000))}>
        {media.captions && <track kind="captions" srcLang="ko" label={msg("viewer.video.captions")} src={media.captions} default />}
      </video>
      <label>{msg("viewer.audio.speed")}{" "}
        <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
          {SPEEDS.map((value) => <option key={value} value={value}>{value}×</option>)}
        </select>
      </label>
    </div>}
    <h3>{msg("viewer.video.chapters")}</h3>
    <ol className="studio-video__chapters">{chapters.map((chapter, index) => <li key={index} aria-current={index === active ? "true" : undefined}
      style={index === active ? { fontWeight: 700 } : undefined}>
      <button type="button" className="studio-btn" onClick={() => seek(chapter)} disabled={!media.url} aria-label={`${msg("viewer.video.seek")}: ${chapter.title}`}>{chapter.title}</button>{" "}
      <Refs refs={scenes[index]?.refs ?? []} evidence={evidence} onOpen={onOpenEvidence} />
    </li>)}</ol>
  </div>;
}

export function StudioViewer({ output, onOpenEvidence, onAskAboutNode, onAttempt, onSaveMemo, onLoadImage, onLoadAudio, onLoadVideo, onLoadCaptions }) {
  const content = output.revision?.content;
  if (!content) return <p>{msg("studio.card.generating")}</p>;
  const common = { content, evidence: output.evidence ?? [], onOpenEvidence };
  switch (output.type_id) {
    case "report": return <ReportViewer {...common} />;
    case "data_table": return <TableViewer {...common} />;
    case "mind_map": return <MindMapViewer {...common} onAskAboutNode={onAskAboutNode} />;
    case "flashcards": return <FlashcardsViewer {...common} onAttempt={(payload) => onAttempt?.("flashcard", payload)} />;
    case "quiz": return <QuizViewer {...common} onAttempt={(payload) => onAttempt?.("quiz", payload)} />;
    case "slides": return <SlidesViewer {...common} />;
    case "infographic": return <InfographicViewer {...common} onLoadImage={onLoadImage} />;
    case "audio_overview": return <AudioViewer {...common} onLoadAudio={onLoadAudio} />;
    case "video_overview": return <VideoViewer {...common} onLoadVideo={onLoadVideo} onLoadCaptions={onLoadCaptions} />;
    case "memo": return <MemoViewer content={content} onSave={onSaveMemo} />;
    default: return <p>{msg("viewer.unsupported")}</p>;
  }
}
