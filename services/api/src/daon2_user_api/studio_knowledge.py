"""스튜디오가 선택한 승인 지식을 근거 구간으로 가져온다(WO-K4 4단계). 무엇을 찾을지는 LLM에 묻는다."""

from __future__ import annotations

import json
from typing import Any

from .authoring.agent import UNIT_PLAN_SCHEMA, UNIT_PLAN_SYSTEM
from .question_external_evidence import ExternalEvidence, ExternalEvidenceError, build_plan_prompt, default_requests, parse_plan, run_planned
from .studio_context_builder import ContextPack, Passage
from .studio_text_generation import StudioPrompt, StudioTextGenerator
from .studio_v2_generation import GenerationContext
from .studio_workspace import StudioError


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

    def extend(self, ctx: GenerationContext, question: str, pack: ContextPack) -> tuple[ContextPack, tuple[Passage, ...]]:
        """(새 구간까지 합친 묶음, 이번 질문에 맞는 구간). 같은 근거는 라벨 하나를 계속 쓴다."""
        try:
            target = self._finder.prepare(ctx.context)
            if target is None:
                return pack, ()
            found = run_planned(self._finder, target, self._requests(ctx, question, target), default_requests(target, question))
        except ExternalEvidenceError as error:
            raise StudioError("PROVIDER_UNAVAILABLE", 503) from error
        known = {_key(p.external_ref): p for p in pack.passages if p.external_ref}
        number = _next_number(pack)
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
        prompt = StudioPrompt(system=UNIT_PLAN_SYSTEM, user=build_plan_prompt(question, (), target), json_schema=UNIT_PLAN_SCHEMA, max_output_tokens=400,
                              prompt_version="studio-knowledge-plan-v1", schema_name="authoring_unit_plan")
        try:
            data = self._llm.generate(ctx.context, prompt, cancel_check=ctx.cancel_check).data
        except (StudioError, ValueError, KeyError, TypeError):
            return fallback
        requests = parse_plan(json.dumps(data, ensure_ascii=False), target)
        return requests or fallback  # 문서를 만들려면 자료가 필요하므로 빈 계획이어도 찾아 본다
