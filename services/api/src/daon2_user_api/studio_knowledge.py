"""스튜디오가 선택한 승인 지식을 근거 구간으로 가져온다(WO-K4 4단계). 무엇을 찾을지는 LLM에 묻는다."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from .authoring.agent import UNIT_PLAN_SCHEMA, UNIT_PLAN_SYSTEM
from .question_external_evidence import EXTERNAL_LIMIT, ExternalEvidence, ExternalEvidenceError, build_plan_prompt, default_requests, parse_plan, run_planned
from .studio_context_builder import ContextPack, Passage
from .studio_text_generation import StudioPrompt, StudioTextGenerator
from .studio_v2_generation import GenerationContext
from .studio_workspace import StudioContext, StudioError


MAX_UNITS = 5
UNIT_EVIDENCE_LIMIT = 3
UNITS_SCHEMA = {"type": "object", "properties": {"units": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}}}, "required": ["units"]}


def _key(ref: Any) -> tuple[Any, Any, Any]:
    return ref.get("connector_id"), ref.get("version_id"), ref.get("block_id")


def _next_number(pack: ContextPack) -> int:
    numbers = [int(p.ref[1:]) for p in pack.passages if p.ref[1:].isdigit()]
    return max(numbers, default=0) + 1


def _passage(item: ExternalEvidence, ref: str) -> Passage:
    external = {"connector_id": item.connector_id, "tool": "search_document_evidence", "document_id": item.document_id, "version_id": item.document_version_id,
                "project_id": item.project_id, "work_package_id": item.work_package_id, "block_id": item.block_id, "name": item.document_name or "문서", "excerpt": item.text[:1200], "resource_uri": ""}
    return Passage(ref, "", "", item.document_name or "문서", None, "page", str(item.page), None, item.text[:1200], external)


class StudioKnowledge:
    def __init__(self, llm: StudioTextGenerator, finder: Any) -> None:
        self._llm, self._finder = llm, finder

    def plan_units(self, ctx: GenerationContext, label: str, focus: str) -> tuple[str, ...]:
        """이번 산출물을 어떤 단위로 구성할지 LLM에 묻는다. 지식을 고르지 않았거나 답을 못 받으면 단위 없이 진행한다."""
        try:
            if self._finder.prepare(ctx.context) is None:
                return ()
        except ExternalEvidenceError:
            return ()
        prompt = StudioPrompt(system="산출물 구성 도구입니다. 산출물을 이루는 주제 단위를 정합니다. JSON 객체 하나만 출력합니다.", user=f"[산출물] {label}\n[주제] {focus or '선택한 지식 전체'}\n주제 단위를 3~5개 정하세요.",
                              json_schema=UNITS_SCHEMA, max_output_tokens=300, prompt_version="studio-knowledge-units-v1", schema_name="studio_knowledge_units")
        try:
            rows = self._llm.generate(ctx.context, prompt, cancel_check=ctx.cancel_check).data.get("units")
        except (StudioError, ValueError, KeyError, TypeError):
            return ()
        titles = [str(row["title"]).strip()[:80] for row in rows if isinstance(row, Mapping) and str(row.get("title") or "").strip()] if isinstance(rows, list) else []
        return tuple(titles[:MAX_UNITS])

    def available(self, context: StudioContext) -> bool:
        try:
            return self._finder.prepare(context) is not None
        except ExternalEvidenceError:
            return False

    def find_requested(self, context: StudioContext, question: str, *, limit: int = EXTERNAL_LIMIT, cancel_check: Callable[[], None] | None = None) -> tuple[ExternalEvidence, ...]:
        """LLM이 찾으라고 한 것만 찾는다. 계획이 비어 있으면 찾지 않는다."""
        target = self._finder.prepare(context)
        if target is None:
            return ()
        try:
            requests = self._plan(context, question, target, cancel_check)
        except (StudioError, ValueError, KeyError, TypeError):
            return ()
        return tuple(run_planned(self._finder, target, requests, default_requests(target, question), limit=limit)) if requests else ()

    def extend_if_requested(self, context: StudioContext, question: str, pack: ContextPack, *, limit: int = EXTERNAL_LIMIT, first_number: int = 1,
                            cancel_check: Callable[[], None] | None = None) -> tuple[ContextPack, tuple[Passage, ...]]:
        return self._merge(pack, self.find_requested(context, question, limit=limit, cancel_check=cancel_check), first_number)

    def extend(self, ctx: GenerationContext, question: str, pack: ContextPack, *, limit: int = EXTERNAL_LIMIT) -> tuple[ContextPack, tuple[Passage, ...]]:
        """(새 구간까지 합친 묶음, 이번 질문에 맞는 구간). 같은 근거는 라벨 하나를 계속 쓴다."""
        try:
            target = self._finder.prepare(ctx.context)
            if target is None:
                return pack, ()
            found = run_planned(self._finder, target, self._requests(ctx, question, target), default_requests(target, question), limit=limit)
        except ExternalEvidenceError as error:
            raise StudioError("PROVIDER_UNAVAILABLE", 503) from error
        return self._merge(pack, found)

    @staticmethod
    def _merge(pack: ContextPack, found: Sequence[ExternalEvidence], first_number: int = 1) -> tuple[ContextPack, tuple[Passage, ...]]:
        known = {_key(p.external_ref): p for p in pack.passages if p.external_ref}
        number = max(_next_number(pack), first_number)
        matched: list[Passage] = []
        added: list[Passage] = []
        for item in found:
            key = (item.connector_id, item.document_version_id, item.block_id)
            passage = known.get(key)
            if passage is None:
                passage = known[key] = _passage(item, f"S{number}")
                number += 1
                added.append(passage)
            matched.append(passage)
        return ContextPack((*pack.passages, *added), pack.truncated, pack.total_sections), tuple(matched)

    def _requests(self, ctx: GenerationContext, question: str, target: Any) -> tuple[tuple[str, ...], ...]:
        fallback = default_requests(target, question)
        try:
            requests = self._plan(ctx.context, question, target, ctx.cancel_check)
        except (StudioError, ValueError, KeyError, TypeError):
            return fallback
        return requests or fallback  # 문서를 만들려면 자료가 필요하므로 빈 계획이어도 찾아 본다

    def _plan(self, context: StudioContext, question: str, target: Any, cancel_check: Callable[[], None] | None) -> tuple[tuple[str, ...], ...]:
        prompt = StudioPrompt(system=UNIT_PLAN_SYSTEM, user=build_plan_prompt(question, (), target), json_schema=UNIT_PLAN_SCHEMA, max_output_tokens=400,
                              prompt_version="studio-knowledge-plan-v1", schema_name="authoring_unit_plan")
        data = self._llm.generate(context, prompt, cancel_check=cancel_check).data
        return parse_plan(json.dumps(data, ensure_ascii=False), target)
