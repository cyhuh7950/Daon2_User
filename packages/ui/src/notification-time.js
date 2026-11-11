// 알림 시각을 사용자 현지 시각으로 읽기 쉽게 보여 준다(ISO 원문 금지).
export function formatNotificationTime(value, options = {}) {
  if (!value) return "기한 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "기한 없음";
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", ...options }).format(date);
}
