// 새 메모 제목. 서버 시계는 UTC라서 사용자의 현지 시각을 브라우저에서 붙인다.
export function localMemoTitle(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return `메모 ${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
