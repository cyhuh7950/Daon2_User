"""Studio v2 산출물 유형 레지스트리. 기존 OUTPUT_TYPES와 독립이다(WO-F1 D10)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

_LANGUAGE = {"type": "string", "enum": ["ko", "en"], "default": "ko"}
_FOCUS = {"type": "string", "maxLength": 500}
_CONFIRM_OUTLINE = {"type": "string", "enum": ["no", "yes"]}
# 슬라이드·동영상 확정 목록(WO-N1 NB3-F1)은 JSON 문자열이다. 장 30개·장면 20개를 담을 수 있게 보고서보다 길게 둔다.
_CONFIRMED_LIST = {"type": "string", "maxLength": 40000, "hidden": True}
# 심층 조사(WO-N1 NB4-F2): 보고서 설정에 둘이 함께 있으면 조사 생성기(studio_research.py)가 처리한다. 화면 설정 창에는 보이지 않는다.
RESEARCH_SCOPES = ("knowledge", "documents")
_RESEARCH_QUERY = {"type": "string", "maxLength": 500, "hidden": True}
_RESEARCH_SCOPES = {"type": "array", "items": {"type": "string", "enum": list(RESEARCH_SCOPES)}, "minItems": 1,
                    "maxItems": len(RESEARCH_SCOPES), "uniqueItems": True, "hidden": True}


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
           default_format="summary", schema={"custom_instruction": {"type": "string", "maxLength": 1000}, "confirm_outline": _CONFIRM_OUTLINE,
                   "confirmed_outline": {"type": "string", "maxLength": 4000, "hidden": True},
                   "research_query": _RESEARCH_QUERY, "research_scopes": _RESEARCH_SCOPES}),
        _t("data_table", ("xlsx", "csv", "pdf")),
        _t("mind_map", ("svg", "png", "json")),
        _t("flashcards", ("csv", "json", "pdf"),
           schema={"count": {"type": "integer", "minimum": 5, "maximum": 40},
                   "difficulty": {"type": "string", "enum": ["easy", "normal", "hard"]}}),
        _t("quiz", ("csv", "json", "pdf"),
           schema={"count": {"type": "integer", "minimum": 5, "maximum": 30},
                   "difficulty": {"type": "string", "enum": ["easy", "normal", "hard"]}}),
        _t("slides", ("pptx", "pdf"), schema={"length": {"type": "string", "enum": ["short", "normal", "long"]},
                                              "confirm_outline": _CONFIRM_OUTLINE, "confirmed_outline": _CONFIRMED_LIST}),
        _t("infographic", ("png", "svg", "pdf"), phase="2"),
        _t("audio_overview", ("mp3",), phase="3",
           schema={"engine": {"type": "string", "maxLength": 32}, "voice_a": {"type": "string", "maxLength": 40},
                   "voice_b": {"type": "string", "maxLength": 40},
                   "length": {"type": "string", "enum": ["short", "normal", "long"]}}),
        _t("video_overview", ("mp4", "vtt"), phase="4",
           schema={"engine": {"type": "string", "maxLength": 32}, "voice_a": {"type": "string", "maxLength": 40},
                   "length": {"type": "string", "enum": ["short", "normal", "long"]},
                   "confirm_outline": _CONFIRM_OUTLINE, "confirmed_outline": _CONFIRMED_LIST}),
        _t("memo", ("md", "txt"), requires_llm=False),
        _t("authored_document", ("docx", "pptx", "pdf"), phase="A1",
           schema={"template_id": {"type": "string", "maxLength": 64}}),
        _t("web_page", ("html",), schema={"page_request": {"type": "string", "maxLength": 2000}}),
        _t("data_aggregation", ("xlsx", "csv"),
           schema={"aggregation_request": {"type": "string", "maxLength": 2000},
                   "table_source_version_id": {"type": "string", "maxLength": 120},
                   "sheet": {"type": "string", "maxLength": 120},
                   "header_row": {"type": "integer", "minimum": 1, "maximum": 50}}),
    )
}

# 현재 제공 단계. 이후 단계는 reason과 함께 비활성으로 노출한다.
_AVAILABLE_PHASES = {"1", "2"}
_TILE_TYPES = ("audio_overview", "slides", "video_overview", "mind_map", "report", "flashcards", "quiz",
               "infographic", "data_table", "web_page", "data_aggregation")


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
    """`/studio/types` 응답. 타일 10종 + 메모(+작성)."""
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


# ------------------------------------------------------------------ 생성 전 구성 확인(WO-N1 NB3-F1)
_REF_LABEL = re.compile(r"\s*[\[(（]\s*S\d+(?:\s*[,，]\s*S\d+)*\s*[\])）]")


def strip_ref_labels(text: str) -> str:
    """구성 목록 글에 모델이 붙인 근거 표시("[S1]", "[S1, S2]", "(S3)")를 지운다(후속 A-3). 다른 괄호 글은 그대로 둔다."""
    return re.sub(r"[ \t]{2,}", " ", _REF_LABEL.sub("", text)).strip()


OUTLINE_LIMITS: Mapping[str, int] = {"slides": 30, "video_overview": 20}
_OUTLINE_KEY = {"slides": "slides", "video_overview": "scenes"}
_TITLE_MAX = 100
_POINTS_MAX, _POINT_MAX = 5, 120
_NARRATION_MAX = 600
_BULLETS_MAX = 5


class OutlineInvalid(ValueError):
    """확정 목록이 비었거나 상한을 넘거나 제목이 비었다. 응답은 422 OUTLINE_INVALID."""

    def __init__(self) -> None:
        super().__init__("OUTLINE_INVALID")


def _text(value: object, limit: int, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise OutlineInvalid()
    text = " ".join(value.split())
    if len(text) > limit or (required and not text):
        raise OutlineInvalid()
    return text


def _texts(value: object, count: int, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > count:
        raise OutlineInvalid()
    return [text for text in (_text(item, limit, required=False) for item in value) if text]


def parse_confirmed_outline(type_id: str, raw: object) -> dict[str, Any]:
    """슬라이드 {slides:[{title, points}]}·동영상 {scenes:[{title, narration_summary, bullets?}]} 확정 목록을 검증·정규화한다.

    빈 목록, 상한(슬라이드 30장·장면 20개) 초과, 빈 제목, 형식 오류는 OutlineInvalid.
    """
    key = _OUTLINE_KEY[type_id]
    if not isinstance(raw, str) or len(raw) > int(_CONFIRMED_LIST["maxLength"]):
        raise OutlineInvalid()
    try:
        data = json.loads(raw)
    except ValueError:
        raise OutlineInvalid() from None
    if not isinstance(data, Mapping) or set(data) - {"title", key}:
        raise OutlineInvalid()
    items = data.get(key)
    if not isinstance(items, list) or not 1 <= len(items) <= OUTLINE_LIMITS[type_id]:
        raise OutlineInvalid()
    allowed = {"title", "points"} if type_id == "slides" else {"title", "narration_summary", "bullets"}
    clean: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, Mapping) or set(item) - allowed:
            raise OutlineInvalid()
        title = _text(item.get("title"), _TITLE_MAX, required=True)
        if type_id == "slides":
            clean.append({"title": title, "points": _texts(item.get("points"), _POINTS_MAX, _POINT_MAX)})
        else:
            scene: dict[str, object] = {"title": title, "narration_summary": _text(item.get("narration_summary"), _NARRATION_MAX)}
            bullets = _texts(item.get("bullets"), _BULLETS_MAX, _POINT_MAX)
            if bullets:
                scene["bullets"] = bullets
            clean.append(scene)
    return {"title": _text(data.get("title"), 160), key: clean}


def checked_settings(type_id: str, format_id: str | None, settings: Mapping[str, object]) -> tuple[str | None, dict[str, object]]:
    """validate_settings + 서비스 오류 변환. 확정 목록 오류는 422 OUTLINE_INVALID, 그 밖은 400 STUDIO_INPUT_INVALID."""
    from .studio_workspace import StudioError
    try:
        return validate_settings(type_id, format_id, settings)
    except OutlineInvalid:
        raise StudioError("OUTLINE_INVALID", 422) from None
    except ValueError:
        raise StudioError("STUDIO_INPUT_INVALID", 400) from None


def validate_settings(type_id: str, format_id: str | None, settings: Mapping[str, object]) -> tuple[str | None, dict[str, object]]:
    """유형별 선택 설정을 검증한다. 오류는 ValueError('STUDIO_INPUT_INVALID'), 확정 목록 오류는 OutlineInvalid."""
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
        if key == "confirmed_outline" and type_id in OUTLINE_LIMITS:
            if isinstance(value, str) and value.strip() == "":
                continue  # 빈 값은 확정 목록을 지운다(보고서와 같다)
            clean[key] = json.dumps(parse_confirmed_outline(type_id, value), ensure_ascii=False)
            continue
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
        elif kind == "array":
            allowed = rule["items"]["enum"]  # type: ignore[index]
            if (not isinstance(value, list) or not int(rule["minItems"]) <= len(value) <= int(rule["maxItems"])  # type: ignore[arg-type]
                    or len(set(map(str, value))) != len(value) or any(not isinstance(item, str) or item not in allowed for item in value)):
                raise ValueError("STUDIO_INPUT_INVALID")
            value = list(value)
        clean[key] = value
    if format_id == "custom" and not str(clean.get("custom_instruction", "")).strip():
        raise ValueError("STUDIO_INPUT_INVALID")
    if type_id == "web_page" and not str(clean.get("page_request", "")).strip():
        raise ValueError("STUDIO_INPUT_INVALID")  # 요청 글 없이 만들면 접수 단계에서 거부한다(실패 카드가 생기지 않게)
    if type_id == "data_aggregation" and (not str(clean.get("aggregation_request", "")).strip()
                                          or not str(clean.get("table_source_version_id", "")).strip()):
        raise ValueError("STUDIO_INPUT_INVALID")  # 집계 요청과 표 자료가 모두 있어야 접수한다
    if ("research_query" in clean) != ("research_scopes" in clean):
        raise ValueError("STUDIO_INPUT_INVALID")  # 심층 조사는 질문과 범위를 함께 보낸다
    if "research_query" in clean and (clean.get("confirm_outline") == "yes" or clean.get("confirmed_outline")):
        raise ValueError("STUDIO_INPUT_INVALID")  # 심층 조사에서는 구성 확인을 쓰지 않는다(NB4-F2 Ruling)
    return format_id, clean
