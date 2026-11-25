"use client";

// 설명서 Hub 화면(N1-B15). 노트북 안 설명서 창과 설정 → 사용자 설명서 페이지가 함께 쓴다.
// 위 도구줄(Release·검색) + 아래 두 칸(왼쪽 문서·목차, 오른쪽 본문). 칸 안에서만 세로 스크롤한다.
// 문서를 열면 부·절 목차를 보이고, 절을 누르면 본문이 그 절로 이동한다. 문서가 하나뿐이면 바로 연다.
// 불러오기·내려받기는 화면마다 다른 API를 쓰므로 onRead·onDownload로 받는다. children은 상태·오류 안내 자리다.
import { useEffect, useRef, useState } from "react";
import { ManualMarkdown } from "./manual-markdown.jsx";
import { filterManualToc, manualToc } from "./manual-toc.js";
import "./manual-hub.css";

export function ManualHubView({ manifest, document: opened, pending = false, blocked = false, onRead, onDownload, className = "", children = null }) {
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(null);
  const sideRef = useRef(null);
  const readerRef = useRef(null);
  const documents = manifest?.documents ?? [];

  // 문서가 하나뿐이면 바로 연다. 오류가 나면(blocked) 다시 시도하지 않는다.
  useEffect(() => {
    if (documents.length === 1 && !opened && !pending && !blocked) onRead?.(documents[0].document_id);
  }, [manifest, opened, pending, blocked]); // eslint-disable-line react-hooks/exhaustive-deps
  // 지금 읽는 절이 바뀌면 왼쪽 목차에서도 그 항목이 보이게 한다(목차 칸 안에서만 움직임).
  useEffect(() => {
    if (!active) return;
    sideRef.current?.querySelector(`button[data-section="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const query = search.trim().toLocaleLowerCase("ko-KR");
  // 문서를 열기 전에는 문서 카드를, 연 뒤에는 목차의 절 이름을 거른다.
  const visibleDocuments = documents.filter((item) => opened || `${item.title} ${item.summary}`.toLocaleLowerCase("ko-KR").includes(query));
  const toc = opened ? filterManualToc(manualToc(opened.text), search) : [];
  const openSection = (id) => {
    setActive(id);
    readerRef.current?.querySelector(`[id="${id}"]`)?.scrollIntoView({ block: "start" });
  };
  // 본문을 스크롤하면 위쪽에 걸린 절을 목차에 표시한다.
  const trackSection = (event) => {
    const body = event.target;
    if (!(body instanceof HTMLElement) || !body.classList.contains("manual-reader-body")) return;
    const top = body.getBoundingClientRect().top + 24;
    let current = null;
    for (const heading of body.querySelectorAll("h4[id]")) {
      if (heading.getBoundingClientRect().top <= top) current = heading.id;
      else break;
    }
    if (current && current !== active) setActive(current);
  };

  return <div className={`manual-hub ${className}`.trim()} aria-live="polite">
    <div className="manual-hub-toolbar">
      <div><strong>Daon 문서 Hub</strong><small>{manifest ? `Release ${manifest.release_version} · ${manifest.language}` : "Release 정보를 확인하고 있습니다."}</small></div>
      <label><span className="sr-only">설명서 검색</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="문서·절 이름 검색" disabled={!manifest} /></label>
    </div>
    {children}
    <div className="manual-hub-layout">
      <div className="manual-hub-side" ref={sideRef}>
        <nav className="manual-document-list" aria-label="Daon 설명서 목록">
          {visibleDocuments.map((item) => <article key={item.document_id} data-manual-scope={item.auth_scope}>
            <button type="button" aria-pressed={opened?.document_id === item.document_id} disabled={pending} onClick={() => onRead?.(item.document_id)}><strong>{item.title}</strong><small>{item.summary}</small><span>Web에서 읽기</span></button>
            <div><button type="button" disabled={pending} onClick={() => onDownload?.(item.document_id, "docx")}>DOCX</button><button type="button" disabled={pending} onClick={() => onDownload?.(item.document_id, "pdf")}>PDF</button></div>
          </article>)}
        </nav>
        {opened ? <nav className="manual-toc" aria-label="설명서 목차">
          {toc.length ? <ol>{toc.map((item) => <li key={item.id} data-level={item.level}>
            <button type="button" data-section={item.id} aria-current={active === item.id ? "location" : undefined} onClick={() => openSection(item.id)}>{item.title}</button>
          </li>)}</ol> : <p>찾는 절이 없습니다.</p>}
        </nav> : null}
      </div>
      <article className="manual-reader" aria-label="선택한 설명서 본문" ref={readerRef} onScrollCapture={trackSection}>
        {opened ? <><header><div><strong>{opened.title}</strong><small>검증된 Release Markdown 정본</small></div></header><ManualMarkdown text={opened.text} /></> : <div className="manual-reader-empty"><span aria-hidden="true">▤</span><strong>{pending ? "설명서를 여는 중입니다." : "읽을 문서를 선택해 주세요."}</strong><small>문서별 공개 범위와 로그인 후 조직 전용 절차를 구분해 제공합니다.</small></div>}
      </article>
    </div>
  </div>;
}

export default ManualHubView;
