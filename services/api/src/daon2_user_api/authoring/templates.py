"""작성 템플릿 로더. JSON + 스키마 검증(서버 기동 시 잘못된 템플릿이면 오류). WO-A1 T-A1-01."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from ..knowledge_connector_service import KIND_TOOLS

INPUT_KINDS = frozenset({"text", "structured", "source_ref", "knowledge_ref", "choice"})
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ALL_TOOLS = frozenset().union(*KIND_TOOLS.values())


class AuthoringError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class AuthoringTemplate:
    template_id: str
    title: str
    version: int
    description: str
    keywords: tuple[str, ...]
    inputs: tuple[Mapping[str, Any], ...]
    knowledge: tuple[Mapping[str, Any], ...]
    sections: tuple[Mapping[str, Any], ...]
    checks: tuple[Mapping[str, Any], ...]
    output: Mapping[str, Any]
    # analysis: rfp_requirements(RFP 소스에서 요구사항 추출) | base_document(기준 문서 + 변경점, 요구사항 추출 없음)
    analysis: str = "rfp_requirements"
    style: str = "proposal"  # proposal | terms | contract — 프롬프트와 점검·표시 방식을 고른다
    source_input: str | None = "rfp_document"

    def input(self, key: str) -> Mapping[str, Any]:
        for item in self.inputs:
            if item["key"] == key:
                return item
        raise AuthoringError("AUTHORING_INPUT_INVALID", 422)

    def summary(self) -> dict[str, Any]:
        return {"template_id": self.template_id, "title": self.title, "description": self.description, "version": self.version,
                "inputs": [{"key": i["key"], "kind": i["kind"], "required": bool(i["required"])} for i in self.inputs],
                "output_formats": list(self.output["formats"]), "default_formats": list(self.output["default"])}


def _fail(reason: str) -> AuthoringError:
    return AuthoringError(f"AUTHORING_TEMPLATE_INVALID:{reason}", 500)


def parse_template(raw: Mapping[str, Any]) -> AuthoringTemplate:
    for key in ("template_id", "title", "version", "inputs", "knowledge", "sections", "checks", "output"):
        if key not in raw:
            raise _fail(f"missing {key}")
    if not isinstance(raw["template_id"], str) or not _KEY.fullmatch(raw["template_id"]):
        raise _fail("template_id")
    seen: set[str] = set()
    for item in raw["inputs"]:
        key = item.get("key")
        if not isinstance(key, str) or not _KEY.fullmatch(key) or key in seen or item.get("kind") not in INPUT_KINDS or not isinstance(item.get("question"), str):
            raise _fail(f"input {key}")
        if item["kind"] == "choice" and not item.get("choices"):
            raise _fail(f"choices {key}")
        seen.add(key)
    for step in raw["knowledge"]:
        if step.get("tool") not in _ALL_TOOLS or step.get("per") not in (None, *seen):
            raise _fail(f"knowledge {step.get('tool')}")
    section_keys: set[str] = set()
    for section in raw["sections"]:
        if not _KEY.fullmatch(str(section.get("key"))) or section["key"] in section_keys or not section.get("title"):
            raise _fail("section")
        section_keys.add(section["key"])
    if not section_keys:
        raise _fail("no sections")
    analysis = raw.get("analysis", "rfp_requirements")
    style = raw.get("style", "proposal")
    if analysis not in ("rfp_requirements", "base_document") or style not in ("proposal", "terms", "contract"):
        raise _fail("analysis/style")
    source_input = raw.get("source_input", "rfp_document" if analysis == "rfp_requirements" else None)
    if analysis == "rfp_requirements" and (source_input not in seen or next(i for i in raw["inputs"] if i["key"] == source_input)["kind"] != "source_ref"):
        raise _fail("source_input")
    if analysis == "base_document" and not any(i["kind"] == "knowledge_ref" and i["required"] for i in raw["inputs"]):
        raise _fail("base document input")
    formats = raw["output"].get("formats", [])
    if not formats or not set(formats) <= {"docx", "pptx"} or not set(raw["output"].get("default", [])) <= set(formats):
        raise _fail("output")
    return AuthoringTemplate(raw["template_id"], raw["title"], int(raw["version"]), str(raw.get("description", "")), tuple(raw.get("keywords", ())),
                             tuple(raw["inputs"]), tuple(raw["knowledge"]), tuple(raw["sections"]), tuple(raw["checks"]), raw["output"],
                             analysis, style, source_input)


class TemplateRegistry:
    """내장 템플릿 + (선택) 조직 템플릿. 조직 템플릿은 `org_provider`(active(tenant), get(tenant, id, version))가 있고 tenant_id를 알 때만 보인다."""

    def __init__(self, raw_templates=None, org_provider=None) -> None:  # type: ignore[no-untyped-def]
        from .template_data import BUILTIN_TEMPLATES
        self._templates: dict[str, AuthoringTemplate] = {}
        for raw in (BUILTIN_TEMPLATES if raw_templates is None else raw_templates):
            template = parse_template(raw)
            self._templates[template.template_id] = template
        self._org = org_provider

    def _org_templates(self, tenant_id: str | None) -> dict[str, AuthoringTemplate]:
        if self._org is None or not tenant_id:
            return {}
        found: dict[str, AuthoringTemplate] = {}
        for raw in self._org.active(tenant_id):
            try:
                template = parse_template(raw)
            except AuthoringError:
                continue  # 저장된 템플릿이 깨졌다면 목록에서만 빼고 나머지는 계속 쓴다
            if template.template_id not in self._templates:
                found[template.template_id] = template
        return found

    def get(self, template_id: str, tenant_id: str | None = None, version: int | None = None) -> AuthoringTemplate:
        template = self._templates.get(template_id)
        if template is not None:
            return template
        if self._org is not None and tenant_id and template_id.startswith("org_"):
            try:
                return parse_template(self._org.get(tenant_id, template_id, version))
            except AuthoringError as error:
                if error.code == "AUTHORING_TEMPLATE_UNKNOWN":
                    raise
                raise AuthoringError("AUTHORING_TEMPLATE_UNKNOWN", 404) from None
        raise AuthoringError("AUTHORING_TEMPLATE_UNKNOWN", 404)

    def list(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return [t.summary() for t in (*self._templates.values(), *self._org_templates(tenant_id).values())]

    def classify(self, request_text: str, tenant_id: str | None = None) -> list[str]:
        """요청 문장에서 템플릿 후보를 키워드로 찾는다(모호하면 둘 이상 반환)."""
        pool = (*self._templates.values(), *self._org_templates(tenant_id).values())
        scored = [(sum(1 for k in t.keywords if k.lower() in request_text.lower()), t.template_id) for t in pool]
        hits = sorted([s for s in scored if s[0] > 0], key=lambda x: (-x[0], x[1]))
        return [tid for _, tid in hits]
