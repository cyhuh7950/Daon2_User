#!/usr/bin/env node
// Studio 아이콘 미리보기(단일 HTML)를 생성한다: node scripts/build-studio-icon-preview.mjs
// 출력: docs/design/studio-icons-preview.html — 다크/라이트 전환, 아이콘 전체 표, 스튜디오 패널 시안.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import {
  STUDIO_ICONS, STUDIO_ICON_NAMES, STUDIO_TILE_ORDER, STUDIO_TYPE_STYLE,
} from "../packages/ui/src/studio-icon-data.js";

const root = path.resolve(import.meta.dirname, "..");
const css = readFileSync(path.join(root, "packages/ui/src/studio-icon.css"), "utf8");

const LABELS = {
  audio_overview: "AI 오디오 오버뷰", slides: "슬라이드 자료", video_overview: "동영상 개요",
  mind_map: "마인드맵", report: "보고서", flashcards: "플래시카드", quiz: "퀴즈",
  infographic: "인포그래픽", data_table: "데이터 표", memo: "메모",
};
const SAMPLE_CARDS = [
  { type: "infographic", title: "2026년 AI 혁명과 미래 과제", sub: "소스 97개 · 93일 전" },
  { type: "flashcards", title: "인공지능 플래시카드", sub: "소스 97개 · 93일 전" },
  { type: "report", title: "[전략 기획 제안서] 하드웨어 생태계 공생형 통합 AI 헬스케어", sub: "전략 기획 제안서 · 소스 14개 · 93일 전" },
  { type: "mind_map", title: "디지털헬스 마인드맵", sub: "소스 14개 · 93일 전" },
  { type: "video_overview", title: "2026 디지털 헬스 플랫폼 전쟁", sub: "8:03 · 설명 동영상 · 소스 14개 · 93일 전", play: true },
  { type: "slides", title: "2026 Digital Health Symbiosis", sub: "소스 14개 · 93일 전" },
  { type: "audio_overview", title: "삼성과 애플을 잇는 헬스 데이터 정수장", sub: "5:32 · 토론 · 소스 14개 · 93일 전", play: true },
  { type: "memo", title: "디지털 헬스케어의 미래: 애플·삼성 생태계 공생 전략", sub: "93일 전" },
];

function svg(name, size = 24, extra = "") {
  const inner = STUDIO_ICONS[name].map(([tag, attrs]) => {
    const props = Object.entries(attrs).map(([key, value]) => `${key}="${value}"`).join(" ");
    return `<${tag} ${props}/>`;
  }).join("");
  return `<svg class="studio-icon studio-icon--${name}${extra}" viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
}

const tiles = STUDIO_TILE_ORDER.map((type) => {
  const style = STUDIO_TYPE_STYLE[type];
  const badge = type === "report" ? '<span class="badge">New!</span>' : "";
  return `<button class="tile" type="button">${svg(style.icon, 24, ` studio-icon--accent-${style.accent}`)}<span>${LABELS[type]}</span>${badge}</button>`;
}).join("");

const cards = SAMPLE_CARDS.map((card) => {
  const style = STUDIO_TYPE_STYLE[card.type];
  const play = card.play ? `<button class="iconbtn" type="button" aria-label="재생">${svg("play", 20)}</button>` : "";
  return `<div class="row">${svg(style.icon, 24, ` studio-icon--accent-${style.accent}`)}<div class="txt"><strong>${card.title}</strong><small>${card.sub}</small></div>${play}<button class="iconbtn" type="button" aria-label="더보기">${svg("more_vertical", 20)}</button></div>`;
}).join("");

const allIcons = STUDIO_ICON_NAMES.map((name) => {
  const style = Object.values(STUDIO_TYPE_STYLE).find((item) => item.icon === name);
  const accent = style ? ` studio-icon--accent-${style.accent}` : "";
  return `<figure>${svg(name, 32, accent)}<figcaption>${name}</figcaption></figure>`;
}).join("");

const html = `<!doctype html>
<html lang="ko" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studio 아이콘 미리보기</title>
<style>
${css}
:root { --canvas:#eef1f6; --panel:#ffffff; --tile:#f1f3f8; --tile-hover:#e6e9f1; --text:#1b2230; --muted:#5b6577; --line:#d5dae5; }
:root[data-theme="dark"] { --canvas:#131418; --panel:#1b1c20; --tile:#2a2c31; --tile-hover:#34363c; --text:#e8eaed; --muted:#9aa0a6; --line:#3a3c42; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: var(--canvas); color: var(--text); font: 14px/1.5 "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; }
h1 { font-size: 20px; margin: 0 0 4px; } p.note { color: var(--muted); margin: 0 0 20px; max-width: 70ch; }
.bar { display: flex; gap: 12px; align-items: center; margin-bottom: 20px; }
button { font: inherit; color: inherit; }
.toggle { background: var(--tile); border: 1px solid var(--line); border-radius: 999px; padding: 8px 16px; cursor: pointer; }
.layout { display: grid; grid-template-columns: minmax(320px, 420px) 1fr; gap: 24px; align-items: start; }
@media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
.panel { background: var(--panel); border-radius: 24px; padding: 18px 16px 76px; position: relative; max-height: 760px; overflow: auto; border: 1px solid var(--line); }
.panel h2 { font-size: 16px; margin: 4px 6px 14px; display: flex; justify-content: space-between; align-items: center; }
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 18px; }
.tile { display: flex; align-items: center; gap: 12px; height: 56px; border: 0; border-radius: 28px; padding: 0 18px; background: var(--tile); cursor: pointer; text-align: left; position: relative; font-size: 14px; }
.tile:hover { background: var(--tile-hover); } .tile:focus-visible, .iconbtn:focus-visible, .toggle:focus-visible { outline: 3px solid #4d8dff; outline-offset: 2px; }
.badge { margin-left: auto; font-size: 11px; background: var(--tile-hover); border-radius: 999px; padding: 2px 8px; }
.row { display: flex; align-items: center; gap: 14px; padding: 12px 8px; border-radius: 14px; }
.row:hover { background: var(--tile); }
.txt { display: flex; flex-direction: column; min-width: 0; flex: 1; } .txt strong { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } .txt small { color: var(--muted); font-size: 12px; }
.iconbtn { width: 36px; height: 36px; display: grid; place-items: center; border: 0; background: transparent; border-radius: 50%; cursor: pointer; } .iconbtn:hover { background: var(--tile-hover); }
.fab { position: absolute; left: 50%; bottom: 16px; transform: translateX(-50%); display: flex; align-items: center; gap: 10px; border: 0; border-radius: 999px; padding: 12px 20px; background: var(--tile-hover); box-shadow: 0 6px 18px rgba(0,0,0,.35); cursor: pointer; }
section.sheet { background: var(--panel); border: 1px solid var(--line); border-radius: 24px; padding: 20px; }
section.sheet h2 { font-size: 16px; margin: 0 0 12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 12px; }
figure { margin: 0; display: grid; justify-items: center; gap: 8px; padding: 14px 6px; border-radius: 16px; background: var(--tile); }
figcaption { font-size: 11px; color: var(--muted); word-break: break-all; text-align: center; }
.menu { display: inline-block; background: var(--tile); border-radius: 16px; padding: 6px; min-width: 260px; margin-top: 12px; }
.menu div { display: flex; align-items: center; gap: 14px; padding: 10px 14px; border-radius: 10px; } .menu div:hover { background: var(--tile-hover); }
.menu hr { border: 0; border-top: 1px solid var(--line); margin: 6px 4px; }
</style>
</head>
<body>
<div class="bar"><h1>Studio 아이콘 미리보기</h1><button class="toggle" type="button" id="theme">라이트로 보기</button></div>
<p class="note">36개 자체 제작 선(outline) 아이콘과 스튜디오 패널 시안입니다. 형태 언어(필 타일, 유형별 컬러 아이콘, 스파클 표식, 둥근 패널)를 참고했고 아이콘은 모두 새로 그렸습니다.</p>
<div class="layout">
  <div class="panel" aria-label="스튜디오 패널 시안">
    <h2>스튜디오 ${svg("panel_toggle", 22)}</h2>
    <div class="tiles">${tiles}</div>
    ${cards}
    <button class="fab" type="button">${svg("memo", 20)}<span>메모 추가</span></button>
  </div>
  <div>
    <section class="sheet"><h2>전체 아이콘 (${STUDIO_ICON_NAMES.length}개)</h2><div class="grid">${allIcons}</div></section>
    <section class="sheet" style="margin-top:20px"><h2>카드 ⋮ 메뉴 시안</h2>
      <div class="menu">
        <div>${svg("share", 22)}<span>공유</span></div>
        <div>${svg("edit", 22)}<span>이름 바꾸기</span></div>
        <div>${svg("download", 22)}<span>다운로드</span></div>
        <div>${svg("info_sparkle", 22)}<span>프롬프트 및 소스 보기</span></div>
        <hr>
        <div>${svg("refresh", 22)}<span>다시 생성</span></div>
        <div>${svg("pin", 22)}<span>메모로 저장</span></div>
        <hr>
        <div>${svg("delete", 22)}<span>삭제</span></div>
      </div>
    </section>
  </div>
</div>
<script>
  const button = document.getElementById("theme");
  button.addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.getAttribute("data-theme") === "dark";
    root.setAttribute("data-theme", dark ? "light" : "dark");
    button.textContent = dark ? "다크로 보기" : "라이트로 보기";
  });
</script>
</body>
</html>
`;

const outDir = path.join(root, "docs", "design");
mkdirSync(outDir, { recursive: true });
writeFileSync(path.join(outDir, "studio-icons-preview.html"), html, "utf8");
console.log(`studio icon preview written (${STUDIO_ICON_NAMES.length} icons)`);
