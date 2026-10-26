"use client";

import { useState } from "react";
import { StudioIcon } from "./studio-icon.js";
import { msg } from "./studio-messages.ko.js";

// 산출물 편집기(S2-11): 보고서·슬라이드·플래시카드·퀴즈의 본문을 고쳐 새 리비전으로 저장한다.
// 근거 번호(refs)는 그대로 유지되고, 서버가 구조와 근거 라벨을 다시 정리한다. 서버 상한: 보고서 문장 5000자, 카드 앞면 300·뒷면 800자 등.

export const EDITABLE_TYPES = ["report", "slides", "flashcards", "quiz"];

const lines = (value) => String(value ?? "").split("\n").map((line) => line.trim()).filter(Boolean);
const update = (list, index, patch) => list.map((item, i) => (i === index ? { ...item, ...patch } : item));
const remove = (list, index) => list.filter((_, i) => i !== index);

function ReportEditor({ body, onChange }) {
  const sections = body.sections ?? [];
  const setSection = (si, patch) => onChange({ ...body, sections: update(sections, si, patch) });
  const setBlock = (si, bi, patch) => setSection(si, { blocks: update(sections[si].blocks, bi, patch) });
  return <div>
    <label>{msg("editor.report.title")}<input aria-label={msg("editor.report.title.label")} value={body.title ?? ""} maxLength={200} onChange={(event) => onChange({ ...body, title: event.target.value })} style={{ width: "100%" }} /></label>
    <label>{msg("editor.report.summary")}<textarea aria-label={msg("editor.report.summary.label")} rows={3} value={body.summary ?? ""} maxLength={2000} onChange={(event) => onChange({ ...body, summary: event.target.value })} style={{ width: "100%" }} /></label>
    {sections.map((section, si) => <fieldset key={si} style={{ border: "1px solid var(--studio-border, #8883)", margin: "8px 0", padding: 8 }}>
      <legend>{msg("editor.report.section", { n: si + 1 })}</legend>
      <input aria-label={msg("editor.report.section.title", { n: si + 1 })} value={section.heading ?? ""} maxLength={160} onChange={(event) => setSection(si, { heading: event.target.value })} style={{ width: "100%" }} />
      {section.blocks.map((block, bi) => <div key={bi}>
        {block.type === "paragraph" && <textarea aria-label={msg("editor.report.paragraph", { n: si + 1, b: bi + 1 })} rows={4} value={block.text ?? ""} maxLength={5000}
          onChange={(event) => setBlock(si, bi, { text: event.target.value })} style={{ width: "100%" }} />}
        {block.type === "bullets" && <textarea aria-label={msg("editor.report.bullets", { n: si + 1, b: bi + 1 })} rows={Math.max(3, (block.items ?? []).length + 1)} value={(block.items ?? []).join("\n")}
          onChange={(event) => setBlock(si, bi, { items: lines(event.target.value) })} style={{ width: "100%" }} />}
        {block.type === "table" && <p><small>{msg("editor.report.table_locked")}</small></p>}
        <button type="button" className="studio-icon-button" aria-label={msg("editor.report.block.delete", { n: si + 1, b: bi + 1 })} onClick={() => setSection(si, { blocks: remove(section.blocks, bi) })}><StudioIcon name="delete" size={16} /></button>
      </div>)}
      <button type="button" className="studio-btn" onClick={() => setSection(si, { blocks: [...section.blocks, { type: "paragraph", text: "", refs: [] }] })}>{msg("editor.report.paragraph.add")}</button>
      <button type="button" className="studio-icon-button" aria-label={msg("editor.report.section.delete", { n: si + 1 })} disabled={sections.length <= 1} onClick={() => onChange({ ...body, sections: remove(sections, si) })}><StudioIcon name="delete" size={16} /></button>
    </fieldset>)}
  </div>;
}

function SlidesEditor({ body, onChange }) {
  const slides = body.slides ?? [];
  const set = (index, patch) => onChange({ ...body, slides: update(slides, index, patch) });
  return <div>{slides.map((slide, index) => <fieldset key={index} style={{ border: "1px solid var(--studio-border, #8883)", margin: "8px 0", padding: 8 }}>
    <legend>{msg("editor.slides.legend", { n: index + 1 })}</legend>
    <input aria-label={msg("editor.slides.title", { n: index + 1 })} value={slide.title ?? ""} maxLength={160} onChange={(event) => set(index, { title: event.target.value })} style={{ width: "100%" }} />
    <textarea aria-label={msg("editor.slides.bullets", { n: index + 1 })} rows={4} value={(slide.bullets ?? []).join("\n")} onChange={(event) => set(index, { bullets: lines(event.target.value) })} style={{ width: "100%" }} />
    <textarea aria-label={msg("editor.slides.notes", { n: index + 1 })} rows={2} value={slide.notes ?? ""} maxLength={1500} onChange={(event) => set(index, { notes: event.target.value })} style={{ width: "100%" }} />
    <button type="button" className="studio-icon-button" aria-label={msg("editor.slides.delete", { n: index + 1 })} disabled={slides.length <= 1} onClick={() => onChange({ ...body, slides: remove(slides, index) })}><StudioIcon name="delete" size={16} /></button>
  </fieldset>)}</div>;
}

function FlashcardsEditor({ body, onChange }) {
  const cards = body.cards ?? [];
  const set = (index, patch) => onChange({ ...body, cards: update(cards, index, patch) });
  return <div>{cards.map((card, index) => <fieldset key={index} style={{ border: "1px solid var(--studio-border, #8883)", margin: "8px 0", padding: 8 }}>
    <legend>{msg("editor.cards.legend", { n: index + 1 })}</legend>
    <input aria-label={msg("editor.cards.front", { n: index + 1 })} value={card.front ?? ""} maxLength={300} onChange={(event) => set(index, { front: event.target.value })} style={{ width: "100%" }} />
    <textarea aria-label={msg("editor.cards.back", { n: index + 1 })} rows={3} value={card.back ?? ""} maxLength={800} onChange={(event) => set(index, { back: event.target.value })} style={{ width: "100%" }} />
    <button type="button" className="studio-icon-button" aria-label={msg("editor.cards.delete", { n: index + 1 })} disabled={cards.length <= 1} onClick={() => onChange({ ...body, cards: remove(cards, index) })}><StudioIcon name="delete" size={16} /></button>
  </fieldset>)}
  <button type="button" className="studio-btn" onClick={() => onChange({ ...body, cards: [...cards, { front: "", back: "", refs: [] }] })}>{msg("editor.cards.add")}</button></div>;
}

function QuizEditor({ body, onChange }) {
  const questions = body.questions ?? [];
  const set = (index, patch) => onChange({ ...body, questions: update(questions, index, patch) });
  return <div>{questions.map((q, index) => <fieldset key={index} style={{ border: "1px solid var(--studio-border, #8883)", margin: "8px 0", padding: 8 }}>
    <legend>{msg("editor.quiz.legend", { n: index + 1 })}</legend>
    <input aria-label={msg("editor.quiz.question", { n: index + 1 })} value={q.q ?? ""} maxLength={500} onChange={(event) => set(index, { q: event.target.value })} style={{ width: "100%" }} />
    {(q.options ?? []).map((option, oi) => <label key={oi} style={{ display: "flex", gap: 6 }}>
      <input type="radio" name={`answer-${index}`} aria-label={msg("editor.quiz.answer", { n: index + 1, o: oi + 1 })} checked={q.answer_index === oi} onChange={() => set(index, { answer_index: oi })} />
      <input aria-label={msg("editor.quiz.option", { n: index + 1, o: oi + 1 })} value={option} maxLength={300} onChange={(event) => set(index, { options: q.options.map((o, i) => (i === oi ? event.target.value : o)) })} style={{ flex: 1 }} /></label>)}
    <textarea aria-label={msg("editor.quiz.explanation", { n: index + 1 })} rows={2} value={q.explanation ?? ""} maxLength={1000} onChange={(event) => set(index, { explanation: event.target.value })} style={{ width: "100%" }} />
    <button type="button" className="studio-icon-button" aria-label={msg("editor.quiz.delete", { n: index + 1 })} disabled={questions.length <= 1} onClick={() => onChange({ ...body, questions: remove(questions, index) })}><StudioIcon name="delete" size={16} /></button>
  </fieldset>)}</div>;
}

const EDITORS = { report: ReportEditor, slides: SlidesEditor, flashcards: FlashcardsEditor, quiz: QuizEditor };

/** output: getOutput 결과(revision.content.body 포함). onSave(content): 저장 약속을 돌려주는 함수. */
export function StudioEditor({ output, onSave, onCancel }) {
  const [body, setBody] = useState(() => JSON.parse(JSON.stringify(output.revision?.content?.body ?? {})));
  const [state, setState] = useState({ saving: false, error: null });
  const Editor = EDITORS[output.type_id];
  if (!Editor) return <p>{msg("editor.unsupported")}</p>;
  const save = async () => {
    setState({ saving: true, error: null });
    try { await onSave({ ...output.revision.content, body }); } catch (error) { setState({ saving: false, error: error?.code ?? "STUDIO_REQUEST_FAILED" }); }
  };
  return <div className="studio-editor" role="form" aria-label={msg("editor.form")}>
    <Editor body={body} onChange={setBody} />
    {state.error && <p role="alert" className="studio-alert">{msg("editor.error", { code: state.error })}</p>}
    <div className="studio-row">
      <button type="button" className="studio-btn studio-btn--primary" disabled={state.saving} onClick={save}>{msg("editor.save")}</button>
      <button type="button" className="studio-btn" disabled={state.saving} onClick={onCancel}>{msg("editor.cancel")}</button>
    </div>
  </div>;
}

export default StudioEditor;
