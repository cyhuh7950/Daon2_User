"""annotate-manual-images.py 시험. 실행: uv run --no-project --with pillow==12.3.0 --with pytest==9.0.3 python -m pytest scripts/tests/test_annotate_manual_images.py"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "annotate-manual-images.py"


def load():
    spec = importlib.util.spec_from_file_location("annotate_manual_images", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blank(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 120), (255, 255, 255)).save(path)
    return path


def test_number_marker_is_drawn_at_the_given_point(tmp_path):
    module = load()
    source, out = blank(tmp_path / "raw" / "a.png"), tmp_path / "a.png"
    module.annotate(source, [{"n": 1, "x": 50, "y": 40}], out)
    image = Image.open(out).convert("RGB")
    assert image.getpixel((50 - 10, 40)) == module.MARK_FILL
    assert image.getpixel((150, 100)) == (255, 255, 255)


def test_mask_area_is_covered_with_one_colour(tmp_path):
    module = load()
    source, out = blank(tmp_path / "raw" / "a.png"), tmp_path / "a.png"
    Image.new("RGB", (200, 120), (10, 200, 30)).save(source)
    module.annotate(source, [{"mask": [20, 20, 60, 30]}], out)
    image = Image.open(out).convert("RGB")
    assert {image.getpixel((x, y)) for x in range(20, 80) for y in range(20, 50)} == {module.MASK_FILL}
    assert image.getpixel((150, 100)) == (10, 200, 30)


def test_source_image_is_not_changed(tmp_path):
    module = load()
    source = blank(tmp_path / "raw" / "a.png")
    before = source.read_bytes()
    module.annotate(source, [{"n": 2, "x": 30, "y": 30}], tmp_path / "a.png")
    assert source.read_bytes() == before


def test_every_raw_image_needs_an_annotation_entry(tmp_path):
    module = load()
    images = tmp_path / "images"
    blank(images / "raw" / "a.png")
    blank(images / "raw" / "b.png")
    (images / "annotations.json").write_text(json.dumps({"a.png": [{"n": 1, "x": 10, "y": 10}]}), encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        module.annotate_all(images)
    assert "b.png" in str(caught.value)


def test_annotate_all_writes_numbered_images_next_to_raw(tmp_path):
    module = load()
    images = tmp_path / "images"
    blank(images / "raw" / "a.png")
    (images / "annotations.json").write_text(json.dumps({"a.png": [{"n": 1, "x": 10, "y": 10}]}), encoding="utf-8")
    module.annotate_all(images)
    assert (images / "a.png").is_file()


def test_unknown_mark_shape_is_rejected(tmp_path):
    module = load()
    source = blank(tmp_path / "raw" / "a.png")
    with pytest.raises(SystemExit):
        module.annotate(source, [{"n": 1}], tmp_path / "a.png")
