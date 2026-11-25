"use client";

import { useEffect, useState } from "react";
import { ManualHubView } from "@daon2-user/ui/manual-hub-view";
import { downloadManualAsset, getManualManifest, readManualDocument } from "../lib/manual-api.js";

function saveDownload(result) {
  const href = URL.createObjectURL(result.blob);
  const link = document.createElement("a");
  link.href = href; link.download = result.filename; link.click();
  queueMicrotask(() => URL.revokeObjectURL(href));
}

export function ManualSettingsPane() {
  const [manifest, setManifest] = useState(null);
  const [selected, setSelected] = useState(null);
  const [pending, setPending] = useState(true);
  const [safeError, setSafeError] = useState(null);
  const load = async () => { setPending(true); setSafeError(null); try { setManifest(await getManualManifest()); } catch { setSafeError("MANUAL_UNAVAILABLE"); } finally { setPending(false); } };
  useEffect(() => { void load(); }, []);
  const read = async (documentId) => { if (!manifest || pending) return; setPending(true); setSafeError(null); try { setSelected(await readManualDocument(documentId, { manifest })); } catch { setSafeError("MANUAL_CONTENT_INVALID"); } finally { setPending(false); } };
  const download = async (documentId, format) => { if (!manifest || pending) return; setPending(true); setSafeError(null); try { saveDownload(await downloadManualAsset(documentId, format, { manifest })); } catch { setSafeError("MANUAL_CONTENT_INVALID"); } finally { setPending(false); } };

  // N1-B15: 노트북 안 설명서 창과 같은 공용 화면(목차·칸 안 스크롤)을 쓴다.
  return <main className="common-settings-page manual-settings-page" aria-labelledby="manual-settings-title">
    <header className="common-settings-header"><a href="/notebooks">Notebook으로</a><h1 id="manual-settings-title">사용자 설명서</h1></header>
    <ManualHubView manifest={manifest} document={selected} pending={pending} blocked={Boolean(safeError)} onRead={(documentId) => void read(documentId)} onDownload={(documentId, format) => void download(documentId, format)}>
      {pending && !manifest ? <p role="status" className="common-settings-state">사용자 설명서를 불러오고 있습니다.</p> : null}
      {safeError ? <div role="alert" className="common-settings-error"><strong>사용자 설명서를 처리하지 못했습니다.</strong><span>{safeError}</span><button type="button" onClick={() => void load()}>다시 시도</button></div> : null}
    </ManualHubView>
  </main>;
}
