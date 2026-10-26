"""Studio v2 산출물 유형 레지스트리. 기존 OUTPUT_TYPES와 독립이다(WO-F1 D10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

_LANGUAGE = {"type": "string", "enum": ["ko", "en"], "default": "ko"}
_FOCUS = {"type": "string", "maxLength": 500}


@dataclass(frozen=True, slots=True)
class StudioV2Type:
    type_id: str
    formats: tuple[str, ...]
    default_format: str | None
    presets: tuple[str, ...]
    settings_schema: Mapping[str, object]
    requires_llm: bool
    phase: str
    export_formats: tuple[str, ...]


def _t(type_id, export_formats, *, presets=(), default_format=None, schema=None, requires_llm=True, phase="1"):
    properties = {"language": _LANGUAGE, "focus": _FOCUS}
    properties.update(schema or {})
    return StudioV2Type(
        type_id=type_id, formats=tuple(presets), default_format=default_format, presets=tuple(presets),
        settings_schema={"type": "object", "additionalProperties": False, "properties": properties},
        requires_llm=requires_llm, phase=phase, export_formats=tuple(export_formats),
    )


STUDIO_V2_TYPES: Mapping[str, StudioV2Type] = {
    t.type_id: t for t in (
        _t("report", ("docx", "pdf", "md"), presets=("summary", "briefing", "blog", "study_guide", "custom"),
           default_format="summary", schema={"custom_instruction": {"type": "string", "maxLength": 1000}}),
        _t("data_table", ("xlsx", "csv", "pdf")),
        _t("mind_map", ("svg", "png", "json")),
        _t("flashcards", ("csv", "json", "pdf"),
           schema={"count": {"type": "integer", "minimum": 5, "maximum": 40},
                   "difficulty": {"type": "string", "enum": ["easy", "normal", "hard"]}}),
        _t("quiz", ("csv", "json", "pdf"),
           schema={"count": {"type": "integer", "minimum": 5, "maximum": 30},
                   "difficulty": {"type": "string", "enum": ["easy", "normal", "hard"]}}),
        _t("slides", ("pptx", "pdf"), schema={"length": {"type": "string", "enum": ["short", "normal", "long"]}}),
        _t("infographic", ("png", "svg", "pdf"), phase="2"),
        _t("audio_overview", ("mp3",), phase="3",
           schema={"engine": {"type": "string", "maxLength": 32}, "voice_a": {"type": "string", "maxLength": 40},
                   "voice_b": {"type": "string", "maxLength": 40},
                   "length": {"type": "string", "enum": ["short", "normal", "long"]}}),
        _t("video_overview", ("mp4", "vtt"), phase="4",
           schema={"engine": {"type": "string", "maxLength": 32}, "voice_a": {"type": "string", "maxLength": 40},
                   "length": {"type": "string", "enum": ["short", "normal", "long"]}}),
        _t("memo", ("md", "txt"), requires_llm=False),
        _t("authored_document", ("docx", "pptx", "pdf"), phase="A1",
           schema={"template_id": {"type": "string", "maxLength": 64}}),
    )
}

# 현재 제공 단계. 이후 단계는 reason과 함께 비활성으로 노출한다.
_AVAILABLE_PHASES = {"1", "2"}
_TILE_TYPES = ("audio_overview", "slides", "video_overview", "mind_map", "report", "flashcards", "quiz",
               "infographic", "data_table")


def is_available(type_id: str, *, tts_enabled: bool = False, authoring_enabled: bool = False) -> bool:
    spec = STUDIO_V2_TYPES.get(type_id)
    if spec is None:
        return False
    if spec.phase in _AVAILABLE_PHASES:
        return True
    if spec.type_id == "audio_overview":
        return tts_enabled
    if spec.type_id == "video_overview":
        from .studio_video import ffmpeg_path
        return tts_enabled and ffmpeg_path() is not None
    if spec.type_id == "authored_document":
        return authoring_enabled
    return False


def available_types(*, tts_enabled: bool = False, authoring_enabled: bool = False,
                    tts_settings: Mapping[str, object] | None = None) -> list[dict[str, object]]:
    """`/studio/types` 응답. 타일 9종 + 메모(+작성)."""
    order = (*_TILE_TYPES, "memo", "authored_document")
    result: list[dict[str, object]] = []
    for type_id in order:
        spec = STUDIO_V2_TYPES[type_id]
        ok = is_available(type_id, tts_enabled=tts_enabled, authoring_enabled=authoring_enabled)
        item: dict[str, object] = {
            "type_id": type_id, "formats": list(spec.formats), "presets": list(spec.presets),
            "export_formats": list(spec.export_formats), "default_format": spec.default_format,
            "available": ok, "settings_schema": spec.settings_schema,
        }
        if type_id in ("audio_overview", "video_overview") and tts_settings:
            overlay = {k: v for k, v in tts_settings.items() if k in spec.settings_schema["properties"] or type_id == "audio_overview"}  # type: ignore[operator]
            schema = {**spec.settings_schema, "properties": {**spec.settings_schema["properties"], **overlay}}  # type: ignore[dict-item]
            item["settings_schema"] = schema
        if not ok:
            item["reason"] = "STUDIO_TYPE_UNAVAILABLE"
        result.append(item)
    return result


def validate_settings(type_id: str, format_id: str | None, settings: Mapping[str, object]) -> tuple[str | None, dict[str, object]]:
    """유형별 선택 설정을 검증한다. 오류는 ValueError('STUDIO_INPUT_INVALID')."""
    spec = STUDIO_V2_TYPES.get(type_id)
    if spec is None or not isinstance(settings, Mapping):
        raise ValueError("STUDIO_INPUT_INVALID")
    if spec.presets:
        format_id = format_id or spec.default_format
        if format_id not in spec.presets:
            raise ValueError("STUDIO_INPUT_INVALID")
    elif format_id is not None:
        raise ValueError("STUDIO_INPUT_INVALID")
    properties: Mapping[str, Mapping[str, object]] = spec.settings_schema["properties"]  # type: ignore[assignment]
    clean: dict[str, object] = {}
    for key, value in settings.items():
        rule = properties.get(key)
        if rule is None:
            raise ValueError("STUDIO_INPUT_INVALID")
        kind = rule["type"]
        if kind == "string":
            if not isinstance(value, str) or len(value) > int(rule.get("maxLength", 500)):
                raise ValueError("STUDIO_INPUT_INVALID")
            if "enum" in rule and value not in rule["enum"]:
                raise ValueError("STUDIO_INPUT_INVALID")
            if value.strip() == "" and "enum" not in rule:
                continue
        elif kind == "integer":
            if type(value) is not int or not int(rule["minimum"]) <= value <= int(rule["maximum"]):  # type: ignore[arg-type]
                raise ValueError("STUDIO_INPUT_INVALID")
        clean[key] = value
    if format_id == "custom" and not str(clean.get("custom_instruction", "")).strip():
        raise ValueError("STUDIO_INPUT_INVALID")
    return format_id, clean
