"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { msg } from "./studio-messages.ko.js";
import { acceptRefMessage } from "./studio-web-page-bridge.js";

// 웹 페이지 보기(WO-N8). 서버가 정리한 HTML(CSP·고정 동작 스크립트·근거 연결 스크립트)은
// 격리 iframe(srcDoc, sandbox="allow-scripts")으로만 보인다. 다른 방식으로 이 HTML을 화면에 넣지 않는다.

const blockText = (block) => {
  if (block?.type === "bullets") return (block.items ?? []).map(String).join(" · ");
  if (block?.type === "table") return (block.rows ?? []).map((row) => (row ?? []).map(String).join(" | ")).join(" / ");
  if (block?.type === "metric") return `${block.label ?? ""}: ${block.value ?? ""}`;
  return String(block?.text ?? "");
};

/** 근거 부족으로 페이지에서 뺀 글 목록(제목 포함). */
export function excludedItems(body = {}) {
  const items = [];
  if (body.title_insufficient === true && body.title) items.push(String(body.title));
  for (const section of body.sections ?? []) {
    for (const block of section?.blocks ?? []) if (block?.insufficient === true) items.push(blockText(block));
  }
  return items;
}

/** iframe 이름표에 쓸 제목. 근거 부족 제목은 쓰지 않고 근거 확인된 첫 절 제목, 그것도 없으면 유형 이름. */
export function frameTitle(body = {}) {
  const own = body.title_insufficient === true ? "" : String(body.title ?? "").trim();
  const heading = (body.sections ?? []).find((section) => (section?.blocks ?? []).some((block) => block && block.insufficient !== true))?.heading;
  const title = own || String(heading ?? "").trim();
  return title ? msg("studio.web_page.frame", { title }) : msg("studio.tile.web_page");
}

/** 격리 iframe. 보기·고친 안 미리보기가 같은 것을 쓴다. */
export function WebPageFrame({ html, title, frameRef }) {
  return <iframe ref={frameRef} className="studio-web-page__frame" srcDoc={html} sandbox="allow-scripts" referrerPolicy="no-referrer" title={title} />;
}

/** 근거 칸 안에서만 스크롤한다. 항목이 이미 보이면 그대로, 위로 벗어나면 위 끝, 아래로 벗어나면 아래 끝을 맞춘다. */
export function paneScrollTop({ itemTop, itemHeight, scrollTop, paneHeight }) {
  if (itemTop < scrollTop) return itemTop;
  if (itemTop + itemHeight > scrollTop + paneHeight) return Math.max(0, itemTop + itemHeight - paneHeight);
  return scrollTop;
}

const whereOf = (item) => item?.locator_kind === "page" ? msg("dialog.page_suffix", { n: item.locator_value }) : item?.locator_value ?? "";

export function WebPageViewer({ content, evidence = [], onOpenEvidence }) {
  const body = content?.body ?? {};
  const html = typeof body.html === "string" ? body.html : "";
  const excluded = useMemo(() => excludedItems(body), [body]);
  const knownRefs = useMemo(() => new Set(evidence.map((item) => item.ref_id)), [evidence]);
  const [active, setActive] = useState(null);
  const frameRef = useRef(null);
  const itemRefs = useRef(new Map());
  const paneRef = useRef(null);
  const latest = useRef({ knownRefs, onOpenEvidence });
  latest.current = { knownRefs, onOpenEvidence };

  useEffect(() => {
    const target = globalThis.window;
    if (!target?.addEventListener) return undefined;
    const onMessage = (event) => {
      const ref = acceptRefMessage(event, frameRef.current?.contentWindow, latest.current.knownRefs);
      if (!ref) return;
      setActive(ref);
      // scrollIntoView는 바깥 칸까지 움직이므로 쓰지 않고, 근거 칸(position:relative)의 scrollTop만 바꾼다.
      const item = itemRefs.current.get(ref);
      const pane = paneRef.current;
      if (item && pane) pane.scrollTop = paneScrollTop({ itemTop: item.offsetTop, itemHeight: item.offsetHeight, scrollTop: pane.scrollTop, paneHeight: pane.clientHeight });
      latest.current.onOpenEvidence?.(ref);
    };
    target.addEventListener("message", onMessage);
    return () => target.removeEventListener("message", onMessage);
  }, []);

  return <div className="studio-web-page">
    <div className="studio-web-page__page">
      <WebPageFrame html={html} title={frameTitle(body)} frameRef={frameRef} />
    </div>
    <aside ref={paneRef} className="studio-web-page__evidence" aria-label={msg("studio.dialog.provenance.evidence")}>
      {excluded.length > 0 && <div className="studio-web-page__excluded">
        <p role="note">{msg("studio.web_page.excluded", { n: excluded.length })}</p>
        <ul>{excluded.map((text, index) => <li key={index}>{text}</li>)}</ul>
      </div>}
      <h3>{msg("studio.dialog.provenance.evidence")}</h3>
      <ol className="studio-web-page__refs">{evidence.map((item) => <li key={item.ref_id} data-ref={item.ref_id}
        aria-current={active === item.ref_id ? "true" : undefined}
        ref={(node) => { if (node) itemRefs.current.set(item.ref_id, node); else itemRefs.current.delete(item.ref_id); }}>
        <button type="button" onClick={() => { setActive(item.ref_id); onOpenEvidence?.(item.ref_id); }}>
          <strong>[{item.ref_id}]</strong> {item.source_name ?? item.external_ref?.name ?? ""} {whereOf(item)}
        </button>
      </li>)}</ol>
    </aside>
  </div>;
}

export default WebPageViewer;
