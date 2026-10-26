"""Studio v2 서비스: 저장소 + 내보내기 + 근거 콘텐츠(+후속: 질문 답변 메모 변환)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .question_answering_postgres import PostgresQuestionAnsweringRepository, QuestionContext, QuestionRepositoryError
from .studio_v2_export import StudioV2Export, export_asset, export_v2, safe_stem
from .studio_v2_postgres import PostgresStudioV2Repository
from .studio_v2_types import STUDIO_V2_TYPES
from .studio_workspace import StudioContext, StudioError

_MAX_EXCERPT_CHARS = 32_768


@dataclass(frozen=True, slots=True)
class EvidenceContent:
    body: bytes
    media_type: str
    headers: dict[str, str] = field(default_factory=dict)


_MEDIA_KINDS = {"audio_overview": "mp3", "video_overview": "mp4"}


class StudioV2Service(PostgresStudioV2Repository):
    def __init__(self, cloud_store, *, object_storage=None, clock=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(cloud_store, clock=clock)
        self._object_storage = object_storage
        self._knowledge_status = None
        self._knowledge_stale: dict[tuple[str, str, str], bool] = {}

    def set_knowledge_status(self, checker) -> None:  # type: ignore[no-untyped-def]
        """checker(context, external_ref) -> True(지식 버전이 바뀜)/False(최신)/None(확인 불가). MCP Connector 연동 시 runtime이 설정한다."""
        self._knowledge_status = checker

    def knowledge_changed(self, context: StudioContext, output_id: str, revision: int | None = None) -> bool:
        """저장된 MCP 근거 스냅샷의 문서 버전이 지식 서버에서 바뀌었는지 확인한다(확인 불가는 stale로 보지 않는다)."""
        if self._knowledge_status is None:
            return False
        cache_key = (context.tenant_id, context.workspace_id, output_id)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            head = self._owned_output(connection, context, output_id)
            number = int(head[8]) if revision is None else revision
            rows = connection.execute(
                "SELECT DISTINCT external_ref FROM studio_v2_evidence WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s "
                "AND left(origin,4)='mcp_' AND external_ref IS NOT NULL LIMIT 10",
                (context.tenant_id, context.workspace_id, output_id, number)).fetchall()
        seen: set[tuple[object, ...]] = set()
        for (ref,) in rows:
            key = (ref.get("connector_id"), ref.get("document_id"), ref.get("version_id"))
            if key in seen or not ref.get("document_id") or not ref.get("version_id"):
                continue
            seen.add(key)
            try:
                if self._knowledge_status(context, ref) is True:
                    self._knowledge_stale[cache_key] = True
                    return True
            except Exception:  # noqa: BLE001 — 지식 서버 장애가 산출물 조회를 막으면 안 된다
                continue
        self._knowledge_stale.pop(cache_key, None)
        return False

    def apply_knowledge_stale(self, context: StudioContext, items: list[dict[str, object]]) -> None:
        """상세 조회에서 확인된 지식 변경(stale)을 목록 카드에도 반영한다(목록 조회 때마다 지식 서버를 부르지 않는다)."""
        for item in items:
            if self._knowledge_stale.get((context.tenant_id, context.workspace_id, str(item.get("output_id")))):
                item["stale"] = True

    def export(self, context: StudioContext, output_id: str, format_name: str, revision: int | None) -> StudioV2Export:
        output = self.get_output(context, output_id, revision)
        spec = STUDIO_V2_TYPES[str(output["type_id"])]
        if format_name not in spec.export_formats:
            raise StudioError("EXPORT_FORMAT_UNSUPPORTED", 400)
        content = (output.get("revision") or {}).get("content") or {}
        choices = content.get("output_choices") if str(output["type_id"]) == "authored_document" else None
        if isinstance(choices, list) and choices and format_name != "pdf" and format_name not in choices:
            raise StudioError("EXPORT_FORMAT_UNSUPPORTED", 400)  # 템플릿이 제공하지 않는 형식(예: 약관·계약서의 PPTX)
        if output.get("revision") is None:
            raise StudioError("STUDIO_VERSION_CONFLICT", 409)
        type_id = str(output["type_id"])
        if type_id in _MEDIA_KINDS:
            stem = safe_stem(str(output.get("title", "")))
            if type_id == "video_overview" and format_name == "vtt":
                from .studio_video import render_vtt
                return export_asset(stem, "vtt", render_vtt(content.get("body") or {}))
            asset = self.get_asset(context, output_id, format_name)
            return export_asset(stem, format_name, asset["content"])  # type: ignore[arg-type]
        return export_v2(format_name, output)

    def get_media(self, context: StudioContext, output_id: str, type_id: str) -> dict[str, object]:
        """오디오·동영상 개요의 재생용 자산(mp3·mp4). 완료된 해당 유형 산출물만."""
        output = self.get_output(context, output_id, None)
        if str(output["type_id"]) != type_id or output.get("status") != "completed":
            raise StudioError("RESOURCE_UNAVAILABLE", 404)
        return self.get_asset(context, output_id, _MEDIA_KINDS[type_id])

    def get_audio(self, context: StudioContext, output_id: str) -> dict[str, object]:
        return self.get_media(context, output_id, "audio_overview")

    def get_video(self, context: StudioContext, output_id: str) -> dict[str, object]:
        return self.get_media(context, output_id, "video_overview")

    def create_memo_from_run_result(self, context: StudioContext, run_result_id: str, title: str | None, idempotency_key: str):
        """채팅 답변(run_results)과 인용(citations)을 메모로 변환한다. 같은 노트북의 대화에서 만든 답변만 허용한다."""
        notebook_id = self._require_notebook(context)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            head = connection.execute(
                "SELECT rr.canonical_json->>'answer',COALESCE((rr.canonical_json->>'insufficient')::boolean,false) "
                "FROM run_results rr JOIN runs r ON r.tenant_id=rr.tenant_id AND r.workspace_id=rr.workspace_id AND r.record_id=rr.run_id "
                "JOIN notebook_bindings nb ON nb.tenant_id=r.tenant_id AND nb.workspace_id=r.workspace_id "
                "AND nb.binding_kind='conversation_thread' AND nb.record_id=r.conversation_id "
                "WHERE rr.tenant_id=%s AND rr.workspace_id=%s AND rr.record_id=%s AND nb.notebook_id=%s",
                (context.tenant_id, context.workspace_id, run_result_id, notebook_id)).fetchone()
            if head is None or not head[0]:
                raise StudioError("RESOURCE_UNAVAILABLE", 404)
            if head[1]:
                raise StudioError("STUDIO_INPUT_INVALID", 400)
            rows = connection.execute(
                "SELECT c.source_version_id,c.evidence_span_id,c.canonical_json->'locator',c.canonical_json->>'page' FROM citations c "
                "WHERE c.tenant_id=%s AND c.workspace_id=%s AND c.run_result_id=%s ORDER BY c.record_id",
                (context.tenant_id, context.workspace_id, run_result_id)).fetchall()
        refs = []
        for index, (version, span, locator, page) in enumerate(rows, 1):
            loc = locator if isinstance(locator, dict) else {"kind": "page", "value": page}
            refs.append({"ref_id": f"S{index}", "source_version_id": version, "evidence_span_id": span,
                         "locator_kind": loc.get("kind"), "locator_value": str(loc.get("value")), "origin": "notebook_source"})
        suffix = ("\n\n" + " ".join(f"[{r['ref_id']}]" for r in refs)) if refs else ""
        markdown = str(head[0]) + suffix
        return self.create_memo(context, title, markdown, idempotency_key, refs=refs)

    def evidence_content(self, context: StudioContext, output_id: str, ref_id: str, revision: int | None) -> EvidenceContent:
        """근거 보기용 원문. PDF는 원본 PDF(+쪽), 그 밖의 형식은 근거 구간 텍스트(JSON)."""
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            head = self._owned_output(connection, context, output_id)
            number = int(head[8]) if revision is None else revision
            ref = connection.execute(
                "SELECT source_version_id,evidence_span_id,locator_kind,locator_value,origin,external_ref "
                "FROM studio_v2_evidence WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s AND ref_id=%s",
                (context.tenant_id, context.workspace_id, output_id, number, ref_id)).fetchone()
            if ref is None:
                raise StudioError("RESOURCE_UNAVAILABLE", 404)
            if ref[4] != "notebook_source":
                # MCP 근거는 생성 당시 저장한 불변 스냅샷을 그대로 돌려준다.
                body = json.dumps({"origin": ref[4], "snapshot": ref[5]}, ensure_ascii=False).encode("utf-8")
                return EvidenceContent(body, "application/json", {"x-citation-locator-kind": str(ref[2] or "")})
            source_version_id, span_id, kind, value = str(ref[0]), ref[1], ref[2], ref[3]
            row = connection.execute(
                "SELECT sv.source_id,COALESCE(sv.canonical_json->>'filename',s.canonical_json->>'filename',sv.record_id),"
                "es.canonical_json FROM source_versions sv JOIN sources s ON s.tenant_id=sv.tenant_id AND s.workspace_id=sv.workspace_id "
                "AND s.record_id=sv.source_id LEFT JOIN evidence_spans es ON es.tenant_id=sv.tenant_id AND es.workspace_id=sv.workspace_id "
                "AND es.record_id=%s AND es.source_version_id=sv.record_id "
                "WHERE sv.tenant_id=%s AND sv.workspace_id=%s AND sv.record_id=%s "
                "AND NOT EXISTS(SELECT 1 FROM deletion_requests d WHERE d.tenant_id=sv.tenant_id AND d.workspace_id=sv.workspace_id "
                "AND d.source_id=sv.source_id AND d.source_active=false) "
                "AND NOT EXISTS(SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=sv.tenant_id AND u.workspace_id=sv.workspace_id "
                "AND u.notebook_id=%s AND u.source_version_id=sv.record_id) "
                "AND NOT EXISTS(SELECT 1 FROM identity_auth_source_access a WHERE a.tenant_id=sv.tenant_id AND a.workspace_id=sv.workspace_id "
                "AND a.source_version_id=sv.record_id AND a.user_id=%s AND a.allowed=0)",
                (span_id, context.tenant_id, context.workspace_id, source_version_id, context.notebook_id, context.actor_id)).fetchone()
        if row is None:
            raise StudioError("RESOURCE_UNAVAILABLE", 404)
        source_id, filename, evidence = str(row[0]), str(row[1]), row[2] if isinstance(row[2], dict) else {}
        headers = {"x-citation-locator-kind": str(kind or "")}
        if kind == "page" and self._object_storage is not None and str(value or "").isdigit():
            try:
                pdf = PostgresQuestionAnsweringRepository(self._cloud_store, self._object_storage).read_current_pdf(
                    QuestionContext(context.tenant_id, context.workspace_id, context.actor_id, context.trace_id,
                                    context.policy_version, context.notebook_id), source_id, source_version_id)
                headers["x-citation-page"] = str(value)
                return EvidenceContent(pdf.content, "application/pdf", headers)
            except QuestionRepositoryError:
                pass  # PDF가 아니거나 읽을 수 없으면 구간 텍스트로 대체한다.
        text = str(evidence.get("text", ""))[:_MAX_EXCERPT_CHARS]
        if not text and kind and value is not None:
            # 근거 구간(span)이 없는 로케이터는 본문에서 다시 찾는다(생성기가 만든 쪽·섹션 근거).
            from .studio_source_reader import StudioSourceReader
            found = StudioSourceReader(self._cloud_store).read_section(context, source_version_id, str(kind), str(value))
            if found is not None:
                filename, text = found[0], found[1][:_MAX_EXCERPT_CHARS]
        body = json.dumps({"filename": filename, "locator": {"kind": kind, "value": value}, "page": evidence.get("page"),
                           "text": text}, ensure_ascii=False).encode("utf-8")
        if value is not None and kind == "page":
            headers["x-citation-page"] = str(value)
        return EvidenceContent(body, "application/json", headers)
