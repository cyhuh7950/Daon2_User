"""작성 문서 내보내기: DOCX(표지·목차·본문·부록 A/B/C)와 PPTX(발표용 요약). WO-A1 T-A1-10."""

from __future__ import annotations

import re
from typing import Any, Mapping

NOTICE = "AI 작성 초안, 전문가 검토 필요"
STATUS_LABEL = {"covered": "대응", "partial": "부분 대응", "missing": "누락"}
DIFF_LABEL = {"unchanged": "유지", "modified": "수정", "new": "신규"}
RELATION_LABEL = {"related": "관련", "possible_conflict": "충돌 가능(확인 필요)"}


def _where(item: Mapping[str, Any]) -> str:
    return f"{item.get('locator_value')}쪽" if item.get("locator_kind") == "page" else str(item.get("locator_value") or "")


def document_of(output: Mapping[str, Any]) -> Mapping[str, Any]:
    content = (output.get("revision") or {}).get("content") or {}
    document = content.get("document")
    if not isinstance(document, Mapping):
        return {}
    return document


def authored_elements(output: Mapping[str, Any]) -> list[tuple]:
    doc = document_of(output)
    if not doc:
        return [("title", str(output.get("title", ""))), ("p", "아직 작성이 끝나지 않은 문서입니다.", [])]
    notice = str(doc.get("notice") or NOTICE)
    els: list[tuple] = [("title", str(doc["title"])), ("p", notice, []), ("pagebreak",), ("h1", "목차")]
    els += [("p", f"{section['title']}", []) for section in doc["sections"]]
    els.append(("pagebreak",))
    for section in doc["sections"]:
        els.append(("h1", section["title"]))
        for paragraph in section["paragraphs"]:
            text = paragraph["text"]
            tag = (paragraph.get("diff") or {}).get("tag")
            if tag in ("modified", "new"):  # 약관: 기준 대비 수정·신규 문장을 본문에서 표시한다
                text = f"[{DIFF_LABEL[tag]}] {text}"
            els.append(("p", text, paragraph.get("refs", [])))
        if section.get("delete_suggested"):
            els += [("h2", f"{section['title']} — 삭제 제안(기준 약관에만 있는 문장)"), ("bullets", list(section["delete_suggested"]), [])]
    titles = {s["key"]: s["title"] for s in doc["sections"]}
    if doc.get("style", "proposal") == "proposal":
        # 부록 A: 요구사항 대응표
        els += [("pagebreak",), ("h1", "부록 A. 요구사항 대응표")]
        rows = [["ID", "요구사항", "대응 섹션", "상태"]]
        for row in doc.get("coverage", []):
            rows.append([row["requirement_id"], row["text"], titles.get(row.get("section_key"), "-"), STATUS_LABEL.get(row["status"], row["status"])])
        els.append(("table", rows))
    else:
        els.append(("pagebreak",))
    # 점검 결과(RuleSet·변경 요약·법령 대조)
    for check in doc.get("checks", []):
        if check.get("id") == "terms_change_summary" and check.get("summary"):
            summary = check["summary"]
            els += [("h2", check["title"]), ("table", [["구분", "문장 수"], ["유지", str(summary.get("unchanged", 0))], ["수정", str(summary.get("modified", 0))],
                                                       ["신규", str(summary.get("new", 0))], ["삭제 제안", str(summary.get("delete_suggested", 0))]])]
        elif check.get("id") == "law_crosscheck" and check.get("rows"):
            els += [("h2", check["title"]), ("p", str(check.get("notice") or ""), []),
                    ("table", [["조항", "관련 법령 조문", "판단", "메모"], *[[r["section_title"], r["law"], RELATION_LABEL.get(r["relation"], r["relation"]), r.get("note", "")] for r in check["rows"]]])]
        elif check.get("id") == "evidence_integrity" and check.get("summary"):
            summary = check["summary"]
            els += [("h2", check["title"]), ("p", f"근거 확인 {summary.get('verified', 0)}건 · 근거 미확인 {summary.get('unverified', 0)}건", [])]
            if check.get("items"):
                els.append(("bullets", [f"{i.get('section_title', '')}: {i.get('text', '')}" for i in check["items"]], []))
        elif check.get("id") == "term_consistency" and check.get("summary"):
            els += [("h2", check["title"]), ("p", f"혼용 {check['summary'].get('mixed', 0)}건 · 동의어만 사용 {check['summary'].get('synonym_only', 0)}건", [])]
            if check.get("items"):
                els.append(("bullets", [f"\"{i['found']}\" → 기준 용어 \"{i['preferred']}\" ({i['count']}회)" for i in check["items"]], []))
        elif check.get("results"):
            els += [("h2", check["title"]), ("table", [["규칙", "결과", "설명"], *[[r["rule_id"], r["status"], r.get("message", "")] for r in check["results"]]])]
        elif check.get("status") == "skipped":
            els.append(("p", f"{check['title']}: 점검하지 못했습니다({check.get('reason')}).", []))
    # 부록 B: 근거 목록
    if output.get("evidence"):
        els += [("pagebreak",), ("h1", "부록 B. 근거 목록"), ("table", [["번호", "출처", "위치"], *[[f"[{e['ref_id']}]", str(e.get("source_name") or e.get("origin") or ""), _where(e)] for e in output["evidence"]]])]
    # 부록 C: 가정·미결 항목
    els += [("pagebreak",), ("h1", "부록 C. 가정과 미결 항목")]
    if doc.get("assumptions"):
        els.append(("bullets", [f"{a['key']}: {a['reason']} → {a['default']}" for a in doc["assumptions"]], []))
    els.append(("bullets", doc.get("open_items") or ["미결 항목 없음"], []))
    return els


def authored_slides(output: Mapping[str, Any]) -> list[dict[str, Any]]:
    """발표용 슬라이드: 표지 + 섹션별 핵심 문장(최대 5개) + 요구사항 대응 요약. 문서의 문장만 쓴다(새 사실 없음)."""
    doc = document_of(output)
    notice = str(doc.get("notice") or NOTICE)
    slides: list[dict[str, Any]] = [{"layout": "title", "title": str(doc.get("title", output.get("title", ""))), "bullets": [notice], "notes": "", "refs": []}]
    for section in doc.get("sections", []):
        bullets, refs = [], []
        for paragraph in section["paragraphs"]:
            sentence = re.split(r"(?<=[.다요])\s+", paragraph["text"].strip())[0][:80]
            if sentence:
                bullets.append(sentence)
                refs += paragraph.get("refs", [])
            if len(bullets) >= 5:
                break
        slides.append({"layout": "bullets", "title": re.sub(r"^\d+\.\s*", "", section["title"]), "bullets": bullets,
                       "notes": " ".join(p["text"] for p in section["paragraphs"])[:800], "refs": list(dict.fromkeys(refs))[:6]})
    coverage = doc.get("coverage", [])
    if coverage:
        counts = {s: sum(1 for c in coverage if c["status"] == s) for s in ("covered", "partial", "missing")}
        slides.append({"layout": "table", "title": "요구사항 대응 현황", "bullets": [], "refs": [],
                       "table": {"columns": ["상태", "건수"], "rows": [[STATUS_LABEL[k], str(v)] for k, v in counts.items()]}, "notes": f"총 {len(coverage)}건"})
    slides[-1]["notes"] = (slides[-1].get("notes", "") + "\n" + notice).strip()
    return slides
