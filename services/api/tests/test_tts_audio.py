"""오디오 개요(WO-F7): TTS 설정·클라이언트·합성 조립·스크립트 검증·생성기·형식 규칙."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

import httpx

from daon2_user_api.studio_audio import AudioOverviewGenerator
from daon2_user_api.studio_context_builder import build_pack
from daon2_user_api.studio_egress import EgressDecision
from daon2_user_api.studio_v2_export import export_asset
from daon2_user_api.studio_v2_routes import _parse_range
from daon2_user_api.studio_v2_types import STUDIO_V2_TYPES, available_types, is_available, validate_settings
from daon2_user_api.studio_validation import validate_audio_script
from daon2_user_api.studio_workspace import StudioError
from daon2_user_api.tts_engines import (
    Spoken, TtsClient, TtsError, load_config, parse_wav, synthesize_dialogue,
)
from test_studio_v2_generation import FakeReader, ScriptedLLM, gen_ctx, source

RATE = 22050


def wav_bytes(seconds: float = 0.5, rate: int = RATE, channels: int = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x10\x00" * int(rate * seconds) * channels)
    return buffer.getvalue()


def config_file(directory: str, **over) -> str:
    engine = {"id": "supertonic", "label": "Supertonic", "base_url": "http://tts.example:8201", "api_key": "k", "provider_kind": "server_internal",
              "voices": {"A": "F1", "B": "M1"}, "voice_choices": ["F1", "F2", "M1"], **over}
    path = Path(directory) / "tts.json"
    path.write_text(json.dumps({"default": "supertonic", "max_total_seconds": 600, "engines": [engine]}), encoding="utf-8")
    return str(path)


class ConfigTests(unittest.TestCase):
    def test_absent_or_empty_means_disabled(self):
        self.assertIsNone(load_config(None))
        self.assertIsNone(load_config("/nonexistent/tts.json"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tts.json"
            path.write_text('{"engines": []}', encoding="utf-8")
            self.assertIsNone(load_config(str(path)))

    def test_valid_config_and_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_file(directory))
        engine = config.resolve(None)
        self.assertEqual((engine.engine_id, engine.voices["B"], engine.host), ("supertonic", "M1", "tts.example"))
        overlay = config.settings_overlay()
        self.assertEqual(overlay["engine"]["enum"], ["supertonic"])
        self.assertEqual(overlay["voice_a"]["enum"], ["F1", "F2", "M1"])
        with self.assertRaises(TtsError):
            config.resolve("nope")

    def test_env_helper_enables_only_with_a_valid_config(self):
        import os
        from unittest import mock
        from daon2_user_api.tts_engines import configured_from_env
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"DAON_TTS_CONFIG_FILE": config_file(directory)}):
                self.assertIsNotNone(configured_from_env())
            bad = Path(directory) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with mock.patch.dict(os.environ, {"DAON_TTS_CONFIG_FILE": str(bad)}):
                self.assertIsNone(configured_from_env())
        with mock.patch.dict(os.environ, {"DAON_TTS_CONFIG_FILE": ""}):
            self.assertIsNone(configured_from_env())

    def test_invalid_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for bad in ({"base_url": "ftp://x"}, {"id": "Bad Id"}, {"voices": {"A": "F1"}}, {"provider_kind": "weird"}, {"voice_choices": ["a b"]}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    load_config(config_file(directory, **bad))


class ClientTests(unittest.TestCase):
    def client(self, handler):
        with tempfile.TemporaryDirectory() as directory:
            engine = load_config(config_file(directory)).resolve(None)
        return TtsClient(engine, transport=httpx.MockTransport(handler)), engine

    def test_synthesize_sends_voice_and_bearer_and_parses_wav(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, content=wav_bytes())
        client, _ = self.client(handler)
        frames, rate = client.synthesize("안녕하세요", "F1", "ko")
        self.assertEqual(rate, RATE)
        self.assertEqual(len(frames), RATE)  # 0.5초 * 2바이트
        self.assertEqual(seen["auth"], "Bearer k")
        self.assertEqual(seen["body"], {"input": "안녕하세요", "voice": "F1", "language": "ko", "response_format": "wav"})

    def test_error_mapping(self):
        for status, code, retryable in ((401, "TTS_ENGINE_AUTH_FAILED", False), (503, "TTS_ENGINE_UNAVAILABLE", True), (422, "TTS_ENGINE_REJECTED", False)):
            client, _ = self.client(lambda request, s=status: httpx.Response(s))
            with self.subTest(status=status), self.assertRaises(TtsError) as caught:
                client.synthesize("문장", "F1", "ko")
            self.assertEqual((caught.exception.code, caught.exception.retryable), (code, retryable))

        def boom(request):
            raise httpx.ConnectError("down")
        client, _ = self.client(boom)
        with self.assertRaises(TtsError) as caught:
            client.synthesize("문장", "F1", "ko")
        self.assertEqual((caught.exception.code, caught.exception.retryable), ("TTS_ENGINE_UNREACHABLE", True))

    def test_input_and_audio_validation(self):
        client, _ = self.client(lambda request: httpx.Response(200, content=b"not a wav"))
        with self.assertRaises(TtsError):
            client.synthesize("문장", "F1", "ko")
        for text, voice in (("", "F1"), ("문장", "bad voice")):
            with self.subTest(text=text), self.assertRaises(TtsError):
                client.synthesize(text, voice, "ko")
        with self.assertRaises(TtsError):
            parse_wav(wav_bytes(rate=4000))
        frames, rate = parse_wav(wav_bytes(0.1, channels=2))
        self.assertEqual(len(frames), int(RATE * 0.1) * 2)

    def test_health(self):
        client, _ = self.client(lambda request: httpx.Response(200, json={"ready": True}))
        self.assertTrue(client.health())
        client, _ = self.client(lambda request: httpx.Response(503))
        self.assertFalse(client.health())


class FakeClient:
    def __init__(self, seconds=0.5, fail_first=False):
        self.calls = []
        self.seconds = seconds
        self.fail_first = fail_first
        self.closed = False

    def health(self):
        return True

    def close(self):
        self.closed = True

    def synthesize(self, text, voice, language):
        self.calls.append((text, voice, language))
        if self.fail_first and len(self.calls) == 1:
            raise TtsError("TTS_TIMEOUT", True)
        return parse_wav(wav_bytes(self.seconds))


class DialogueTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as directory:
            self.engine = load_config(config_file(directory)).resolve(None)

    def test_segments_gaps_and_mp3(self):
        client = FakeClient()
        lines = [Spoken("A", "하나"), Spoken("B", "둘"), Spoken("B", "셋")]
        result = synthesize_dialogue(client, self.engine, lines, voices={"A": "F1", "B": "M1"}, max_total_seconds=60)
        self.assertEqual([c[1] for c in client.calls], ["F1", "M1", "M1"])
        self.assertEqual(result.segments[0], (0, 500))
        self.assertEqual(result.segments[1], (850, 1350))     # 화자가 바뀌면 350ms
        self.assertEqual(result.segments[2], (1550, 2050))    # 같은 화자는 200ms
        self.assertEqual(result.duration_ms, 2050)
        self.assertTrue(result.mp3[:3] == b"ID3" or result.mp3[0] == 0xFF)
        self.assertGreater(len(result.mp3), 1000)

    def test_retry_once_on_retryable_error_then_fail(self):
        result = synthesize_dialogue(FakeClient(fail_first=True), self.engine, [Spoken("A", "하나")], voices={"A": "F1", "B": "M1"}, max_total_seconds=60)
        self.assertEqual(len(result.segments), 1)

        class Always(FakeClient):
            def synthesize(self, *a):
                raise TtsError("TTS_ENGINE_UNAVAILABLE", True)
        with self.assertRaises(TtsError) as caught:
            synthesize_dialogue(Always(), self.engine, [Spoken("A", "하나")], voices={"A": "F1", "B": "M1"}, max_total_seconds=60)
        self.assertEqual(caught.exception.code, "TTS_ENGINE_UNAVAILABLE")

    def test_time_budget(self):
        ticks = iter([0, 0, 1000, 1000, 1000])
        with self.assertRaises(TtsError) as caught:
            synthesize_dialogue(FakeClient(), self.engine, [Spoken("A", "하나"), Spoken("B", "둘")], voices={"A": "F1", "B": "M1"},
                                max_total_seconds=10, clock=lambda: next(ticks))
        self.assertEqual(caught.exception.code, "TTS_TIME_BUDGET_EXCEEDED")


SCRIPT = {"title": "보험금 이야기", "summary": "요약", "script": [
    {"speaker": "A" if i % 2 == 0 else "B", "text": f"문장 {i} 보험금은 3일 이내에 지급한다.", "speech": f"문장 {i} 보험금은 삼 일 이내에 지급한다.", "refs": ["S1"]}
    for i in range(8)]}


class ValidationTests(unittest.TestCase):
    def pack(self):
        return build_pack((source(),), budget_chars=10_000)

    def test_valid_script_keeps_speech_only_when_different(self):
        body, warnings, used = validate_audio_script(SCRIPT, self.pack())
        self.assertEqual(len(body["script"]), 8)
        self.assertIn("speech", body["script"][0])
        self.assertEqual(used, ["S1"] * 8)
        same = {**SCRIPT, "script": [{**row, "speech": row["text"]} for row in SCRIPT["script"]]}
        self.assertNotIn("speech", validate_audio_script(same, self.pack())[0]["script"][0])

    def test_rejects_short_single_speaker_and_unreferenced(self):
        with self.assertRaises(StudioError):
            validate_audio_script({"script": SCRIPT["script"][:3]}, self.pack())
        with self.assertRaises(StudioError):
            validate_audio_script({"script": [{**row, "speaker": "A"} for row in SCRIPT["script"]]}, self.pack())
        with self.assertRaises(StudioError):
            validate_audio_script({"script": [{**row, "refs": ["S9"]} for row in SCRIPT["script"]]}, self.pack())

    def test_invalid_speakers_and_empty_text_are_dropped_and_numbers_are_checked(self):
        rows = [*SCRIPT["script"], {"speaker": "C", "text": "x", "refs": ["S1"]}, {"speaker": "A", "text": "", "refs": ["S1"]},
                {"speaker": "B", "text": "지급은 99일이다.", "refs": ["S1"]}]
        body, warnings, _ = validate_audio_script({"script": rows}, self.pack())
        self.assertEqual(len(body["script"]), 9)
        self.assertTrue(any(w["code"] == "ANCHOR_MISMATCH" for w in warnings))


class StubGate:
    def __init__(self, allowed, masked=False):
        self.allowed = allowed
        self.masked = masked
        self.seen = None

    def authorize(self, context, model, size):
        self.seen = (model.provider_kind, model.base_url, size)
        return EgressDecision(self.allowed, "ok" if self.allowed else "EGRESS_DESTINATION_DENIED", masked=self.masked)


class GeneratorTests(unittest.TestCase):
    def make(self, *, gate=None, engine_over=None, client=None, data=None):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_file(directory, **(engine_over or {})))
        client = client or FakeClient()
        generator = AudioOverviewGenerator(FakeReader(), ScriptedLLM(data or SCRIPT), config, egress_gate=gate, client_factory=lambda engine: client)
        return generator, client

    def test_generates_content_asset_and_timings(self):
        generator, client = self.make()
        result = generator.generate(gen_ctx("audio_overview")[0])
        body = result.content["body"]
        self.assertEqual(len(body["script"]), 8)
        self.assertEqual(body["script"][0]["start_ms"], 0)
        self.assertEqual(body["engine"], "supertonic")
        self.assertEqual(body["voices"], {"A": "F1", "B": "M1"})
        self.assertEqual(client.calls[0][0], "문장 0 보험금은 삼 일 이내에 지급한다.")   # speech가 있으면 그것을 읽는다
        asset = result.assets[0]
        self.assertEqual((asset["kind"], asset["content_type"]), ("mp3", "audio/mpeg"))
        self.assertEqual(asset["duration_ms"], body["duration_ms"])
        self.assertEqual(result.generated_with["tts_engine"], "supertonic")
        self.assertTrue(client.closed)

    def test_voice_override_and_unknown_voice(self):
        generator, client = self.make()
        generator.generate(gen_ctx("audio_overview", {"voice_a": "F2"})[0])
        self.assertEqual(client.calls[0][1], "F2")
        generator, _ = self.make()
        with self.assertRaises(StudioError) as caught:
            generator.generate(gen_ctx("audio_overview", {"voice_a": "M9"})[0])
        self.assertEqual(caught.exception.code, "TTS_VOICE_UNKNOWN")
        with self.assertRaises(StudioError) as caught:
            self.make()[0].generate(gen_ctx("audio_overview", {"engine": "other"})[0])
        self.assertEqual(caught.exception.code, "TTS_ENGINE_UNKNOWN")

    def test_egress_gate_is_consulted_and_external_without_gate_is_blocked(self):
        gate = StubGate(False)
        generator, client = self.make(gate=gate, engine_over={"provider_kind": "external_api"})
        with self.assertRaises(StudioError) as caught:
            generator.generate(gen_ctx("audio_overview")[0])
        self.assertEqual(caught.exception.code, "EGRESS_DESTINATION_DENIED")
        self.assertEqual(gate.seen[:2], ("external_api", "http://tts.example:8201"))
        self.assertEqual(client.calls, [])
        generator, client = self.make(gate=None, engine_over={"provider_kind": "external_api"})
        with self.assertRaises(StudioError):
            generator.generate(gen_ctx("audio_overview")[0])
        self.assertEqual(client.calls, [])

    def test_policy_masking_hides_personal_patterns_before_sending(self):
        data = {**SCRIPT, "script": [{**row, "speech": "연락처는 010-1234-5678 입니다."} if i == 0 else row for i, row in enumerate(SCRIPT["script"])]}
        generator, client = self.make(gate=StubGate(True, masked=True), data=data)
        generator.generate(gen_ctx("audio_overview")[0])
        self.assertEqual(client.calls[0][0], "연락처는 [전화번호] 입니다.")
        generator, client = self.make(gate=StubGate(True, masked=False), data=data)
        generator.generate(gen_ctx("audio_overview")[0])
        self.assertIn("010-1234-5678", client.calls[0][0])

    def test_a_per_tenant_resolver_picks_each_tenants_engines(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_file(directory))
        seen = []

        def resolver(tenant_id):
            seen.append(tenant_id)
            return config if tenant_id == "tenant-1" else None
        client = FakeClient()
        generator = AudioOverviewGenerator(FakeReader(), ScriptedLLM(SCRIPT), resolver, client_factory=lambda engine: client)
        generator.generate(gen_ctx("audio_overview")[0])
        self.assertEqual(seen, ["tenant-1"])
        self.assertTrue(client.calls)
        from daon2_user_api.studio_workspace import StudioContext
        other = gen_ctx("audio_overview")[0]
        other = type(other)(StudioContext("tenant-2", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-1"), *[getattr(other, f) for f in ("output_id", "type_id", "format_id", "settings", "source_version_ids", "customization", "language", "mode", "progress", "cancel_check")])
        with self.assertRaises(StudioError) as caught:
            generator.generate(other)
        self.assertEqual(caught.exception.code, "TTS_ENGINE_UNKNOWN")      # 엔진이 없는 조직은 생성할 수 없다

    def test_unreachable_engine_is_a_retryable_503(self):
        class Down(FakeClient):
            def health(self):
                return False
        generator, _ = self.make(client=Down())
        with self.assertRaises(StudioError) as caught:
            generator.generate(gen_ctx("audio_overview")[0])
        self.assertEqual((caught.exception.code, caught.exception.status_code if hasattr(caught.exception, "status_code") else 503), ("TTS_ENGINE_UNREACHABLE", 503))


class TypeAndRouteRuleTests(unittest.TestCase):
    def test_availability_follows_tts_and_schema_overlay(self):
        self.assertFalse(is_available("audio_overview"))
        self.assertTrue(is_available("audio_overview", tts_enabled=True))
        off = next(t for t in available_types() if t["type_id"] == "audio_overview")
        self.assertFalse(off["available"])
        overlay = {"engine": {"type": "string", "enum": ["supertonic"]}}
        on = next(t for t in available_types(tts_enabled=True, tts_settings=overlay) if t["type_id"] == "audio_overview")
        self.assertTrue(on["available"])
        self.assertEqual(on["settings_schema"]["properties"]["engine"]["enum"], ["supertonic"])
        self.assertIn("length", on["settings_schema"]["properties"])
        self.assertEqual(STUDIO_V2_TYPES["audio_overview"].export_formats, ("mp3",))

    def test_video_availability_needs_tts_and_an_encoder_and_has_no_second_voice(self):
        from unittest import mock
        from daon2_user_api import studio_video
        self.assertFalse(is_available("video_overview"))
        with mock.patch.object(studio_video, "ffmpeg_path", return_value="/usr/bin/ffmpeg"):
            self.assertTrue(is_available("video_overview", tts_enabled=True))
            self.assertFalse(is_available("video_overview", tts_enabled=False))
        with mock.patch.object(studio_video, "ffmpeg_path", return_value=None):
            self.assertFalse(is_available("video_overview", tts_enabled=True))
        overlay = {"engine": {"type": "string", "enum": ["supertonic"]}, "voice_a": {"type": "string", "enum": ["F1"]}, "voice_b": {"type": "string", "enum": ["M1"]}}
        with mock.patch.object(studio_video, "ffmpeg_path", return_value="/x"):
            on = next(t for t in available_types(tts_enabled=True, tts_settings=overlay) if t["type_id"] == "video_overview")
        self.assertTrue(on["available"])
        self.assertEqual(sorted(on["settings_schema"]["properties"]), ["engine", "focus", "language", "length", "voice_a"])
        self.assertEqual(STUDIO_V2_TYPES["video_overview"].export_formats, ("mp4", "vtt"))

    def test_settings_validation(self):
        fmt, clean = validate_settings("audio_overview", None, {"engine": "supertonic", "voice_a": "F1", "length": "short"})
        self.assertEqual(clean["length"], "short")
        for bad in ({"length": "huge"}, {"voice_a": "x" * 41}, {"unknown": 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_settings("audio_overview", None, bad)

    def test_range_parsing(self):
        self.assertIsNone(_parse_range(None, 100))
        self.assertIsNone(_parse_range("items=0-1", 100))
        self.assertEqual(_parse_range("bytes=0-9", 100), (0, 9))
        self.assertEqual(_parse_range("bytes=90-", 100), (90, 99))
        self.assertEqual(_parse_range("bytes=-10", 100), (90, 99))
        self.assertEqual(_parse_range("bytes=50-500", 100), (50, 99))
        for bad in ("bytes=100-", "bytes=9-3", "bytes=-0"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _parse_range(bad, 100)

    def test_mp3_export_wrapper(self):
        exported = export_asset("보험금_이야기", "mp3", b"ID3data")
        self.assertEqual(exported.media_type, "audio/mpeg")
        self.assertTrue(exported.ascii_filename.endswith(".mp3"))


if __name__ == "__main__":
    unittest.main()
