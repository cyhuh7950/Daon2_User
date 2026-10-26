#!/usr/bin/env node
// 작업계획서(docs/daon2_user_development_plan.md)의 항목 상태를 집계한다.
//   node scripts/plan-progress.mjs          요약을 표준 출력으로 낸다.
//   node scripts/plan-progress.mjs --write  계획서의 progress 블록을 갱신한다.
// 상태 표기: [0] 완료, [1] 테스트 중, [2] 개발 중, [ ] 착수 안 함 (표의 첫 열).
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const planPath = path.join(root, "docs", "daon2_user_development_plan.md");
const START = "<!-- progress:start -->";
const END = "<!-- progress:end -->";
const STATES = [
  ["[0]", "완료"],
  ["[1]", "테스트 중"],
  ["[2]", "개발 중"],
  ["[ ]", "착수 안 함"],
];

function parse(text) {
  const sections = [];
  let part = "";
  let current = null;
  const seen = new Map();
  const errors = [];
  text.split(/\r?\n/u).forEach((line, index) => {
    const partMatch = /^# (Part [SF])\./u.exec(line);
    if (partMatch) { part = partMatch[1]; current = null; return; }
    const sectionMatch = /^## ([SF]\d+)\. (.+)$/u.exec(line);
    if (sectionMatch && part) {
      current = { part, id: sectionMatch[1], title: sectionMatch[2].trim(), counts: { "[0]": 0, "[1]": 0, "[2]": 0, "[ ]": 0 } };
      sections.push(current);
      return;
    }
    const row = /^\| (\[[^\]]*\]) \| ([SF]\d+-\d+) \|/u.exec(line);
    if (!row) return;
    const [, marker, id] = row;
    if (!current) { errors.push(`line ${index + 1}: ${id} is outside a section`); return; }
    if (!Object.hasOwn(current.counts, marker)) { errors.push(`line ${index + 1}: ${id} has invalid status ${marker}`); return; }
    if (seen.has(id)) errors.push(`line ${index + 1}: duplicate id ${id} (first at line ${seen.get(id)})`);
    seen.set(id, index + 1);
    if (!id.startsWith(current.id + "-")) errors.push(`line ${index + 1}: ${id} is not in section ${current.id}`);
    current.counts[marker] += 1;
  });
  return { sections, errors };
}

function total(counts) {
  return Object.values(counts).reduce((sum, value) => sum + value, 0);
}

function sum(items) {
  const counts = { "[0]": 0, "[1]": 0, "[2]": 0, "[ ]": 0 };
  for (const item of items) for (const key of Object.keys(counts)) counts[key] += item.counts[key];
  return counts;
}

function percent(counts) {
  const all = total(counts);
  return all === 0 ? "0%" : `${Math.round((counts["[0]"] / all) * 100)}%`;
}

function row(label, counts) {
  return `| ${label} | ${total(counts)} | ${counts["[0]"]} | ${counts["[1]"]} | ${counts["[2]"]} | ${counts["[ ]"]} | ${percent(counts)} |`;
}

function render({ sections }) {
  const header = [
    "| 구분 | 항목 수 | [0] 완료 | [1] 테스트 중 | [2] 개발 중 | [ ] 착수 안 함 | 완료율 |",
    "| --- | --- | --- | --- | --- | --- | --- |",
  ];
  const lines = ["**진행 요약** (`node scripts/plan-progress.mjs --write`로 생성, 완료율 = `[0]` 비율)", "", ...header];
  for (const part of ["Part S", "Part F"]) {
    const items = sections.filter((section) => section.part === part);
    lines.push(row(`**${part === "Part S" ? "화면 (Part S)" : "기능 (Part F)"} 합계**`, sum(items)));
    for (const section of items) lines.push(row(`${section.id}. ${section.title}`, section.counts));
  }
  lines.push(row("**전체**", sum(sections)));
  return lines.join("\n");
}

const text = readFileSync(planPath, "utf8");
const result = parse(text);
if (result.errors.length) {
  console.error(result.errors.join("\n"));
  process.exit(1);
}
const summary = render(result);
if (process.argv.includes("--write")) {
  const start = text.indexOf(START);
  const end = text.indexOf(END);
  if (start < 0 || end < start) {
    console.error("progress markers not found in the plan");
    process.exit(1);
  }
  writeFileSync(planPath, `${text.slice(0, start + START.length)}\n${summary}\n${text.slice(end)}`);
  console.log("plan summary updated");
} else {
  console.log(summary);
}
