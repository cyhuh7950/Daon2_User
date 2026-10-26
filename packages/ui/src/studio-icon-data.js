// Studio 아이콘 도형 데이터 (자체 제작). 24x24 선(outline) 아이콘이며 모양은 순수 데이터로만 둔다.
// 요소 형식: [태그, 속성]. 채움이 필요한 요소는 속성에 fill:"currentColor", stroke:"none"을 명시한다.
// 허용 태그: path, rect, circle, line, polyline. 새 아이콘을 추가하면 단위 테스트가 규격을 검사한다.

const FILL = Object.freeze({ fill: "currentColor", stroke: "none" });

// AI 표식(4점 별). 위치와 크기만 바꿔 재사용한다.
function sparkle(cx, cy, r) {
  const a = r * 0.28;
  return ["path", {
    d: `M${cx} ${cy - r}L${cx + a} ${cy - a}L${cx + r} ${cy}L${cx + a} ${cy + a}L${cx} ${cy + r}L${cx - a} ${cy + a}L${cx - r} ${cy}L${cx - a} ${cy - a}Z`,
    ...FILL,
  }];
}

export const STUDIO_ICON_VIEWBOX = 24;
export const ALLOWED_ICON_TAGS = Object.freeze(["path", "rect", "circle", "line", "polyline"]);

const RAW = {
  // ───────────── 산출물 유형 10종 ─────────────
  audio_overview: [
    ["line", { x1: 5, y1: 10, x2: 5, y2: 14 }],
    ["line", { x1: 9, y1: 6, x2: 9, y2: 18 }],
    ["line", { x1: 13, y1: 9, x2: 13, y2: 15 }],
    ["line", { x1: 17, y1: 12, x2: 17, y2: 20 }],
    sparkle(18.2, 5.4, 3.2),
  ],
  slides: [
    ["rect", { x: 3, y: 4, width: 18, height: 12, rx: 2.5 }],
    ["line", { x1: 12, y1: 16, x2: 12, y2: 20 }],
    ["line", { x1: 8, y1: 20, x2: 16, y2: 20 }],
    ["line", { x1: 7, y1: 8.5, x2: 13, y2: 8.5 }],
    ["line", { x1: 7, y1: 11.5, x2: 10.5, y2: 11.5 }],
  ],
  video_overview: [
    ["rect", { x: 3, y: 6, width: 13, height: 12, rx: 3 }],
    ["path", { d: "M16 10.2l4.4-2.6a.6.6 0 0 1 .9.5v7.8a.6.6 0 0 1-.9.5L16 13.8" }],
    ["path", { d: "M8.2 9.8v4.4l3.6-2.2z" }],
  ],
  mind_map: [
    ["circle", { cx: 6, cy: 12, r: 2.6 }],
    ["circle", { cx: 18, cy: 6, r: 2.6 }],
    ["circle", { cx: 18, cy: 18, r: 2.6 }],
    ["path", { d: "M8.4 11.1C11 10.4 12.6 8.4 15.6 7" }],
    ["path", { d: "M8.4 12.9C11 13.6 12.6 15.6 15.6 17" }],
  ],
  report: [
    ["path", { d: "M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" }],
    ["path", { d: "M14 3v5h5" }],
    ["line", { x1: 8.5, y1: 13, x2: 15.5, y2: 13 }],
    ["line", { x1: 8.5, y1: 16.5, x2: 13, y2: 16.5 }],
  ],
  flashcards: [
    ["rect", { x: 8, y: 3, width: 13, height: 13, rx: 2.5 }],
    ["path", { d: "M16 20H6.5A2.5 2.5 0 0 1 4 17.5V8" }],
    ["line", { x1: 11.5, y1: 8, x2: 17.5, y2: 8 }],
    ["line", { x1: 11.5, y1: 11.5, x2: 15, y2: 11.5 }],
  ],
  quiz: [
    ["rect", { x: 3, y: 3, width: 18, height: 18, rx: 4.5 }],
    ["path", { d: "M9.6 9.6a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.2.9-1.2 1.8" }],
    ["circle", { cx: 12, cy: 16.6, r: 0.9, ...FILL }],
  ],
  infographic: [
    ["rect", { x: 4, y: 12, width: 4, height: 8, rx: 1 }],
    ["rect", { x: 10, y: 5, width: 4, height: 15, rx: 1 }],
    ["rect", { x: 16, y: 9, width: 4, height: 11, rx: 1 }],
  ],
  data_table: [
    ["rect", { x: 3, y: 4, width: 18, height: 16, rx: 2.5 }],
    ["line", { x1: 3, y1: 9.5, x2: 21, y2: 9.5 }],
    ["line", { x1: 3, y1: 14.5, x2: 21, y2: 14.5 }],
    ["line", { x1: 9.5, y1: 4, x2: 9.5, y2: 20 }],
  ],
  memo: [
    ["rect", { x: 4, y: 3, width: 16, height: 18, rx: 3 }],
    ["line", { x1: 8, y1: 8, x2: 16, y2: 8 }],
    ["line", { x1: 8, y1: 12, x2: 16, y2: 12 }],
    ["line", { x1: 8, y1: 16, x2: 12.5, y2: 16 }],
  ],

  // ───────────── 동작·메뉴 아이콘 ─────────────
  add: [["path", { d: "M12 5v14M5 12h14" }]],
  close: [["path", { d: "M6 6l12 12M18 6L6 18" }]],
  more_vertical: [
    ["circle", { cx: 12, cy: 5, r: 1.4, ...FILL }],
    ["circle", { cx: 12, cy: 12, r: 1.4, ...FILL }],
    ["circle", { cx: 12, cy: 19, r: 1.4, ...FILL }],
  ],
  share: [
    ["circle", { cx: 18, cy: 5.5, r: 2.5 }],
    ["circle", { cx: 6, cy: 12, r: 2.5 }],
    ["circle", { cx: 18, cy: 18.5, r: 2.5 }],
    ["path", { d: "M8.2 10.8l7.6-4.1M8.2 13.2l7.6 4.1" }],
  ],
  edit: [
    ["path", { d: "M4 20l4.2-1L19 8.2a2.1 2.1 0 0 0-3-3L5.2 16z" }],
    ["path", { d: "M14.4 6.6l3 3" }],
  ],
  download: [
    ["path", { d: "M12 4v11" }],
    ["path", { d: "M7.5 11.2l4.5 4.5 4.5-4.5" }],
    ["path", { d: "M5 20h14" }],
  ],
  upload: [
    ["path", { d: "M12 15V4" }],
    ["path", { d: "M7.5 8.2L12 3.7l4.5 4.5" }],
    ["path", { d: "M5 20h14" }],
  ],
  info_sparkle: [
    ["circle", { cx: 11, cy: 13, r: 8 }],
    ["line", { x1: 11, y1: 12, x2: 11, y2: 17 }],
    ["circle", { cx: 11, cy: 9, r: 0.95, ...FILL }],
    sparkle(19, 5, 3.3),
  ],
  delete: [
    ["path", { d: "M4 7h16" }],
    ["path", { d: "M9 7V4.5h6V7" }],
    ["path", { d: "M6.5 7l1 13h9l1-13" }],
    ["path", { d: "M10 11v6M14 11v6" }],
  ],
  play: [["path", { d: "M8 5.5v13l11-6.5z", ...FILL }]],
  panel_toggle: [
    ["rect", { x: 3, y: 4, width: 18, height: 16, rx: 3.5 }],
    ["line", { x1: 15, y1: 4, x2: 15, y2: 20 }],
  ],
  settings_sliders: [
    ["path", { d: "M4 7h8M16.5 7H20M4 17h3.5M12 17h8" }],
    ["circle", { cx: 14.2, cy: 7, r: 2.2 }],
    ["circle", { cx: 9.8, cy: 17, r: 2.2 }],
  ],
  copy: [
    ["rect", { x: 8.5, y: 8.5, width: 11.5, height: 11.5, rx: 2.5 }],
    ["path", { d: "M15.5 8.5V6.5a2.5 2.5 0 0 0-2.5-2.5H6.5A2.5 2.5 0 0 0 4 6.5V13a2.5 2.5 0 0 0 2.5 2.5h2" }],
  ],
  pin: [
    ["path", { d: "M9 4h6l-.8 5.6 2.8 3H7l2.8-3z" }],
    ["line", { x1: 12, y1: 12.6, x2: 12, y2: 20 }],
  ],
  chart: [
    ["path", { d: "M4 4v16h16" }],
    ["path", { d: "M8 15l3.2-4.2 3 2.4L19 7.5" }],
  ],
  history: [
    ["circle", { cx: 12, cy: 12, r: 8.5 }],
    ["path", { d: "M12 7.5V12l3 2" }],
  ],
  refresh: [
    ["path", { d: "M19.5 12a7.5 7.5 0 1 1-2.3-5.4" }],
    ["path", { d: "M19.8 4.6v4.6h-4.6" }],
  ],
  check: [["path", { d: "M5 12.5l4.5 4.5L19 7.5" }]],
  warning: [
    ["path", { d: "M12 4l9 16H3z" }],
    ["line", { x1: 12, y1: 10, x2: 12, y2: 14 }],
    ["circle", { cx: 12, cy: 17, r: 0.9, ...FILL }],
  ],
  chat: [
    ["path", { d: "M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" }],
  ],
  spinner: [["path", { d: "M12 3.5a8.5 8.5 0 1 0 8.5 8.5" }]],
  sparkle: [sparkle(12, 12, 8.5)],
  source_stack: [
    ["path", { d: "M5 7l7-3 7 3-7 3z" }],
    ["path", { d: "M5 12l7 3 7-3" }],
    ["path", { d: "M5 17l7 3 7-3" }],
  ],
  cancel: [
    ["circle", { cx: 12, cy: 12, r: 8.5 }],
    ["path", { d: "M9 9l6 6M15 9l-6 6" }],
  ],
  chevron_right: [["path", { d: "M9 5l7 7-7 7" }]],
  chevron_down: [["path", { d: "M5 9l7 7 7-7" }]],
};

function freeze(elements) {
  return Object.freeze(elements.map(([tag, attrs]) => Object.freeze([tag, Object.freeze({ ...attrs })])));
}

export const STUDIO_ICONS = Object.freeze(
  Object.fromEntries(Object.entries(RAW).map(([name, elements]) => [name, freeze(elements)])),
);

export const STUDIO_ICON_NAMES = Object.freeze(Object.keys(STUDIO_ICONS));

// 산출물 유형 → 아이콘·강조색(CSS 변수)·문구 키. 문구는 메시지 카탈로그(studio-messages)에서 가져온다.
export const STUDIO_TYPE_STYLE = Object.freeze({
  audio_overview: Object.freeze({ icon: "audio_overview", accent: "audio", labelKey: "studio.tile.audio_overview" }),
  slides: Object.freeze({ icon: "slides", accent: "slides", labelKey: "studio.tile.slides" }),
  video_overview: Object.freeze({ icon: "video_overview", accent: "video", labelKey: "studio.tile.video_overview" }),
  mind_map: Object.freeze({ icon: "mind_map", accent: "mindmap", labelKey: "studio.tile.mind_map" }),
  report: Object.freeze({ icon: "report", accent: "report", labelKey: "studio.tile.report" }),
  flashcards: Object.freeze({ icon: "flashcards", accent: "flashcards", labelKey: "studio.tile.flashcards" }),
  quiz: Object.freeze({ icon: "quiz", accent: "quiz", labelKey: "studio.tile.quiz" }),
  infographic: Object.freeze({ icon: "infographic", accent: "infographic", labelKey: "studio.tile.infographic" }),
  data_table: Object.freeze({ icon: "data_table", accent: "table", labelKey: "studio.tile.data_table" }),
  memo: Object.freeze({ icon: "memo", accent: "memo", labelKey: "studio.tile.memo" }),
});

// 타일 표시 순서(참조 화면의 2열 배치: 좌→우, 위→아래).
export const STUDIO_TILE_ORDER = Object.freeze([
  "audio_overview", "slides", "video_overview", "mind_map", "report",
  "flashcards", "quiz", "infographic", "data_table",
]);
