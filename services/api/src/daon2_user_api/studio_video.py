"""동영상 개요(WO-F7V F7-05): 소스 → 장면(슬라이드+내레이션, LLM) → 내레이션 TTS → 슬라이드 PNG → ffmpeg로 mp4.

모든 장면은 1280x720 정지 화면이고 오디오는 내레이터 1명의 연결된 음성이다. 장면 하나가 챕터 하나이며
자막(WebVTT)은 문장 단위 시간으로 만든다. 본문 JSON에 장면별 시작·끝 시간과 자막 줄(cues)을 저장한다.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import studio_validation as V
from .studio_audio import _EgressModel
from .studio_egress import StudioEgressGate, mask_text
from .studio_generators import _REFS, _Base
from .studio_infographic import _font, _width, wrap
from .studio_v2_generation import GenerationContext, GenerationResult
from .studio_workspace import StudioError
from .tts_engines import AudioResult, Spoken, TtsClient, TtsConfig, TtsEngine, TtsError, synthesize_dialogue

WIDTH, HEIGHT, FPS = 1280, 720, 5
MARGIN = 80
GAP_SCENE_MS = 450
TAIL_MS = 600
SENTENCE_LIMIT = 200
LENGTHS = {"short": (3, 5, "약 2분"), "normal": (5, 9, "약 4분"), "long": (9, 14, "약 7분")}
FFMPEG_TIMEOUT = 300
_FFMPEG_CODES = {"VIDEO_ENCODER_UNAVAILABLE": 503, "VIDEO_ENCODE_FAILED": 502, "VIDEO_TIME_BUDGET_EXCEEDED": 502}
_SENTENCE_END = re.compile(r"(?<=[.!?。！？…])\s+")
_COLORS = {"bg": "#f6f7fb", "title": "#1b2230", "body": "#2a3347", "muted": "#5b6577", "accent": "#2f55d4", "card": "#ffffff", "line": "#d5dae5"}


def ffmpeg_path() -> str | None:
    """DAON_FFMPEG > imageio-ffmpeg 번들 > PATH 순으로 실행 파일을 찾는다. 없으면 None(동영상 비활성)."""
    explicit = os.environ.get("DAON_FFMPEG", "").strip()
    if explicit:
        return explicit if Path(explicit).is_file() else None
    try:
        import imageio_ffmpeg
        found = imageio_ffmpeg.get_ffmpeg_exe()
        if found and Path(found).is_file():
            return found
    except Exception:
        pass
    return shutil.which("ffmpeg")


def split_sentences(text: str, limit: int = SENTENCE_LIMIT) -> list[str]:
    """문장 부호 기준으로 나누고, 한 문장이 limit보다 길면 띄어쓰기에서 자른다."""
    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(" ".join(str(text).split())):
        sentence = sentence.strip()
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)
    return pieces


# ------------------------------------------------------------------ 슬라이드 그리기
def _draw_lines(draw: Any, x: float, y: float, lines: Sequence[str], size: int, fill: str, gap: float = 1.35) -> float:
    for line in lines:
        draw.text((x, y), line, font=_font(size), fill=fill, anchor="ls")
        y += round(size * gap)
    return y


def render_scene_png(scene: Mapping[str, Any], number: int, total: int) -> tuple[bytes, list[str]]:
    """장면 하나를 1280x720 PNG로 그린다. (PNG, 넘친 영역 경로 목록). 제목 44px·본문 28px 이상을 지킨다."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (WIDTH, HEIGHT), _COLORS["bg"])
    draw = ImageDraw.Draw(image)
    overflow: list[str] = []
    layout = str(scene.get("layout", "bullets"))
    title = str(scene.get("title", ""))
    bullets = [str(b) for b in scene.get("bullets", [])]
    draw.rectangle([0, 0, 14, HEIGHT], fill=_COLORS["accent"])
    if layout == "title":
        lines, over = wrap(title, 64, WIDTH - 2 * MARGIN - 40, 3)
        if over:
            overflow.append("title")
        top = HEIGHT / 2 - len(lines) * 44 - (20 if bullets else 0)
        _draw_lines(draw, MARGIN + 20, top + 64, lines, 64, _COLORS["title"], 1.25)
        if bullets:
            sub, over = wrap(" ".join(bullets), 32, WIDTH - 2 * MARGIN - 40, 3)
            if over:
                overflow.append("bullets")
            _draw_lines(draw, MARGIN + 20, HEIGHT / 2 + 70, sub, 32, _COLORS["muted"])
    else:
        lines, over = wrap(title, 48, WIDTH - 2 * MARGIN, 2)
        if over:
            overflow.append("title")
        y = _draw_lines(draw, MARGIN, 120, lines, 48, _COLORS["title"], 1.2)
        draw.rectangle([MARGIN, y - 20, MARGIN + 120, y - 14], fill=_COLORS["accent"])
        top = y + 30
        if layout == "table" and isinstance(scene.get("table"), Mapping):
            _draw_table(draw, scene["table"], top, overflow)  # type: ignore[arg-type]
        elif layout == "two_column" and len(bullets) >= 2:
            half = (len(bullets) + 1) // 2
            for column, items in enumerate((bullets[:half], bullets[half:])):
                x = MARGIN + column * ((WIDTH - 2 * MARGIN) // 2 + 10)
                _draw_bullets(draw, x, top, items, (WIDTH - 2 * MARGIN) // 2 - 30, overflow, f"bullets{column}")
        else:
            _draw_bullets(draw, MARGIN, top, bullets, WIDTH - 2 * MARGIN, overflow, "bullets")
    draw.text((WIDTH - MARGIN, HEIGHT - 36), f"{number} / {total}", font=_font(24), fill=_COLORS["muted"], anchor="rs")
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue(), overflow


def _draw_bullets(draw: Any, x: float, y: float, items: Sequence[str], width: float, overflow: list[str], path: str) -> None:
    room = HEIGHT - 90 - y
    size = 32
    for item in items:
        lines, over = wrap(item, size, width - 40, 3)
        height = len(lines) * round(size * 1.35) + 18
        if room < height:
            overflow.append(path)
            break
        draw.ellipse([x, y - 20, x + 12, y - 8], fill=_COLORS["accent"])
        y = _draw_lines(draw, x + 32, y, lines, size, _COLORS["body"])
        y += 18
        room = HEIGHT - 90 - y
        if over:
            overflow.append(path)


def _draw_table(draw: Any, table: Mapping[str, Any], top: float, overflow: list[str]) -> None:
    columns = [str(c) for c in table.get("columns", [])][:6]
    rows = [[str(c) for c in r] for r in table.get("rows", [])][:8]
    if not columns:
        return
    cell_w = (WIDTH - 2 * MARGIN) / len(columns)
    size = 28
    y = top
    for r, row in enumerate([columns, *rows]):
        draw.rectangle([MARGIN, y - 36, WIDTH - MARGIN, y + 14], fill=_COLORS["card"] if r else "#e6ebfa", outline=_COLORS["line"])
        for c, value in enumerate(row[: len(columns)]):
            lines, over = wrap(value, size, cell_w - 20, 1)
            if over:
                overflow.append(f"table[{r}][{c}]")
            draw.text((MARGIN + c * cell_w + 10, y), lines[0] if lines else "", font=_font(size), fill=_COLORS["title"] if not r else _COLORS["accent"], anchor="ls")
        y += 58
        if y > HEIGHT - 90:
            if r < len(rows):
                overflow.append("table")
            break


# ------------------------------------------------------------------ 오디오 연결·자막·챕터
def _wav_bytes(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


def assemble_timeline(scene_audio: Sequence[AudioResult], rate: int) -> tuple[bytes, list[dict[str, int]], list[list[tuple[int, int]]]]:
    """장면별 PCM을 무음(장면 사이 450ms, 끝 600ms)과 함께 잇는다.
    (연결 PCM, 장면 구간[{start_ms,end_ms}], 장면별 문장 구간(전체 시간 기준))."""
    pcm = bytearray()
    spans: list[dict[str, int]] = []
    cues: list[list[tuple[int, int]]] = []
    for index, audio in enumerate(scene_audio):
        start_ms = round(len(pcm) / 2 * 1000 / rate)
        pcm += audio.pcm
        pcm += b"\x00\x00" * (rate * (GAP_SCENE_MS if index < len(scene_audio) - 1 else TAIL_MS) // 1000)
        end_ms = round(len(pcm) / 2 * 1000 / rate)
        spans.append({"start_ms": start_ms, "end_ms": end_ms})
        cues.append([(start_ms + a, start_ms + b) for a, b in audio.segments])
    return bytes(pcm), spans, cues


def build_cues(narration: str, speech: str | None, sentence_spans: Sequence[tuple[int, int]], scene_span: Mapping[str, int]) -> list[dict[str, Any]]:
    """자막 줄. 읽는 문장 수와 자막 문장 수가 같으면 문장별로, 다르면 장면 전체에 한 줄로 붙인다."""
    shown = split_sentences(narration)
    if len(shown) == len(sentence_spans) and shown:
        return [{"start_ms": a, "end_ms": b, "text": text} for text, (a, b) in zip(shown, sentence_spans)]
    return [{"start_ms": scene_span["start_ms"], "end_ms": scene_span["end_ms"], "text": " ".join(narration.split())}]


def _vtt_time(ms: int) -> str:
    hours, rest = divmod(max(0, int(ms)), 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def render_vtt(body: Mapping[str, Any]) -> bytes:
    """본문(scenes[].cues)에서 WebVTT를 만든다."""
    out = ["WEBVTT", ""]
    number = 0
    for scene in body.get("scenes", []):
        for cue in scene.get("cues", []):
            number += 1
            text = str(cue.get("text", "")).replace("-->", "→").replace("&", "&amp;").replace("<", "&lt;")
            out += [str(number), f"{_vtt_time(cue['start_ms'])} --> {_vtt_time(cue['end_ms'])}", text, ""]
    return "\n".join(out).encode("utf-8")


def chapter_metadata(chapters: Sequence[Mapping[str, Any]]) -> str:
    def esc(value: str) -> str:
        return re.sub(r"([=;#\\\n])", r"\\\1", value)
    lines = [";FFMETADATA1"]
    for chapter in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(chapter['start_ms'])}", f"END={int(chapter['end_ms'])}", f"title={esc(str(chapter['title']))}"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ ffmpeg 합성
def compose_mp4(pngs: Sequence[bytes], spans: Sequence[Mapping[str, int]], wav: bytes, chapters: Sequence[Mapping[str, Any]], *,
                ffmpeg: str | None = None, timeout: int = FFMPEG_TIMEOUT, runner: Callable[..., Any] = subprocess.run) -> bytes:
    """장면 이미지(각 장면 길이만큼)와 연결 음성을 H.264+AAC mp4 한 파일로 만든다. 챕터 메타데이터 포함."""
    exe = ffmpeg or ffmpeg_path()
    if exe is None:
        raise StudioError("VIDEO_ENCODER_UNAVAILABLE", 503)
    with tempfile.TemporaryDirectory(prefix="daon-video-") as directory:
        base = Path(directory)
        listing = []
        for index, (png, span) in enumerate(zip(pngs, spans)):
            (base / f"s{index}.png").write_bytes(png)
            listing += [f"file 's{index}.png'", f"duration {(span['end_ms'] - span['start_ms']) / 1000:.3f}"]
        listing.append(f"file 's{len(pngs) - 1}.png'")   # concat demuxer는 마지막 duration을 무시하므로 한 번 더 적는다
        (base / "list.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
        (base / "audio.wav").write_bytes(wav)
        (base / "chapters.txt").write_text(chapter_metadata(chapters), encoding="utf-8")
        command = [exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-i", "audio.wav",
                   "-i", "chapters.txt", "-map", "0:v", "-map", "1:a", "-map_metadata", "2", "-map_chapters", "2",
                   "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "30",
                   "-c:a", "aac", "-b:a", "64k", "-ar", "44100", "-ac", "1", "-threads", "2", "-movflags", "+faststart", "-shortest", "out.mp4"]
        try:
            done = runner(command, cwd=directory, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise StudioError("VIDEO_ENCODE_FAILED", 502) from None
        except OSError:
            raise StudioError("VIDEO_ENCODER_UNAVAILABLE", 503) from None
        output = base / "out.mp4"
        if done.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise StudioError("VIDEO_ENCODE_FAILED", 502)
        return output.read_bytes()


# ------------------------------------------------------------------ 생성기
class VideoOverviewGenerator(_Base):
    type_id = "video_overview"
    max_tokens = 6000
    SCHEMA = {"type": "object", "properties": {
        "title": {"type": "string"},
        "scenes": {"type": "array", "items": {"type": "object", "properties": {
            "layout": {"type": "string", "enum": ["title", "bullets", "two_column", "table"]}, "title": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "string"}},
            "table": {"type": "object", "properties": {"columns": {"type": "array", "items": {"type": "string"}},
                                                        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}}},
            "narration": {"type": "string"}, "speech": {"type": "string"}, "refs": _REFS}, "required": ["title", "narration", "refs"]}}},
        "required": ["scenes"]}

    def __init__(self, reader, llm, config: "TtsConfig | Callable[[str], TtsConfig | None]", *, egress_gate: StudioEgressGate | None = None,  # type: ignore[no-untyped-def]
                 client_factory: Callable[[TtsEngine], TtsClient] = TtsClient, composer: Callable[..., bytes] = compose_mp4,
                 context_chars: int = 24_000) -> None:
        super().__init__(reader, llm, context_chars=context_chars)
        self._config = config
        self._gate = egress_gate
        self._client_factory = client_factory
        self._composer = composer

    def _config_for(self, ctx: GenerationContext) -> TtsConfig:
        config = self._config(ctx.context.tenant_id) if callable(self._config) else self._config
        if config is None:
            raise StudioError("TTS_ENGINE_UNKNOWN", 409)
        return config

    def _engine_and_voice(self, ctx: GenerationContext, config: TtsConfig) -> tuple[TtsEngine, str]:
        try:
            engine = config.resolve(str(ctx.settings.get("engine") or "") or None)
        except TtsError as error:
            raise StudioError(error.code, 409) from None
        voice = engine.voices["A"]
        chosen = ctx.settings.get("voice_a")
        if chosen:
            if chosen not in engine.voice_choices:
                raise StudioError("TTS_VOICE_UNKNOWN", 409)
            voice = str(chosen)
        return engine, voice

    def _authorize(self, ctx: GenerationContext, engine: TtsEngine, size_bytes: int) -> bool:
        if self._gate is None:
            if engine.provider_kind == "external_api":
                raise StudioError("EGRESS_POLICY_UNAVAILABLE", 409)
            return False
        decision = self._gate.authorize(ctx.context, _EgressModel(engine), size_bytes)
        if not decision.allowed:
            raise StudioError(decision.reason, 409)
        return decision.masked

    def generate(self, ctx: GenerationContext) -> GenerationResult:
        if ffmpeg_path() is None:
            raise StudioError("VIDEO_ENCODER_UNAVAILABLE", 503)
        config = self._config_for(ctx)
        engine, voice = self._engine_and_voice(ctx, config)
        pack = self._pack(ctx)
        lo, hi, span = LENGTHS.get(str(ctx.settings.get("length", "normal")), LENGTHS["normal"])
        ctx.progress(8, "장면 작성")
        data = self._ask(
            ctx, f"소스의 핵심을 설명하는 동영상 개요의 장면 {lo}~{hi}개를 만드세요({span} 분량). 첫 장면은 layout=title로 주제를 소개하고 마지막 장면은 정리합니다. "
                 "각 장면은 슬라이드 화면(title 40자 이내, bullets 최대 4개·각 60자 이내 또는 table)과 내레이션(narration, 화면 자막용 원문, 한 장면 300자 이내의 말하는 문장)과 refs를 갖습니다. "
                 "화면에 보이는 title·bullets·narration에는 숫자와 기호를 소스 원문 그대로 씁니다(예: 1,000,000원, 90일). 소리 내어 읽는 형태(백만 원, 구십 일)는 오직 speech에만 적고, 읽는 형태가 narration과 같으면 speech를 생략합니다. 소스에 없는 사실·숫자를 만들지 마세요.",
            self.SCHEMA, pack, tokens=self.max_tokens)
        body, warnings, used = V.validate_video_scenes(data, pack, max_scenes=hi + 4)
        scenes: list[dict[str, Any]] = body["scenes"]  # type: ignore[assignment]
        spoken_texts = [str(s.get("speech") or s["narration"]) for s in scenes]
        sentences = [split_sentences(text) for text in spoken_texts]
        if self._authorize(ctx, engine, sum(len(t.encode("utf-8")) for t in spoken_texts)):
            sentences = [[mask_text(x) for x in group] for group in sentences]
        import time
        started = time.monotonic()
        client = self._client_factory(engine)
        scene_audio: list[AudioResult] = []
        try:
            if not client.health():
                raise StudioError("TTS_ENGINE_UNREACHABLE", 503)
            for index, group in enumerate(sentences):
                ctx.progress(15 + int(55 * index / len(sentences)), f"내레이션 합성 {index + 1}/{len(sentences)}")
                ctx.cancel_check()
                try:
                    scene_audio.append(synthesize_dialogue(client, engine, [Spoken("A", text) for text in group], voices={"A": voice, "B": voice},
                                                           max_total_seconds=config.max_total_seconds, encode=False, started=started))
                except TtsError as error:
                    raise StudioError(error.code, 503 if error.retryable else 502) from None
        finally:
            client.close()
        rates = {a.rate for a in scene_audio}
        if len(rates) != 1:
            raise StudioError("TTS_AUDIO_INVALID", 502)
        rate = rates.pop()
        pcm, spans, sentence_spans = assemble_timeline(scene_audio, rate)
        ctx.progress(72, "화면 그리기")
        pngs: list[bytes] = []
        for index, scene in enumerate(scenes):
            png, over = render_scene_png(scene, index + 1, len(scenes))
            pngs.append(png)
            for path in over:
                warnings.append({"code": "VIDEO_TEXT_TRUNCATED", "path": f"scenes[{index}].{path}"})
            scene.update(spans[index])
            scene["cues"] = build_cues(str(scene["narration"]), scene.get("speech"), sentence_spans[index], spans[index])  # type: ignore[arg-type]
        chapters = [{"title": str(s["title"]), "start_ms": s["start_ms"], "end_ms": s["end_ms"]} for s in scenes]
        ctx.progress(80, "영상 합성")
        ctx.cancel_check()
        video = self._composer(pngs, spans, _wav_bytes(pcm, rate), chapters)
        duration_ms = spans[-1]["end_ms"]
        body.update({"chapters": chapters, "duration_ms": duration_ms, "engine": engine.engine_id, "voice": voice,
                     "video": {"width": WIDTH, "height": HEIGHT, "fps": FPS}})
        result = self._finish(ctx, pack, dict(body), warnings, used)
        generated_with = {**dict(result.generated_with), "tts_engine": engine.engine_id, "tts_voice": voice}
        return GenerationResult(content=result.content, warnings=result.warnings, generated_with=generated_with, sources=result.sources,
                                evidence=result.evidence, assets=({"kind": "mp4", "content_type": "video/mp4", "content": video, "duration_ms": duration_ms},))
