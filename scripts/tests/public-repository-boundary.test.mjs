import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "../..");

// 이 저장소는 비공개이며 문서(docs)는 정상 추적 대상이다. 이 게이트는 공개 여부와
// 무관하게 비밀·서명 자료와 참조 전용 Backup이 Git에 들어가지 않도록 막는다.
// 허용 예외는 값이 없는 예시 파일(.env.example)뿐이다.
const forbiddenPathPatterns = [
  /(?:^|\/)\.env(?:\.[^/]+)?$/u,
  /\.(?:keystore|jks|p12|pfx|pem|key)$/u,
  /(?:^|\/)secrets\//u,
  /^Backup\//u,
  /^\.claude\//u,
];
const allowedPaths = new Set([".env.example"]);

function trackedFiles() {
  return execFileSync("git", ["ls-files", "-z"], { cwd: root, encoding: "utf8" })
    .split("\0")
    .filter(Boolean);
}

function isForbiddenTrackedPath(relativePath) {
  if (allowedPaths.has(relativePath)) return false;
  return forbiddenPathPatterns.some((pattern) => pattern.test(relativePath));
}

test("the boundary classifier flags secrets, signing material and reference-only paths", () => {
  for (const relativePath of [
    ".env",
    ".env.production",
    "apps/mobile/android/app/debug.keystore",
    "keys/release.jks",
    "certs/server.pem",
    "services/api/secrets/object_secret_key",
    "Backup/apps/web/package.json",
    ".claude/settings.json",
  ]) {
    assert.equal(isForbiddenTrackedPath(relativePath), true, relativePath);
  }
  for (const relativePath of [
    ".env.example",
    "docs/daon2-user-studio-design.md",
    "docs/manual/daon-user-manual/index.md",
    "apps/web/public/manual/daon-user-manual.md",
    "services/api/src/daon2_user_api/provider_credentials.py",
  ]) {
    assert.equal(isForbiddenTrackedPath(relativePath), false, relativePath);
  }
});

test("Git tracks no secrets, signing material or reference-only folders", () => {
  const forbidden = trackedFiles().filter(isForbiddenTrackedPath);
  assert.deepEqual(
    forbidden,
    [],
    `repository tracks forbidden files:\n${forbidden.join("\n")}`,
  );
});

test(".gitignore keeps the guarded paths out of Git", () => {
  const gitignore = readFileSync(path.join(root, ".gitignore"), "utf8");
  for (const entry of ["/Backup/", "/.claude/", ".env", "secrets/", "*.keystore", "*.jks", "*.p12"]) {
    assert.ok(
      gitignore.split(/\r?\n/u).includes(entry),
      `.gitignore must contain ${entry}`,
    );
  }
});

test("canonical manuals remain tracked", () => {
  const tracked = trackedFiles();
  assert.ok(tracked.some((item) => item.startsWith("docs/manual/")), "docs/manual must stay tracked");
  assert.ok(
    tracked.some((item) => item.startsWith("apps/web/public/manual/")),
    "web-published manuals must stay tracked",
  );
});

test("public repository boundary is a mandatory security gate", () => {
  const packageJson = JSON.parse(
    readFileSync(path.join(root, "package.json"), "utf8"),
  );
  assert.equal(
    packageJson.scripts["verify:public-repository-boundary"],
    "node --test scripts/tests/public-repository-boundary.test.mjs",
  );

  const policy = JSON.parse(
    readFileSync(path.join(root, "quality-gate-policy.json"), "utf8"),
  );
  assert.deepEqual(
    policy.mandatory_checks.find(
      (check) => check.id === "public-repository-boundary",
    ),
    {
      id: "public-repository-boundary",
      category: "security",
      command: ["npm", "run", "verify:public-repository-boundary"],
      failure_kind: "quality",
      evidence_files: [
        ".gitignore",
        "scripts/tests/public-repository-boundary.test.mjs",
      ],
    },
  );

  const runner = readFileSync(
    path.join(root, "scripts/lib/quality-gate.mjs"),
    "utf8",
  );
  assert.match(
    runner,
    /\["public-repository-boundary", \{ category: "security", kind: null \}\]/u,
  );
});
