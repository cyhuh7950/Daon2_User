// WO-UM1 매뉴얼 구조 시험: 1부 흐름, 화면 절의 공통 틀, 번호 그림, 화면 문구 대조.
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "../..");
const manualPath = path.join(root, "docs/manual/daon-user-manual/index.md");
const imageDir = path.join(root, "docs/manual/daon-user-manual/images");
const markdown = () => readFileSync(manualPath, "utf8");

// 설계 4.2·4.3(3-2 조직 관리·가입은 미공개 화면이라 제외, 기록 WO-UM1 Ruling).
const SCREENS = [
  "2-1", "2-2", "2-3", "2-4", "2-5", "2-6", "2-7", "2-8", "2-9", "2-10", "2-11",
  "3-1", "3-2", "3-3", "3-4", "3-5", "3-6", "3-7", "3-8", "3-9",
];
const PARTS = ["기능·목적", "쓸 수 있는 사람", "사용 순서", "화면 구성", "주의·오류", "관련"];
// 굵게 쓰지만 화면 문구가 아닌 것(이유와 함께). 비어 있는 것이 정상이다.
const NOT_UI_TEXT = new Set([]);

function section(text, number) {
  const start = text.search(new RegExp(`^### ${number} `, "mu"));
  if (start < 0) return null;
  const rest = text.slice(start + 1);
  const next = rest.search(/\n#{2,3} /u);
  return text.slice(start, next < 0 ? undefined : start + 1 + next);
}

function uiCorpus() {
  const roots = ["packages/ui/src", "apps/web/components", "apps/web/app", "apps/web/lib"];
  let text = "";
  const walk = (folder) => {
    for (const name of readdirSync(folder)) {
      const full = path.join(folder, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.(?:jsx?|mjs)$/u.test(name) && !/\.test\./u.test(name)) text += readFileSync(full, "utf8");
    }
  };
  for (const folder of roots) walk(path.join(root, folder));
  return text;
}

test("1부는 8단계이고 단계마다 2부·3부 화면 연결이 있다", () => {
  const text = markdown();
  for (let step = 1; step <= 8; step += 1) {
    const body = section(text, `1-${step}`);
    assert.ok(body, `1-${step} 단계 없음`);
    assert.match(body, /자세히: [23]-\d+/u, `1-${step}에 화면 연결 없음`);
  }
});

test("화면 절은 여섯 제목을 순서대로 가진다", () => {
  const text = markdown();
  for (const number of SCREENS) {
    const body = section(text, number);
    assert.ok(body, `${number} 절 없음`);
    const headings = [...body.matchAll(/^#### (.+)$/gmu)].map((match) => match[1].trim());
    assert.deepEqual(headings, PARTS, `${number} 절 제목`);
  }
});

test("화면 절마다 번호 그림이 하나 이상 있고 파일이 존재한다", () => {
  const text = markdown();
  for (const number of SCREENS) {
    const body = section(text, number);
    const images = [...body.matchAll(/^!\[([^\]]+)\]\((images\/[a-z0-9-]+\.png)\)$/gmu)];
    assert.ok(images.length > 0, `${number} 절 그림 없음`);
    for (const [, , file] of images) assert.ok(existsSync(path.join(imageDir, path.basename(file))), `${number}: ${file} 없음`);
  }
  for (const [, file] of text.matchAll(/!\[[^\]]+\]\(([^)]+)\)/gu)) {
    assert.match(file, /^images\/[a-z0-9-]+\.png$/u, `허용되지 않는 그림 경로 ${file}`);
  }
});

test("굵게 쓴 버튼·메뉴 이름은 화면 문구에 있다", () => {
  const corpus = uiCorpus();
  const missing = [];
  for (const [, name] of markdown().matchAll(/\*\*([^*\n]{1,30})\*\*/gu)) {
    if (NOT_UI_TEXT.has(name) || !/[가-힣]/u.test(name)) continue;
    if (!corpus.includes(name)) missing.push(name);
  }
  assert.deepEqual([...new Set(missing)], [], "화면 문구 파일에 없는 굵은 이름");
});
