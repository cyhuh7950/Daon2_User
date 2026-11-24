/** 근거 창에 보일 글. 원문 발췌(text)가 없으면 snapshot의 이름·출처 표시·발췌만 쓰고 내부 식별자는 보이지 않는다. */
export function evidenceExcerptView(content) {
  const snapshot = content?.snapshot && typeof content.snapshot === "object" ? content.snapshot : {};
  const pick = (value) => (typeof value === "string" ? value : "");
  if (typeof content?.text === "string") return { title: pick(content.filename), label: "", text: content.text };
  return { title: pick(content?.filename) || pick(snapshot.name), label: pick(snapshot.origin_label), text: pick(snapshot.excerpt) };
}
