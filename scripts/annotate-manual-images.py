"""매뉴얼 화면 그림에 ①②③ 번호와 가리기를 그린다.

images/raw/<이름>.png(촬영 원본) + images/annotations.json(번호 좌표) → images/<이름>.png(매뉴얼에 넣는 그림).
번호: {"n": 1, "x": 120, "y": 64}  가리기(키·개인정보): {"mask": [x, y, 너비, 높이]}
실행: uv run --no-project --with pillow==12.3.0 python scripts/annotate-manual-images.py [images 폴더]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGES = ROOT / "docs" / "manual" / "daon-user-manual" / "images"
DIAMETER = 28
MARK_FILL = (31, 77, 160)
MARK_EDGE = (255, 255, 255)
MASK_FILL = (210, 214, 222)
FONT_CANDIDATES = (r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _font(size):
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def annotate(source: Path, marks: list[dict], out: Path) -> None:
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _font(16)
    radius = DIAMETER // 2
    for mark in marks:
        if set(mark) == {"mask"} and len(mark["mask"]) == 4:
            x, y, width, height = (int(value) for value in mark["mask"])
            draw.rectangle((x, y, x + width - 1, y + height - 1), fill=MASK_FILL)
        elif set(mark) == {"n", "x", "y"}:
            x, y, number = int(mark["x"]), int(mark["y"]), int(mark["n"])
            draw.ellipse((x - radius - 2, y - radius - 2, x + radius + 2, y + radius + 2), fill=MARK_EDGE)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=MARK_FILL)
            draw.text((x, y), str(number), fill=MARK_EDGE, font=font, anchor="mm")
        else:
            raise SystemExit(f"ANNOTATION_INVALID: {source.name} {mark}")
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, optimize=True)


def annotate_all(images: Path = DEFAULT_IMAGES) -> list[Path]:
    raw = sorted((images / "raw").glob("*.png"))
    entries = json.loads((images / "annotations.json").read_text(encoding="utf-8"))
    missing = [path.name for path in raw if path.name not in entries]
    if missing:
        raise SystemExit(f"ANNOTATION_MISSING: {', '.join(missing)}")
    written = []
    for path in raw:
        out = images / path.name
        annotate(path, entries[path.name], out)
        written.append(out)
    return written


if __name__ == "__main__":
    for written in annotate_all(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGES):
        print(written.name)
