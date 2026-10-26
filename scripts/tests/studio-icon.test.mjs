import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ALLOWED_ICON_TAGS, STUDIO_ICON_NAMES, STUDIO_ICONS, STUDIO_TILE_ORDER, STUDIO_TYPE_STYLE,
} from "../../packages/ui/src/studio-icon-data.js";
import { StudioIcon } from "../../packages/ui/src/studio-icon.js";

const root = path.resolve(import.meta.dirname, "../..");
const css = readFileSync(path.join(root, "packages/ui/src/studio-icon.css"), "utf8");

const REQUIRED_TYPE_ICONS = [
  "audio_overview", "slides", "video_overview", "mind_map", "report",
  "flashcards", "quiz", "infographic", "data_table", "memo",
];
const REQUIRED_ACTION_ICONS = [
  "add", "close", "more_vertical", "share", "edit", "download", "info_sparkle", "delete", "play",
  "panel_toggle", "settings_sliders", "copy", "pin", "chart", "history", "refresh", "check", "warning",
  "chat", "spinner", "sparkle", "source_stack", "cancel", "chevron_right", "chevron_down", "upload",
];

function hexToRgb(hex) {
  const value = hex.replace("#", "");
  return [0, 2, 4].map((index) => parseInt(value.slice(index, index + 2), 16) / 255);
}
function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map((value) => (value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}
function accents(block) {
  return Object.fromEntries([...block.matchAll(/--studio-accent-([a-z]+):\s*(#[0-9a-fA-F]{6});/gu)].map((m) => [m[1], m[2]]));
}

test("아이콘 이름은 36개이며 중복 없이 필수 유형·동작 아이콘을 모두 가진다", () => {
  assert.equal(STUDIO_ICON_NAMES.length, 36);
  assert.equal(new Set(STUDIO_ICON_NAMES).size, STUDIO_ICON_NAMES.length);
  for (const name of [...REQUIRED_TYPE_ICONS, ...REQUIRED_ACTION_ICONS]) {
    assert.ok(Object.hasOwn(STUDIO_ICONS, name), name);
  }
  for (const name of STUDIO_ICON_NAMES) assert.match(name, /^[a-z][a-z_]{1,31}$/u);
});

test("모든 아이콘 요소는 허용 태그와 24x24 안의 유한한 좌표만 쓴다", () => {
  for (const [name, elements] of Object.entries(STUDIO_ICONS)) {
    assert.ok(elements.length >= 1 && elements.length <= 8, `${name} 요소 수`);
    for (const [tag, attrs] of elements) {
      assert.ok(ALLOWED_ICON_TAGS.includes(tag), `${name}: ${tag}`);
      for (const [key, value] of Object.entries(attrs)) {
        assert.match(key, /^[a-z][a-z0-9-]*$/u, `${name} 속성 이름`);
        if (["x", "y", "cx", "cy", "r", "x1", "x2", "y1", "y2", "width", "height", "rx"].includes(key)) {
          assert.ok(Number.isFinite(value) && value >= 0 && value <= 24, `${name} ${key}=${value}`);
        }
        if (key === "d") assert.match(value, /^[MmLlHhVvCcSsQqTtAaZz0-9eE.,\s-]+$/u, `${name} path`);
      }
      if (tag === "rect") assert.ok(attrs.x + attrs.width <= 24 && attrs.y + attrs.height <= 24, `${name} rect 범위`);
      if (tag === "circle") assert.ok(attrs.cx - attrs.r >= -0.01 && attrs.cx + attrs.r <= 24.01, `${name} circle 범위`);
    }
  }
});

test("유형 스타일은 모든 산출물 유형에 아이콘·강조색·문구 키를 연결한다", () => {
  assert.deepEqual(Object.keys(STUDIO_TYPE_STYLE).sort(), [...REQUIRED_TYPE_ICONS].sort());
  for (const [type, style] of Object.entries(STUDIO_TYPE_STYLE)) {
    assert.ok(Object.hasOwn(STUDIO_ICONS, style.icon), type);
    assert.equal(style.labelKey, `studio.tile.${type}`);
    assert.match(css, new RegExp(`\\.studio-icon--accent-${style.accent}\\s*\\{`, "u"), `${type} 강조색 클래스`);
    assert.match(css, new RegExp(`--studio-accent-${style.accent}:`, "u"), `${type} 라이트 토큰`);
  }
  assert.equal(STUDIO_TILE_ORDER.length, 9);
  assert.ok(!STUDIO_TILE_ORDER.includes("memo"), "메모는 타일이 아니라 하단 버튼");
  for (const type of STUDIO_TILE_ORDER) assert.ok(Object.hasOwn(STUDIO_TYPE_STYLE, type));
});

test("유형 강조색은 라이트·다크 배경에서 비텍스트 대비 3:1 이상이다", () => {
  const light = accents(css.slice(0, css.indexOf(':root[data-theme="dark"]')));
  const dark = accents(css.slice(css.indexOf(':root[data-theme="dark"]')));
  const types = Object.values(STUDIO_TYPE_STYLE).map((style) => style.accent);
  for (const accent of types) {
    assert.ok(light[accent] && dark[accent], `${accent} 토큰 누락`);
    for (const background of ["#ffffff", "#f1f3f8"]) {
      assert.ok(contrast(light[accent], background) >= 3, `라이트 ${accent} ${light[accent]} / ${background}`);
    }
    for (const background of ["#1b1c20", "#2a2c31"]) {
      assert.ok(contrast(dark[accent], background) >= 3, `다크 ${accent} ${dark[accent]} / ${background}`);
    }
  }
});

test("StudioIcon은 장식용은 aria-hidden, 제목이 있으면 role=img로 렌더한다", () => {
  const decorative = renderToStaticMarkup(createElement(StudioIcon, { name: "report", accent: true }));
  assert.match(decorative, /<svg /u);
  assert.match(decorative, /aria-hidden="true"/u);
  assert.match(decorative, /studio-icon--report/u);
  assert.match(decorative, /studio-icon--accent-report/u);
  assert.doesNotMatch(decorative, /role=/u);

  const labelled = renderToStaticMarkup(createElement(StudioIcon, { name: "delete", title: "삭제", size: 20 }));
  assert.match(labelled, /role="img"/u);
  assert.match(labelled, /<title>삭제<\/title>/u);
  assert.match(labelled, /width="20"/u);
  assert.doesNotMatch(labelled, /aria-hidden/u);

  assert.throws(() => renderToStaticMarkup(createElement(StudioIcon, { name: "nope" })), /STUDIO_ICON_UNKNOWN/u);
  assert.throws(() => renderToStaticMarkup(createElement(StudioIcon, { name: "../x" })), /STUDIO_ICON_UNKNOWN/u);
  const clamped = renderToStaticMarkup(createElement(StudioIcon, { name: "add", size: 1000 }));
  assert.match(clamped, /width="24"/u);
});

test("모든 아이콘이 서버 렌더로 정상 마크업을 만든다", () => {
  for (const name of STUDIO_ICON_NAMES) {
    const markup = renderToStaticMarkup(createElement(StudioIcon, { name }));
    assert.match(markup, /^<svg [^>]*viewBox="0 0 24 24"/u, name);
    assert.ok(markup.length > 120, name);
  }
});
