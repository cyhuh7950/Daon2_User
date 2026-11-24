// Provider Key를 요청에 실을 때 쓰는 값. 붙여 넣을 때 섞인 앞뒤 공백·줄바꿈·탭만 지운다(가운데는 그대로).
// 서버는 앞뒤 공백이 있는 Key를 'Key 없음'으로 거절하므로, 화면에서 지운 값만 보낸다.
export function requestCredential(value) {
  return typeof value === "string" ? value.trim() : "";
}
