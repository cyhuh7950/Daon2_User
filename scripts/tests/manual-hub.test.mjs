import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../../${path}`, import.meta.url), "utf8");

const manifest = {
  schema_version: 1,
  release_version: "2.0.0",
  released_at: "2026-11-11",
  language: "ko-KR",
  documents: [
    {
      document_id: "daon-user-manual", title: "Daon 사용자 설명서", summary: "전체 절차", auth_scope: "public_and_authenticated", version: "2.0.0", language: "ko-KR",
      assets: {
        markdown: { filename: "daon-user-manual.md", href: "/manual/daon-user-manual.md", bytes: 4, sha256: "d".repeat(64), mime: "text/markdown; charset=utf-8" },
        docx: { filename: "daon-user-manual.docx", href: "/manual/daon-user-manual.docx", bytes: 4, sha256: "e".repeat(64), mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" },
        pdf: { filename: "daon-user-manual.pdf", href: "/manual/daon-user-manual.pdf", bytes: 4, sha256: "f".repeat(64), mime: "application/pdf" },
      },
    },
  ],
};

async function withoutManualWebCrypto(run) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  try {
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: undefined });
    await run();
  } finally {
    if (previous) Object.defineProperty(globalThis, "crypto", previous);
    else delete globalThis.crypto;
  }
}

test("S33 WebCrypto 없는 HTTP 조건에서도 배포 원문과 DOCX PDF의 정확한 bytes hash를 검증한다", async (t) => {
  const api = await import("../../apps/web/lib/manual-api.js");
  const current = JSON.parse(await read("apps/web/public/manual/manifest.json"));
  const document = current.documents.find((item) => item.document_id === "daon-user-manual");
  await withoutManualWebCrypto(async () => {
    for (const kind of ["markdown", "docx", "pdf"]) await t.test(kind, async () => {
      const asset = document.assets[kind];
      const original = await readFile(new URL(`../../apps/web/public${asset.href}`, import.meta.url));
      assert.equal(original.byteLength, asset.bytes);
      assert.equal(createHash("sha256").update(original).digest("hex"), asset.sha256);
      const calls = [];
      const fetchImpl = async (url, options) => {
        calls.push(url);
        assert.equal(url, asset.href);
        assert.equal(options.credentials, "same-origin");
        assert.equal(options.cache, "no-store");
        return new Response(original, { headers: { "Content-Type": asset.mime } });
      };
      if (kind === "markdown") {
        const result = await api.readManualDocument(document.document_id, { manifest: current, fetchImpl });
        assert.equal(result.text, original.toString("utf8"));
      } else {
        const result = await api.downloadManualAsset(document.document_id, kind, { manifest: current, fetchImpl });
        assert.equal(result.filename, asset.filename);
        assert.equal(result.mime, asset.mime);
        const downloaded = new Uint8Array(await result.blob.arrayBuffer());
        assert.deepEqual(downloaded, new Uint8Array(original));
        assert.equal(createHash("sha256").update(downloaded).digest("hex"), asset.sha256);
      }
      assert.deepEqual(calls, [asset.href]);
    });
  });
});

test("S33 HTTP 다운로드는 음성 25MiB 한도를 물려받지 않고 설명서 32MiB 경계를 유지한다", async (t) => {
  const api = await import("../../apps/web/lib/manual-api.js");
  await withoutManualWebCrypto(async () => {
    for (const size of [25 * 1024 * 1024 + 1, 32 * 1024 * 1024]) await t.test(`${size} bytes`, async () => {
      const original = Uint8Array.from({ length: size }, (_, index) => index % 251);
      const current = structuredClone(manifest);
      const asset = current.documents[0].assets.pdf;
      asset.bytes = size;
      asset.sha256 = createHash("sha256").update(original).digest("hex");
      let calls = 0;
      const result = await api.downloadManualAsset("daon-user-manual", "pdf", {
        manifest: current,
        fetchImpl: async (url) => {
          calls += 1; assert.equal(url, asset.href);
          return new Response(original, { headers: { "Content-Type": asset.mime } });
        },
      });
      const downloaded = new Uint8Array(await result.blob.arrayBuffer());
      assert.equal(calls, 1); assert.equal(downloaded.byteLength, size);
      assert.deepEqual(downloaded, original);
      assert.equal(createHash("sha256").update(downloaded).digest("hex"), asset.sha256);
    });
    await t.test("32MiB+1 declared bytes rejects before fetch", async () => {
      const current = structuredClone(manifest); current.documents[0].assets.pdf.bytes = 32 * 1024 * 1024 + 1;
      let calls = 0;
      await assert.rejects(api.downloadManualAsset("daon-user-manual", "pdf", {
        manifest: current, fetchImpl: async () => { calls += 1; return new Response(); },
      }), /MANUAL_MANIFEST_INVALID/u);
      assert.equal(calls, 0);
    });
  });
});

test("S33 WebCrypto 없는 DOCX PDF도 hash MIME byte 불일치를 계속 거부한다", async (t) => {
  const api = await import("../../apps/web/lib/manual-api.js");
  const original = new Uint8Array([0, 255, 128, 1, 13, 10, 0, 42]);
  await withoutManualWebCrypto(async () => {
    for (const kind of ["docx", "pdf"]) for (const fault of ["hash", "mime", "bytes"]) await t.test(`${kind} ${fault}`, async () => {
      const current = structuredClone(manifest), asset = current.documents[0].assets[kind];
      asset.bytes = original.byteLength;
      asset.sha256 = createHash("sha256").update(original).digest("hex");
      const wrong = original.slice(); wrong[0] = 1;
      await assert.rejects(api.downloadManualAsset("daon-user-manual", kind, {
        manifest: current, fetchImpl: async () => new Response(fault === "hash" ? wrong : fault === "bytes" ? original.slice(1) : original, {
          headers: { "Content-Type": fault === "mime" ? "application/octet-stream" : asset.mime },
        }),
      }), /MANUAL_CONTENT_INVALID/u);
    });
  });
});

test("Manual Hub client는 allowlisted same-origin manifest만 읽고 bytes/hash/MIME를 검증한다", async () => {
  const api = await import("../../apps/web/lib/manual-api.js");
  const encoder = new TextEncoder();
  const markdownText = "# Daon 사용자 설명서\n\n본문";
  const body = encoder.encode(markdownText);
  const digest = await crypto.subtle.digest("SHA-256", body);
  const sha256 = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
  const safeManifest = structuredClone(manifest);
  safeManifest.documents[0].assets.markdown.bytes = body.byteLength;
  safeManifest.documents[0].assets.markdown.sha256 = sha256;
  const requests = [];
  const fetchImpl = async (path) => {
    requests.push(path);
    if (path === "/manual/manifest.json") return Response.json(safeManifest);
    return new Response(body, { headers: { "Content-Type": "text/markdown; charset=utf-8" } });
  };
  const projected = await api.getManualManifest({ fetchImpl });
  const document = await api.readManualDocument("daon-user-manual", { fetchImpl, manifest: projected });
  assert.equal(document.text, markdownText);
  assert.deepEqual(requests, ["/manual/manifest.json", "/manual/daon-user-manual.md"]);
  await api.getManualManifest({ fetchImpl: async () => new Response(JSON.stringify(safeManifest), { headers: { "Content-Type": "application/json; charset=UTF-8" } }) });

  for (const bad of [
    { ...safeManifest, release_version: "../1.0.0" },
    { ...safeManifest, documents: [{ ...safeManifest.documents[0], document_id: "../secret" }] },
    { ...safeManifest, documents: [{ ...safeManifest.documents[0], assets: { ...safeManifest.documents[0].assets, markdown: { ...safeManifest.documents[0].assets.markdown, href: "https://internal.invalid/manual.md" } } }] },
  ]) {
    await assert.rejects(api.getManualManifest({ fetchImpl: async () => Response.json(bad) }), /MANUAL_MANIFEST_INVALID/u);
  }

  const unapprovedRelease = structuredClone(safeManifest);
  unapprovedRelease.release_version = "9.9.9";
  for (const document of unapprovedRelease.documents) document.version = "9.9.9";
  await assert.rejects(
    api.getManualManifest({ fetchImpl: async () => Response.json(unapprovedRelease) }),
    /MANUAL_MANIFEST_INVALID/u,
  );

  const rogueDocument = structuredClone(safeManifest);
  const rogue = rogueDocument.documents[0];
  rogue.document_id = "rogue-document";
  for (const [kind, extension] of [["markdown", "md"], ["docx", "docx"], ["pdf", "pdf"]]) {
    rogue.assets[kind].filename = `rogue-document.${extension}`;
    rogue.assets[kind].href = `/manual/rogue-document.${extension}`;
  }
  await assert.rejects(
    api.getManualManifest({ fetchImpl: async () => Response.json(rogueDocument) }),
    /MANUAL_MANIFEST_INVALID/u,
  );

  // 2.0.0부터 한 권이다. 은퇴한 문서가 섞이거나 문서가 여러 개이거나 옛 판이면 거부한다.
  const retired = structuredClone(safeManifest);
  const extra = structuredClone(retired.documents[0]);
  extra.document_id = "daon-getting-started";
  for (const [kind, extension] of [["markdown", "md"], ["docx", "docx"], ["pdf", "pdf"]]) {
    extra.assets[kind].filename = `daon-getting-started.${extension}`;
    extra.assets[kind].href = `/manual/daon-getting-started.${extension}`;
  }
  retired.documents.push(extra);
  const onlyRetired = structuredClone(retired);
  onlyRetired.documents = [extra];
  const oldRelease = structuredClone(safeManifest);
  oldRelease.release_version = "1.0.0";
  oldRelease.documents[0].version = "1.0.0";
  for (const bad of [retired, onlyRetired, oldRelease]) {
    await assert.rejects(api.getManualManifest({ fetchImpl: async () => Response.json(bad) }), /MANUAL_MANIFEST_INVALID/u);
  }
  await assert.rejects(api.readManualDocument("unknown", { fetchImpl, manifest: projected }), /MANUAL_DOCUMENT_NOT_FOUND/u);
  await assert.rejects(api.readManualDocument("daon-user-manual", {
    manifest: projected,
    fetchImpl: async () => new Response(body, { headers: { "Content-Type": "text/html" } }),
  }), /MANUAL_CONTENT_INVALID/u);
});

test("Web 읽기는 caller duck manifest를 Network 전에 다시 검증한다", async () => {
  const api = await import("../../apps/web/lib/manual-api.js");
  for (const mutate of [
    (value) => { value.documents[0].assets.markdown.href = "https://internal.invalid/manual.md"; },
    (value) => { value.documents[0].assets.markdown.href = "/manual/../secret.md"; },
    (value) => { value.documents[0].document_id = "rogue-document"; },
    (value) => { value.documents[0].version = "9.9.9"; },
  ]) {
    const duckManifest = structuredClone(manifest);
    mutate(duckManifest);
    let fetchCount = 0;
    await assert.rejects(
      api.readManualDocument("daon-user-manual", {
        manifest: duckManifest,
        fetchImpl: async () => { fetchCount += 1; return new Response(); },
      }),
      /MANUAL_MANIFEST_INVALID/u,
    );
    assert.equal(fetchCount, 0);
  }
});

test("DOCX/PDF 다운로드는 caller duck manifest를 Network 전에 다시 검증한다", async () => {
  const api = await import("../../apps/web/lib/manual-api.js");
  for (const mutate of [
    (value) => { value.documents[0].assets.docx.mime = "application/octet-stream"; },
    (value) => { value.documents[0].assets.pdf.sha256 = "not-a-sha"; },
    (value) => { delete value.documents[0].assets.docx.bytes; },
    (value) => { value.release_version = "9.9.9"; },
  ]) {
    const duckManifest = structuredClone(manifest);
    mutate(duckManifest);
    let fetchCount = 0;
    await assert.rejects(
      api.downloadManualAsset("daon-user-manual", "docx", {
        manifest: duckManifest,
        fetchImpl: async () => { fetchCount += 1; return new Response(); },
      }),
      /MANUAL_MANIFEST_INVALID/u,
    );
    assert.equal(fetchCount, 0);
  }
});

test("Workspace 설정은 검색·Web 읽기·Release·DOCX/PDF 다운로드 Hub를 제공한다", async () => {
  const [shell, actual, css, dockerfile] = await Promise.all([
    read("packages/ui/src/product-workspace-shell.jsx"),
    read("apps/web/components/actual-workspace.jsx"),
    read("packages/ui/src/workspace.css"),
    read("apps/web/Dockerfile"),
  ]);
  assert.match(shell, /사용자 설명서/u);
  assert.match(shell, /manualSearch/u);
  assert.match(shell, /Release/u);
  assert.match(shell, /DOCX/u);
  assert.match(shell, /PDF/u);
  assert.match(actual, /getManualManifest/u);
  assert.match(actual, /readManualDocument/u);
  assert.match(actual, /downloadManualAsset/u);
  assert.match(css, /manual-hub/u);
  assert.match(dockerfile, /COPY --from=builder \/app\/apps\/web\/public \.\/apps\/web\/public/u);
});
