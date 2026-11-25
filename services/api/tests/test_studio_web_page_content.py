"""WO-N8 웹 페이지 1단계(내용 JSON) 검사."""

from __future__ import annotations

import pytest

from daon2_user_api.studio_context_builder import ContextPack, Passage
from daon2_user_api.studio_web_page import validate_web_page, verified_body, verified_text
from daon2_user_api.studio_workspace import StudioError


def _pack(*texts: str) -> ContextPack:
    passages = tuple(
        Passage(f"S{i + 1}", "v", "s", "문서.pdf", None, "page", str(i + 1), None, text)
        for i, text in enumerate(texts)
    )
    return ContextPack(passages, False, len(passages))


def _data(blocks: list[dict], heading: str = "개요") -> dict:
    return {"title": "안내", "sections": [{"heading": heading, "blocks": blocks}]}


def test_block_without_valid_refs_is_insufficient() -> None:
    pack = _pack("보상 한도는 100만 원이다.")
    data = _data([
        {"type": "paragraph", "text": "보상 한도는 100만 원이다.", "refs": ["S1"]},
        {"type": "paragraph", "text": "근거 없는 문장", "refs": ["S99"]},
    ])
    body, _, used = validate_web_page(data, pack, "요청")
    blocks = body["sections"][0]["blocks"]
    assert len(blocks) == 2
    assert blocks[0]["insufficient"] is False
    assert blocks[1]["insufficient"] is True
    assert blocks[1]["refs"] == []
    assert used == ["S1"]


def test_number_not_in_cited_passage_is_insufficient() -> None:
    pack = _pack("보상 한도는 100만 원이다.", "지급 기한은 30일이다.")
    data = _data([
        {"type": "paragraph", "text": "지급 기한은 30일이다.", "refs": ["S2"]},
        {"type": "paragraph", "text": "보상 한도는 300만 원", "refs": ["S1"]},
    ])
    body, warnings, _ = validate_web_page(data, pack, "요청")
    blocks = body["sections"][0]["blocks"]
    assert blocks[1]["insufficient"] is True
    assert any(w["code"] == "ANCHOR_MISMATCH" for w in warnings)


def test_supported_block_is_kept_verified() -> None:
    pack = _pack("보상 한도는 100만 원이다.")
    data = _data([
        {"type": "paragraph", "text": "보상 한도는 100만 원", "refs": ["S1"]},
        {"type": "bullets", "items": ["한도 100만 원"], "refs": ["S1"]},
        {"type": "table", "rows": [["항목", "금액"], ["한도", "100만 원"]], "refs": ["S1"]},
        {"type": "metric", "label": "보상 한도", "value": "100만 원", "refs": ["S1"]},
    ])
    body, warnings, _ = validate_web_page(data, pack, "요청")
    blocks = body["sections"][0]["blocks"]
    assert [b["type"] for b in blocks] == ["paragraph", "bullets", "table", "metric"]
    assert all(b["insufficient"] is False for b in blocks)
    assert not warnings
    assert body["html"] == ""


def test_all_insufficient_raises_validation_failed() -> None:
    pack = _pack("보상 한도는 100만 원이다.")
    data = _data([
        {"type": "paragraph", "text": "보상 한도는 300만 원", "refs": ["S1"]},
        {"type": "metric", "label": "한도", "value": "5억", "refs": []},
    ])
    with pytest.raises(StudioError) as excinfo:
        validate_web_page(data, pack, "요청")
    assert excinfo.value.code == "STUDIO_VALIDATION_FAILED"


def test_verified_body_drops_insufficient_and_empty_sections() -> None:
    pack = _pack("보상 한도는 100만 원이다.")
    data = {"title": "안내", "sections": [
        {"heading": "근거 있음", "blocks": [
            {"type": "paragraph", "text": "보상 한도는 100만 원", "refs": ["S1"]},
            {"type": "paragraph", "text": "지어낸 문장", "refs": []},
        ]},
        {"heading": "근거 없음", "blocks": [{"type": "paragraph", "text": "지어낸 문장 둘", "refs": []}]},
    ]}
    body, _, _ = validate_web_page(data, pack, "요청")
    assert len(body["sections"]) == 2
    clean = verified_body(body)
    assert [s["heading"] for s in clean["sections"]] == ["근거 있음"]
    assert len(clean["sections"][0]["blocks"]) == 1
    assert len(body["sections"][1]["blocks"]) == 1  # 원본은 그대로
    text = verified_text(body)
    assert "보상 한도는 100만 원" in text and "근거 있음" in text and "안내" in text
    assert "지어낸" not in text and "근거 없음" not in text


def test_request_stored_trimmed_to_2000() -> None:
    pack = _pack("보상 한도는 100만 원이다.")
    data = _data([{"type": "paragraph", "text": "보상 한도는 100만 원", "refs": ["S1"]}])
    body, _, _ = validate_web_page(data, pack, "  " + "가" * 2500 + "  ")
    assert body["request"] == "가" * 2000
