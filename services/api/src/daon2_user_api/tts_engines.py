"""선택 가능한 TTS 엔진(WO-F7). 같은 HTTP 규격(OpenAI 호환 `/v1/audio/speech`)을 쓰는 엔진만 등록한다.

설정은 배포가 정하는 JSON 파일(비밀 파일, 키 포함)이다. 사용자 입력으로 주소를 바꿀 수 없다.

    {"default": "supertonic", "max_total_seconds": 1800,
     "engines": [{"id": "supertonic", "label": "Supertonic", "base_url": "http://host:8201", "api_key": "...",
                  "provider_kind": "external_api", "language": "ko", "timeout_seconds": 120,
                  "voices": {"A": "F1", "B": "M1"}, "voice_choices": ["F1", "F2", "M1", "M2"]}]}

`provider_kind`는 외부 전송 정책 판정에 쓴다(기본 `external_api` = 정책이 허용한 목적지만).
"""

from __future__ import annotations

import io
import json
import re
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_VOICE = re.compile(r"[A-Za-z0-9_.-]{1,40}")
MAX_LINE_CHARS = 400
GAP_SAME_MS = 200
GAP_TURN_MS = 350
MP3_KBPS = 128


class TtsError(RuntimeError):
    def __init__(self, code: str, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class TtsEngine:
    engine_id: str
    label: str
    base_url: str
    api_key: str
    provider_kind: str
    language: str
    timeout_seconds: float
    voices: Mapping[str, str]
    voice_choices: tuple[str, ...]
    source: str = "deployment"   # deployment(배포 설정 파일) | settings(관리 화면 등록)

    @property
    def host(self) -> str:
        return (urlsplit(self.base_url).hostname or "").lower()


@dataclass(frozen=True, slots=True)
class TtsConfig:
    engines: Mapping[str, TtsEngine]
    default: str
    max_total_seconds: float

    def resolve(self, engine_id: str | None) -> TtsEngine:
        engine = self.engines.get(engine_id or self.default)
        if engine is None:
            raise TtsError("TTS_ENGINE_UNKNOWN")
        return engine

    def settings_overlay(self) -> dict[str, object]:
        """`/studio/types`의 audio_overview 설정 스키마에 덧씌울 선택지."""
        voices = sorted({v for e in self.engines.values() for v in e.voice_choices})
        return {"engine": {"type": "string", "enum": list(self.engines), "default": self.default},
                "voice_a": {"type": "string", "enum": voices}, "voice_b": {"type": "string", "enum": voices}}


def load_config(path: str | Path | None) -> TtsConfig | None:
    """파일이 없거나 비어 있으면 None(TTS 비활성). 형식이 잘못되면 ValueError."""
    if not path:
        return None
    file = Path(path)
    if not file.is_file():
        return None
    raw = json.loads(file.read_text(encoding="utf-8"))
    engines: dict[str, TtsEngine] = {}
    for item in raw.get("engines", ()):
        engine_id = str(item.get("id", ""))
        base_url = str(item.get("base_url", "")).rstrip("/")
        parts = urlsplit(base_url)
        if not _ID.fullmatch(engine_id) or parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("TTS_CONFIG_INVALID")
        voices = {k: str(v) for k, v in dict(item.get("voices", {})).items() if k in {"A", "B"}}
        choices = tuple(str(v) for v in item.get("voice_choices", voices.values()))
        if set(voices) != {"A", "B"} or not all(_VOICE.fullmatch(v) for v in (*voices.values(), *choices)):
            raise ValueError("TTS_CONFIG_INVALID")
        kind = str(item.get("provider_kind", "external_api"))
        if kind not in {"external_api", "server_internal", "local", "local_runtime"}:
            raise ValueError("TTS_CONFIG_INVALID")
        engines[engine_id] = TtsEngine(
            engine_id, str(item.get("label", engine_id))[:60], base_url, str(item.get("api_key", "")), kind,
            str(item.get("language", "ko")), max(5.0, min(float(item.get("timeout_seconds", 120)), 600.0)),
            voices, choices)
    if not engines:
        return None
    default = str(raw.get("default", next(iter(engines))))
    if default not in engines:
        raise ValueError("TTS_CONFIG_INVALID")
    return TtsConfig(engines, default, max(60.0, min(float(raw.get("max_total_seconds", 1800)), 7200.0)))


class TtsClient:
    """엔진 하나를 호출한다. 문장 하나에 WAV(16비트 PCM) 하나."""

    def __init__(self, engine: TtsEngine, *, transport: httpx.BaseTransport | None = None) -> None:
        self._engine = engine
        self._http = httpx.Client(timeout=engine.timeout_seconds, transport=transport, follow_redirects=False)

    def close(self) -> None:
        self._http.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._engine.api_key}"} if self._engine.api_key else {}

    def health(self) -> bool:
        try:
            response = self._http.get(f"{self._engine.base_url}/health", timeout=10)
            return response.status_code == 200 and bool(response.json().get("ready", True))
        except Exception:
            return False

    def voices(self) -> list[str]:
        """엔진이 알려 주는 보이스 id 목록(`/v1/voices`). 인증 실패는 TtsError, 엔드포인트가 없으면 빈 목록."""
        try:
            response = self._http.get(f"{self._engine.base_url}/v1/voices", headers=self._headers(), timeout=10)
        except httpx.TimeoutException:
            raise TtsError("TTS_TIMEOUT", True) from None
        except httpx.HTTPError:
            raise TtsError("TTS_ENGINE_UNREACHABLE", True) from None
        if response.status_code in (401, 403):
            raise TtsError("TTS_ENGINE_AUTH_FAILED")
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            raise TtsError("TTS_ENGINE_UNAVAILABLE", response.status_code >= 500)
        try:
            payload = response.json()
        except ValueError:
            return []
        items = payload.get("voices", []) if isinstance(payload, dict) else payload
        found: list[str] = []
        for item in items if isinstance(items, list) else []:
            value = item.get("id") or item.get("name") if isinstance(item, dict) else item
            if isinstance(value, str) and _VOICE.fullmatch(value) and value not in found:
                found.append(value)
        return found[:64]

    def synthesize(self, text: str, voice: str, language: str) -> tuple[bytes, int]:
        """(PCM16 모노 바이트, 샘플레이트)."""
        if not text.strip() or len(text) > MAX_LINE_CHARS * 2 or not _VOICE.fullmatch(voice):
            raise TtsError("TTS_INPUT_INVALID")
        body = {"input": text, "voice": voice, "language": language, "response_format": "wav"}
        try:
            response = self._http.post(f"{self._engine.base_url}/v1/audio/speech", json=body, headers=self._headers())
        except httpx.TimeoutException:
            raise TtsError("TTS_TIMEOUT", True) from None
        except httpx.HTTPError:
            raise TtsError("TTS_ENGINE_UNREACHABLE", True) from None
        if response.status_code in (401, 403):
            raise TtsError("TTS_ENGINE_AUTH_FAILED")
        if response.status_code >= 500 or response.status_code == 503:
            raise TtsError("TTS_ENGINE_UNAVAILABLE", True)
        if response.status_code != 200:
            raise TtsError("TTS_ENGINE_REJECTED")
        return parse_wav(response.content)


def parse_wav(data: bytes) -> tuple[bytes, int]:
    try:
        with wave.open(io.BytesIO(data)) as reader:
            if reader.getsampwidth() != 2 or reader.getnframes() == 0:
                raise TtsError("TTS_AUDIO_INVALID")
            channels, rate = reader.getnchannels(), reader.getframerate()
            frames = reader.readframes(reader.getnframes())
    except (wave.Error, EOFError):
        raise TtsError("TTS_AUDIO_INVALID") from None
    if channels == 2:  # 모노로 합친다
        import array
        samples = array.array("h")
        samples.frombytes(frames)
        mono = array.array("h", ((samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples) - 1, 2)))
        frames = mono.tobytes()
    elif channels != 1:
        raise TtsError("TTS_AUDIO_INVALID")
    if not 8000 <= rate <= 48000:
        raise TtsError("TTS_AUDIO_INVALID")
    return frames, rate


@dataclass(frozen=True, slots=True)
class Spoken:
    speaker: str
    text: str   # 읽을 문장(숫자·기호를 읽는 형태로 푼 것일 수 있다)


@dataclass(frozen=True, slots=True)
class AudioResult:
    mp3: bytes
    duration_ms: int
    segments: tuple[tuple[int, int], ...]   # 줄마다 (시작 ms, 끝 ms)
    pcm: bytes = b""                        # 16비트 모노 PCM(동영상 합성용). mp3를 쓰지 않으면 encode=False로 비워 둔다
    rate: int = 0


def synthesize_dialogue(client: TtsClient, engine: TtsEngine, lines: Sequence[Spoken], *, voices: Mapping[str, str],
                        max_total_seconds: float, progress: Callable[[int, int], None] | None = None,
                        clock: Callable[[], float] = time.monotonic, encode: bool = True,
                        started: float | None = None) -> AudioResult:
    """줄마다 합성해 무음을 끼워 이어 붙이고 mp3로 인코딩한다. 전체 시간 한도를 넘기면 TTS_TIME_BUDGET_EXCEEDED."""
    started = clock() if started is None else started
    rate = 0
    pcm = bytearray()
    segments: list[tuple[int, int]] = []
    previous = ""
    for index, line in enumerate(lines):
        if clock() - started > max_total_seconds:
            raise TtsError("TTS_TIME_BUDGET_EXCEEDED")
        for attempt in (1, 2):
            try:
                frames, line_rate = client.synthesize(line.text, voices[line.speaker], engine.language)
                break
            except TtsError as error:
                if not error.retryable or attempt == 2:
                    raise
        if rate and line_rate != rate:
            raise TtsError("TTS_AUDIO_INVALID")
        rate = line_rate
        if previous:
            gap_ms = GAP_TURN_MS if previous != line.speaker else GAP_SAME_MS
            pcm += b"\x00\x00" * (rate * gap_ms // 1000)
        start = round(len(pcm) / 2 * 1000 / rate)
        pcm += frames
        segments.append((start, round(len(pcm) / 2 * 1000 / rate)))
        previous = line.speaker
        if progress:
            progress(index + 1, len(lines))
    if not pcm:
        raise TtsError("TTS_AUDIO_INVALID")
    return AudioResult(encode_mp3(bytes(pcm), rate) if encode else b"", round(len(pcm) / 2 * 1000 / rate), tuple(segments), bytes(pcm), rate)


def encode_mp3(pcm: bytes, rate: int) -> bytes:
    import lameenc
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(MP3_KBPS)
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    return bytes(encoder.encode(pcm)) + bytes(encoder.flush())


def configured_from_env() -> TtsConfig | None:
    """DAON_TTS_CONFIG_FILE에서 설정을 읽는다. 없거나 잘못되면 None(TTS 비활성)."""
    import os
    try:
        return load_config(os.environ.get("DAON_TTS_CONFIG_FILE", "").strip() or None)
    except (ValueError, OSError):
        return None
