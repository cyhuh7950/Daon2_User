// 설명서 목차(N1-B15): 부(##)와 절(###) 제목을 2단계 목록으로 뽑는다. 본문 렌더러(manual-markdown.jsx)가 같은 id를 제목에 붙여
// 목차를 누르면 그 절로 이동한다. id는 원문 줄 번호로 만든다(같은 문서에서는 늘 같다).
import { readableManualLine } from "./manual-markdown-text.js";

export const manualHeadingId = (lineIndex) => `manual-section-${lineIndex}`;

export function manualToc(text) {
  const toc = [];
  String(text ?? "").split("\n").forEach((line, index) => {
    const match = /^(#{2,3})\s+(.+)$/u.exec(readableManualLine(line.trim()));
    if (match) toc.push({ id: manualHeadingId(index), level: match[1].length, title: match[2].trim() });
  });
  return toc;
}

/** 검색어가 든 절만 남기고, 남은 절이 속한 부 제목도 남긴다. 부 제목에 검색어가 들면 그 부의 절을 모두 남긴다. */
export function filterManualToc(toc, query) {
  const needle = String(query ?? "").trim().toLocaleLowerCase("ko-KR");
  if (!needle) return toc;
  const has = (item) => item.title.toLocaleLowerCase("ko-KR").includes(needle);
  const kept = [];
  let part = null;
  let partMatched = false;
  let partAdded = false;
  for (const item of toc) {
    if (item.level === 2) {
      part = item;
      partMatched = has(item);
      partAdded = false;
      if (partMatched) { kept.push(item); partAdded = true; }
      continue;
    }
    if (partMatched || has(item)) {
      if (part && !partAdded) { kept.push(part); partAdded = true; }
      kept.push(item);
    }
  }
  return kept;
}
