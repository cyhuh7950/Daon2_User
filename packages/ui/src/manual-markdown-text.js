// 설명서 원문 한 줄의 표시용 글(그림·링크·굵게·코드 표시를 걷어 낸 글). 본문 렌더러와 목차가 함께 쓴다.
export function readableManualLine(line) {
  return line
    .replace(/!\[([^\]]+)\]\([^)]*\)/gu, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/gu, "$1")
    .replace(/\*\*([^*]+)\*\*/gu, "$1")
    .replace(/`([^`]+)`/gu, "$1");
}
