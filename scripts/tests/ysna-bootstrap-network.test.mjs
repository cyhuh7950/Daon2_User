import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "../..");
const toPosix = (value) => value.replaceAll("\\", "/");

// 서버를 새로 세우는 상황을 임시 폴더에서 재현한다. docker는 호출 인자만 기록하는 가짜로 바꾼다.
function runBootstrap({ networkExists }) {
  const dir = mkdtempSync(path.join(tmpdir(), "ysna-bootstrap-"));
  try {
    const deployDir = path.join(dir, "deploy", "daon2-user");
    const binDir = path.join(dir, "bin");
    const dockerLog = path.join(dir, "docker.log");
    mkdirSync(deployDir, { recursive: true });
    mkdirSync(binDir, { recursive: true });
    copyFileSync(
      path.join(root, "deploy/daon2-user/ysna-bootstrap.sh"),
      path.join(deployDir, "ysna-bootstrap.sh"),
    );
    writeFileSync(
      path.join(binDir, "docker"),
      [
        "#!/usr/bin/env bash",
        'echo "$*" >> "$DOCKER_LOG"',
        `if [ "$1 $2" = "network inspect" ]; then exit ${networkExists ? 0 : 1}; fi`,
        "exit 0",
        "",
      ].join("\n"),
      { mode: 0o755 },
    );
    execFileSync("bash", [toPosix(path.join(deployDir, "ysna-bootstrap.sh"))], {
      cwd: dir,
      stdio: "pipe",
      env: {
        ...process.env,
        PATH: `${binDir}${path.delimiter}${process.env.PATH}`,
        DOCKER_LOG: toPosix(dockerLog),
        DAON_GATEWAY_URL: "https://example.test",
        DAON_TRUSTED_PROXY_IPS: "127.0.0.1",
        DAON_REFERENCE_ENV: toPosix(path.join(dir, "missing-reference")),
      },
    });
    return existsSync(dockerLog) ? readFileSync(dockerLog, "utf8") : "";
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("bootstrap creates proxy-network on a new server", () => {
  assert.match(runBootstrap({ networkExists: false }), /^network create proxy-network$/mu);
});

test("bootstrap leaves an existing proxy-network alone", () => {
  assert.doesNotMatch(runBootstrap({ networkExists: true }), /network create/u);
});
