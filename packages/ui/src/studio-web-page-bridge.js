// 웹 페이지 보기(WO-N8): 격리 iframe이 보내는 근거 번호 메시지를 판정한다.
// srcdoc 격리 프레임의 origin은 "null"이라 믿을 수 없다. 보낸 창이 우리 iframe의 창인지(event.source)로 지킨다.

const REF_PATTERN = /^S\d+$/u;

const plainObject = (value) => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === null || Object.getPrototypeOf(proto) === null;
};

/** 우리 iframe이 보낸 {type:"daon-ref", ref:"S#"}이고 알려진 근거 번호면 번호를, 아니면 null을 준다. */
export function acceptRefMessage(event, frameWindow, knownRefs) {
  if (!event || !frameWindow || event.source !== frameWindow) return null;
  const data = event.data;
  if (!plainObject(data) || data.type !== "daon-ref") return null;
  const ref = data.ref;
  if (typeof ref !== "string" || !REF_PATTERN.test(ref)) return null;
  return knownRefs instanceof Set && knownRefs.has(ref) ? ref : null;
}
