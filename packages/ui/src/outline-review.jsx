"use client";

import { useRef, useState } from "react";
import { msg, studioErrorMessage } from "./studio-messages.ko.js";

/**
 * 생성 전 구성 확인(WO-N1 NB3-U1): 슬라이드 장 목록·동영상 장면 목록을 사람이 고친 뒤 확정한다.
 * 상한은 서버 parse_confirmed_outline(studio_v2_types.py)과 같다. 화면에서 먼저 막고, 서버가 422 OUTLINE_INVALID로 한 번 더 막는다.
 */
export const OUTLINE_RULES = Object.freeze({
  slides: Object.freeze({ key: "slides", unit: "slide", maxItems: 30, title: 100, list: "points", listMax: 5, listItem: 120 }),
  video_overview: Object.freeze({ key: "scenes", unit: "scene", maxItems: 20, title: 100, narration: 600, list: "bullets", listMax: 5, listItem: 120 }),
});
export const OUTLINE_DOC_TITLE_MAX = 160;
export const OUTLINE_REVIEW_TYPES = Object.freeze(Object.keys(OUTLINE_RULES));

const unitName = (rules) => msg(`outline.unit.${rules.unit}`);
const listName = (rules) => msg(`outline.field.${rules.list}`);

/** 화면 입력값의 문제를 사람이 읽는 문구 목록으로 돌려준다. 비어 있으면 확정할 수 있다. */
export function outlineProblems(typeId, title, items) {
  const rules = OUTLINE_RULES[typeId];
  const unit = unitName(rules);
  const problems = [];
  if (title.trim().length > OUTLINE_DOC_TITLE_MAX) problems.push(msg("outline.error.doc_title", { max: OUTLINE_DOC_TITLE_MAX }));
  if (items.length === 0) problems.push(msg("outline.error.empty", { unit }));
  if (items.length > rules.maxItems) problems.push(msg("outline.error.too_many", { unit, max: rules.maxItems }));
  items.forEach((item, index) => {
    const n = index + 1;
    const name = item.title.trim();
    if (!name) problems.push(msg("outline.error.title_required", { n, unit }));
    else if (name.length > rules.title) problems.push(msg("outline.error.too_long.title", { n, unit, max: rules.title }));
    if (rules.narration && item.narration.trim().length > rules.narration) problems.push(msg("outline.error.too_long.narration", { n, unit, max: rules.narration }));
    const list = item.list.map((value) => value.trim()).filter(Boolean);
    if (list.length > rules.listMax) problems.push(msg("outline.error.list_count", { n, unit, field: listName(rules), max: rules.listMax }));
    if (list.some((value) => value.length > rules.listItem)) problems.push(msg(`outline.error.too_long.${rules.list}`, { n, unit, max: rules.listItem }));
  });
  return problems;
}

/** 확정 목록 JSON 문자열(settings.confirmed_outline). 빈 요지·글머리는 뺀다(서버와 같음). */
export function confirmedOutlineJson(typeId, title, items) {
  const rules = OUTLINE_RULES[typeId];
  const list = (item) => item.list.map((value) => value.trim()).filter(Boolean);
  const entries = items.map((item) => {
    if (typeId === "slides") return { title: item.title.trim(), points: list(item) };
    const bullets = list(item);
    return { title: item.title.trim(), narration_summary: item.narration.trim(), ...(bullets.length ? { bullets } : {}) };
  });
  return JSON.stringify({ title: title.trim(), [rules.key]: entries });
}

function fromServer(typeId, review, nextKey) {
  return (review ?? []).map((entry) => ({
    key: nextKey(),
    title: String(entry?.title ?? ""),
    narration: String(entry?.narration_summary ?? ""),
    list: (typeId === "slides" ? entry?.points : entry?.bullets ?? []).filter((value) => typeof value === "string").map(String),
  }));
}

export function OutlineReviewEditor({ typeId, body, onConfirm, onCancel }) {
  const rules = OUTLINE_RULES[typeId];
  const counter = useRef(0);
  const nextKey = () => { counter.current += 1; return counter.current; };
  const [title, setTitle] = useState(String(body?.title ?? ""));
  const [items, setItems] = useState(() => fromServer(typeId, body?.outline_review, nextKey));
  const [pending, setPending] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const unit = unitName(rules);
  const field = listName(rules);
  const problems = outlineProblems(typeId, title, items);
  const change = (index, patch) => { setSubmitError(null); setItems((list) => list.map((item, i) => (i === index ? { ...item, ...patch } : item))); };
  const move = (index, delta) => setItems((list) => {
    const target = index + delta;
    if (target < 0 || target >= list.length) return list;
    const next = list.slice();
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  });
  const remove = (index) => setItems((list) => list.filter((_, i) => i !== index));
  const add = () => setItems((list) => [...list, { key: nextKey(), title: "", narration: "", list: [] }]);
  const confirm = async () => {
    if (problems.length || pending || !onConfirm) return;
    setPending(true);
    setSubmitError(null);
    try {
      await onConfirm(confirmedOutlineJson(typeId, title, items));
    } catch (error) {
      setSubmitError(studioErrorMessage(error?.code));
      setPending(false);
    }
  };
  return <article className="studio-outline-review" aria-labelledby="studio-outline-review-title">
    <p className="studio-chip" role="status" id="studio-outline-review-title">{msg("outline.reviewing")}</p>
    <p>{msg(`outline.help.${rules.unit}`)}</p>
    <label className="studio-outline-review__doc">{msg("outline.doc_title")}
      <input aria-label={msg("outline.doc_title")} maxLength={OUTLINE_DOC_TITLE_MAX} value={title} onChange={(event) => { setSubmitError(null); setTitle(event.target.value); }} />
    </label>
    <ol className="studio-outline-review__list">{items.map((item, index) => {
      const n = index + 1;
      return <li key={item.key} className="studio-outline-review__item">
        <div className="studio-outline-review__head"><span aria-hidden="true">{n}.</span>
          <input className="studio-outline-review__title" aria-label={msg("outline.label.title", { n, unit })} maxLength={rules.title} value={item.title}
            placeholder={msg("outline.placeholder.title", { unit })} onChange={(event) => change(index, { title: event.target.value })} /></div>
        {rules.narration && <textarea aria-label={msg("outline.label.narration", { n, unit })} maxLength={rules.narration} rows={3} value={item.narration}
          placeholder={msg("outline.placeholder.narration")} onChange={(event) => change(index, { narration: event.target.value })} />}
        {item.list.length > 0 && <ul className="studio-outline-review__points">{item.list.map((value, at) => <li key={at}>
          <input aria-label={msg("outline.label.list_item", { n, unit, field, m: at + 1 })} maxLength={rules.listItem} value={value}
            onChange={(event) => change(index, { list: item.list.map((old, i) => (i === at ? event.target.value : old)) })} />
          <button type="button" className="studio-btn studio-outline-review__small" aria-label={msg("outline.label.list_remove", { n, unit, field, m: at + 1 })}
            onClick={() => change(index, { list: item.list.filter((_, i) => i !== at) })}>{msg("outline.remove")}</button>
        </li>)}</ul>}
        <div className="studio-outline-review__actions">
          <button type="button" className="studio-btn studio-outline-review__small" aria-label={msg("outline.label.list_add", { n, unit, field })} disabled={item.list.length >= rules.listMax}
            onClick={() => change(index, { list: [...item.list, ""] })}>{msg("outline.list_add", { field })}</button>
          <span className="studio-outline-review__spacer" />
          <button type="button" className="studio-btn studio-outline-review__small" aria-label={msg("outline.label.up", { n, unit })} disabled={index === 0} onClick={() => move(index, -1)}>{msg("outline.up")}</button>
          <button type="button" className="studio-btn studio-outline-review__small" aria-label={msg("outline.label.down", { n, unit })} disabled={index === items.length - 1} onClick={() => move(index, 1)}>{msg("outline.down")}</button>
          <button type="button" className="studio-btn studio-outline-review__small" aria-label={msg("outline.label.remove", { n, unit })} onClick={() => remove(index)}>{msg("outline.remove")}</button>
        </div>
      </li>;
    })}</ol>
    <div className="studio-row">
      <button type="button" className="studio-btn" disabled={items.length >= rules.maxItems} onClick={add}>{msg("outline.add", { unit })}</button>
      <small>{msg("outline.count", { count: items.length, max: rules.maxItems })}</small>
    </div>
    {problems.length > 0 && <div className="studio-alert" role="alert"><ul>{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul></div>}
    {submitError && <p className="studio-alert" role="alert">{submitError}</p>}
    <div className="studio-row">
      <button type="button" className="studio-btn" disabled={pending} onClick={() => onCancel?.()}>{msg("outline.cancel")}</button>
      <button type="button" className="studio-btn studio-btn--primary" disabled={problems.length > 0 || pending || !onConfirm} onClick={() => void confirm()}>{msg("outline.confirm")}</button>
    </div>
  </article>;
}
