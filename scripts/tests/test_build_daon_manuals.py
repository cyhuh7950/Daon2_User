"""build-daon-manuals.py 시험. 실행: uv run --no-project --with python-docx --with pillow==12.3.0 --with pytest==9.0.3 python -m pytest scripts/tests/test_build_daon_manuals.py"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from docx import Document
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "build-daon-manuals.py"


def load(root: Path):
    spec = importlib.util.spec_from_file_location("build_daon_manuals", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    module.DIST = root / "docs" / "manual" / "dist"
    module.PUBLIC = root / "apps" / "web" / "public" / "manual"
    return module


def write_manual(root: Path, body: str) -> Path:
    folder = root / "docs" / "manual" / "daon-user-manual"
    (folder / "images").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), "white").save(folder / "images" / "studio-panel.png")
    source = folder / "index.md"
    source.write_text("# Daon 사용자 설명서\n\n" + body, encoding="utf-8")
    return source


TABLE = "| 번호 | 항목 |\n| --- | --- |\n| ① | `x\\|y` **굵게** |\n"


def test_table_rows_are_split_on_unescaped_pipes(tmp_path):
    module = load(tmp_path)
    rows, after = module.parse_table(["| a | b |", "| --- | --- |", "| `x\\|y` | **굵게** |", "다음 문단"], 0)
    assert rows == [["a", "b"], ["x|y", "굵게"]]
    assert after == 3


def test_docx_renders_markdown_tables_as_word_tables(tmp_path):
    module = load(tmp_path)
    write_manual(tmp_path, "## 2부 화면별 설명\n\n" + TABLE)
    module.build_docx()
    document = Document(str(module.DIST / "daon-user-manual.docx"))
    body = [table for table in document.tables if table.rows[0].cells[0].text == "번호"]
    assert len(body) == 1
    assert [cell.text for cell in body[0].rows[1].cells] == ["①", "x|y 굵게"]
    assert not any(paragraph.text.startswith("|") for paragraph in document.paragraphs)


def test_docx_embeds_images_with_alt_caption(tmp_path):
    module = load(tmp_path)
    write_manual(tmp_path, "## 2부\n\n![① 스튜디오 패널](images/studio-panel.png)\n")
    module.build_docx()
    document = Document(str(module.DIST / "daon-user-manual.docx"))
    assert len(document.inline_shapes) == 1
    assert any(paragraph.text == "① 스튜디오 패널" for paragraph in document.paragraphs)


def test_level_four_headings_become_word_heading_3(tmp_path):
    module = load(tmp_path)
    write_manual(tmp_path, "## 2부\n\n### 2-6 스튜디오\n\n#### 기능·목적\n\n설명\n")
    module.build_docx()
    document = Document(str(module.DIST / "daon-user-manual.docx"))
    styles = {paragraph.text: paragraph.style.name for paragraph in document.paragraphs}
    assert styles["기능·목적"] == "Heading 3"
    assert styles["2-6 스튜디오"] == "Heading 2"
    assert not any("####" in paragraph.text for paragraph in document.paragraphs)


def test_pdf_failure_keeps_previous_pdf_and_skips_manifest(tmp_path, monkeypatch):
    module = load(tmp_path)
    write_manual(tmp_path, "## 1부\n\n본문\n")
    module.DIST.mkdir(parents=True)
    (module.DIST / "daon-user-manual.pdf").write_bytes(b"%PDF-old")
    manifest = tmp_path / "docs" / "manual" / "release-manifest.json"
    manifest.write_text("old", encoding="utf-8")
    monkeypatch.setattr(module, "find_soffice", lambda: None)
    with pytest.raises(SystemExit):
        module.main(["all"])
    assert (module.DIST / "daon-user-manual.pdf").read_bytes() == b"%PDF-old"
    assert manifest.read_text(encoding="utf-8") == "old"
    assert not module.PUBLIC.exists()


def test_manifest_lists_one_document_version_2_and_copies_images(tmp_path):
    module = load(tmp_path)
    write_manual(tmp_path, "## 1부\n")
    folder = tmp_path / "docs" / "manual" / "daon-user-manual" / "images"
    (folder / "raw").mkdir()
    (folder / "raw" / "studio-panel.png").write_bytes(b"raw")
    (folder / "annotations.json").write_text("{}", encoding="utf-8")
    module.DIST.mkdir(parents=True)
    for extension in ("docx", "pdf"):
        (module.DIST / f"daon-user-manual.{extension}").write_bytes(extension.encode())
    module.PUBLIC.mkdir(parents=True)
    (module.PUBLIC / "daon-getting-started.md").write_text("retired", encoding="utf-8")
    (module.PUBLIC / "images").mkdir()
    (module.PUBLIC / "images" / "stale.png").write_bytes(b"stale")
    module.build_manifest()
    manifest = json.loads((module.PUBLIC / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["release_version"] == "2.0.0"
    assert [document["document_id"] for document in manifest["documents"]] == ["daon-user-manual"]
    assert sorted(path.name for path in (module.PUBLIC / "images").iterdir()) == ["studio-panel.png"]
    assert not (module.PUBLIC / "daon-getting-started.md").exists()
    assert (tmp_path / "docs" / "manual" / "release-manifest.json").read_text(encoding="utf-8") == (module.PUBLIC / "manifest.json").read_text(encoding="utf-8")
