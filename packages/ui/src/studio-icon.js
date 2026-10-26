// Studio 아이콘 컴포넌트. JSX 문법 없이 jsx-runtime만 써서 번들러 없이도 테스트할 수 있고, 서버 렌더에서 개발/운영 React가 섞여도 안전하다.
import { jsx, jsxs } from "react/jsx-runtime";
import { STUDIO_ICONS, STUDIO_ICON_VIEWBOX, STUDIO_TYPE_STYLE } from "./studio-icon-data.js";

export { STUDIO_ICON_NAMES, STUDIO_TILE_ORDER, STUDIO_TYPE_STYLE } from "./studio-icon-data.js";

const SAFE_NAME = /^[a-z][a-z_]{1,31}$/u;

// accent가 true이면 유형 강조색 클래스를 붙인다. 유형 이름(report 등)이거나 accent 이름(mindmap 등)을 쓸 수 있다.
function accentClass(name, accent) {
  if (!accent) return "";
  const style = STUDIO_TYPE_STYLE[name];
  const key = typeof accent === "string" ? accent : style?.accent;
  return key ? ` studio-icon--accent-${key}` : "";
}

export function StudioIcon({ name, size = 24, title, accent = false, className = "", strokeWidth }) {
  if (typeof name !== "string" || !SAFE_NAME.test(name) || !Object.hasOwn(STUDIO_ICONS, name)) {
    throw new Error("STUDIO_ICON_UNKNOWN");
  }
  const px = Number.isInteger(size) && size >= 12 && size <= 96 ? size : 24;
  const labelled = typeof title === "string" && title.trim().length > 0;
  const children = STUDIO_ICONS[name].map(([tag, attrs], index) => jsx(tag, { ...attrs }, index));
  if (labelled) children.unshift(jsx("title", { children: title }, "title"));
  return jsxs("svg", {
    viewBox: `0 0 ${STUDIO_ICON_VIEWBOX} ${STUDIO_ICON_VIEWBOX}`,
    width: px,
    height: px,
    fill: "none",
    stroke: "currentColor",
    strokeWidth: strokeWidth ?? 1.75,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    focusable: "false",
    role: labelled ? "img" : undefined,
    "aria-hidden": labelled ? undefined : "true",
    className: `studio-icon studio-icon--${name}${accentClass(name, accent)}${className ? ` ${className}` : ""}`.trim(),
    children,
  });
}

export default StudioIcon;
