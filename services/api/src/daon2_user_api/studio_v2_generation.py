"""Studio v2 생성기 계약과 레지스트리. 실제 생성기는 WO-F2에서 이 레지스트리에 등록한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol, Sequence

from .studio_workspace import StudioContext, StudioError


class StudioCancelled(RuntimeError):
    """사용자 취소 요청을 단계 경계에서 감지했다."""


@dataclass(frozen=True, slots=True)
class GenerationContext:
    context: StudioContext
    output_id: str
    type_id: str
    format_id: str | None
    settings: Mapping[str, object]
    source_version_ids: tuple[str, ...]
    customization: str
    language: str
    mode: str
    progress: Callable[[int, str], None]   # 단계마다 호출: lease 연장 + 취소 확인(취소면 StudioCancelled)
    cancel_check: Callable[[], None]


@dataclass(frozen=True, slots=True)
class GenerationResult:
    content: Mapping[str, object]
    warnings: Sequence[Mapping[str, object]] = ()
    generated_with: Mapping[str, object] = field(default_factory=dict)
    sources: Sequence[Mapping[str, object]] = ()
    evidence: Sequence[Mapping[str, object]] = ()
    assets: Sequence[Mapping[str, object]] = ()   # [{kind, content_type, content(bytes), duration_ms}] — 리비전과 함께 저장


class StudioGenerator(Protocol):
    type_id: str

    def generate(self, ctx: GenerationContext) -> GenerationResult: ...


class StubGenerator:
    """WO-F1 종료 기준용 스텁. 본문 없이 구조만 만든다(WO-F2에서 실제 생성기로 교체)."""

    def __init__(self, type_id: str) -> None:
        self.type_id = type_id

    def generate(self, ctx: GenerationContext) -> GenerationResult:
        ctx.progress(50, "스텁 생성")
        return GenerationResult(
            content={"schema": f"studio.{ctx.type_id}.v1", "language": ctx.language,
                     "body": {"stub": True, "source_count": len(ctx.source_version_ids)}},
            warnings=({"code": "GENERATOR_STUB"},),
            generated_with={"provider": "stub", "model": "stub", "prompt_version": "stub-v0"},
            sources=tuple({"source_version_id": v} for v in ctx.source_version_ids),
        )


class GeneratorRegistry:
    def __init__(self) -> None:
        self._generators: dict[str, StudioGenerator] = {}

    def register(self, generator: StudioGenerator) -> None:
        self._generators[generator.type_id] = generator

    def get(self, type_id: str) -> StudioGenerator:
        generator = self._generators.get(type_id)
        if generator is None:
            raise StudioError("STUDIO_TYPE_UNAVAILABLE", 409)
        return generator

    @classmethod
    def with_stubs(cls) -> "GeneratorRegistry":
        registry = cls()
        for type_id in ("report", "data_table", "mind_map", "flashcards", "quiz", "slides"):
            registry.register(StubGenerator(type_id))
        return registry
