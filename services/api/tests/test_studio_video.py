"""동영상 개요(WO-F7V): 장면 검증·슬라이드 그리기·타임라인·자막·챕터·ffmpeg 합성·생성기."""
from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from daon2_user_api import studio_video as video
from daon2_user_api.studio_context_builder import build_pack
from daon2_user_api.studio_validation import validate_video_scenes
from daon2_user_api.studio_workspace import StudioError
from daon2_user_api.tts_engines import AudioResult, TtsError, load_config
from test_studio_v2_generation import FakeReader, ScriptedLLM, gen_ctx, source
from test_tts_audio import FakeClient, StubGate, config_file

HAS_FFMPEG = video.ffmpeg_path() is not None

SCENES = {"title": "보험금 이야기", "scenes": [
    {"layout": "title", "title": "보험금 지급 안내", "bullets": [], "narration": "안녕하세요. 보험금 지급 안내를 시작합니다.", "refs": []},
    {"layout": "bullets", "title": "지급 기한", "bullets": ["접수일부터 3일 이내", "한도 1,000,000원"],
     "narration": "보험금은 청구서류를 접수한 날부터 3일 이내에 지급합니다. 한도는 사고당 1,000,000원입니다.",
     "speech": "보험금은 청구서류를 접수한 날부터 삼 일 이내에 지급합니다. 한도는 사고당 백만 원입니다.", "refs": ["S1"]},
    {"layout": "two_column", "title": "면책 기간", "bullets": ["계약일부터 90일", "즉시 통지"], "narration": "면책 기간은 계약일부터 90일입니다.", "refs": ["S2"]},
    {"layout": "table", "title": "요약", "bullets": [], "table": {"columns": ["항목", "내용"], "rows": [["기한", "3일"], ["면책", "90일"]]},
     "narration": "정리하면 기한은 3일, 면책은 90일입니다.", "refs": ["S1", "S2"]}]}


def pack():
    return build_pack((source(),), budget_chars=10_000)


class SentenceTests(unittest.TestCase):
    def test_split_on_punctuation_and_limit(self):
        self.assertEqual(video.split_sentences("첫 문장입니다. 둘째 문장입니까? 셋째!"), ["첫 문장입니다.", "둘째 문장입니까?", "셋째!"])
        long = " ".join(["단어"] * 150)
        parts = video.split_sentences(long, limit=50)
        self.assertTrue(all(len(p) <= 50 for p in parts))
        self.assertEqual(" ".join(parts), long)
        self.assertEqual(video.split_sentences("   "), [])


class ValidationTests(unittest.TestCase):
    def test_valid_scenes_keep_narration_and_speech(self):
        body, warnings, used = validate_video_scenes(SCENES, pack())
        self.assertEqual([s["layout"] for s in body["scenes"]], ["title", "bullets", "two_column", "table"])
        self.assertNotIn("notes", body["scenes"][0])
        self.assertIn("speech", body["scenes"][1])
        self.assertNotIn("speech", body["scenes"][0])
        self.assertIn("S1", used)

    def test_fallback_narration_and_minimum_scenes_and_anchor_check(self):
        data = {"title": "t", "scenes": [{**SCENES["scenes"][0]}, {**SCENES["scenes"][1], "narration": ""}, {**SCENES["scenes"][2], "narration": "지급은 77일이다."}]}
        body, warnings, _ = validate_video_scenes(data, pack())
        codes = [w["code"] for w in warnings]
        self.assertIn("NARRATION_FALLBACK", codes)
        self.assertIn("ANCHOR_MISMATCH", codes)
        self.assertTrue(body["scenes"][1]["narration"].startswith("지급 기한"))
        with self.assertRaises(StudioError):
            validate_video_scenes({"title": "t", "scenes": SCENES["scenes"][:2]}, pack())
        with self.assertRaises(StudioError):
            validate_video_scenes({"title": "t", "scenes": [{**s, "refs": ["S9"]} for s in SCENES["scenes"]]}, pack())


class RenderTests(unittest.TestCase):
    def test_every_layout_is_1280x720_and_flags_overflow(self):
        for index, scene in enumerate(SCENES["scenes"]):
            png, over = video.render_scene_png(scene, index + 1, 4)
            self.assertEqual(Image.open(io.BytesIO(png)).size, (1280, 720))
            self.assertEqual(over, [])
        crowded = {"layout": "bullets", "title": "가" * 90, "bullets": ["나" * 200] * 6, "refs": []}
        png, over = video.render_scene_png(crowded, 1, 1)
        self.assertIn("title", over)
        self.assertTrue(any(p.startswith("bullets") for p in over))
        self.assertEqual(Image.open(io.BytesIO(png)).size, (1280, 720))


class TimelineTests(unittest.TestCase):
    def audio(self, seconds, sentences):
        rate = 22050
        n = int(rate * seconds)
        step = n // sentences
        segs = tuple((round(i * step * 1000 / rate), round((i + 1) * step * 1000 / rate)) for i in range(sentences))
        return AudioResult(b"", round(seconds * 1000), segs, b"\x01\x00" * n, rate)

    def test_timeline_gaps_spans_and_cues(self):
        a, b = self.audio(1.0, 2), self.audio(2.0, 1)
        pcm, spans, cues = video.assemble_timeline([a, b], 22050)
        self.assertEqual(spans[0], {"start_ms": 0, "end_ms": 1450})        # 1.0초 + 장면 사이 450ms
        self.assertEqual(spans[1], {"start_ms": 1450, "end_ms": 4050})     # 2.0초 + 끝 600ms
        self.assertEqual(len(pcm) // 2, 22050 * 3 + 22050 * 450 // 1000 + 22050 * 600 // 1000)
        self.assertEqual(cues[1][0][0], 1450)
        shown = video.build_cues("첫째입니다. 둘째입니다.", None, cues[0], spans[0])
        self.assertEqual([c["text"] for c in shown], ["첫째입니다.", "둘째입니다."])
        merged = video.build_cues("하나. 둘. 셋.", None, cues[0], spans[0])        # 문장 수가 다르면 장면 전체 한 줄
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]["start_ms"], merged[0]["end_ms"]), (0, 1450))

    def test_vtt_and_chapter_metadata(self):
        body = {"scenes": [{"cues": [{"start_ms": 0, "end_ms": 1500, "text": "안녕 & <b> --> 끝"}]}, {"cues": [{"start_ms": 3_661_005, "end_ms": 3_662_000, "text": "둘"}]}]}
        vtt = video.render_vtt(body).decode("utf-8")
        self.assertTrue(vtt.startswith("WEBVTT\n"))
        self.assertIn("00:00:00.000 --> 00:00:01.500", vtt)
        self.assertIn("01:01:01.005 --> 01:01:02.000", vtt)
        self.assertIn("안녕 &amp; &lt;b> → 끝", vtt)
        meta = video.chapter_metadata([{"title": "a=b;c#d\\e", "start_ms": 0, "end_ms": 1000}])
        self.assertIn("title=a\\=b\\;c\\#d\\\\e", meta)
        self.assertIn("START=0", meta)
        self.assertTrue(meta.startswith(";FFMETADATA1"))


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg가 없다")
class ComposeTests(unittest.TestCase):
    def test_real_ffmpeg_produces_h264_aac_with_chapters(self):
        scenes = SCENES["scenes"][:3]
        pngs = [video.render_scene_png(s, i + 1, 3)[0] for i, s in enumerate(scenes)]
        rate = 22050
        parts = [TimelineTests().audio(1.0, 1), TimelineTests().audio(1.5, 1), TimelineTests().audio(1.0, 1)]
        pcm, spans, _ = video.assemble_timeline(parts, rate)
        chapters = [{"title": s["title"], "start_ms": sp["start_ms"], "end_ms": sp["end_ms"]} for s, sp in zip(scenes, spans)]
        mp4 = video.compose_mp4(pngs, spans, video._wav_bytes(pcm, rate), chapters)
        self.assertEqual(mp4[4:8], b"ftyp")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.mp4"
            path.write_bytes(mp4)
            info = subprocess.run([video.ffmpeg_path(), "-hide_banner", "-i", str(path)], capture_output=True).stderr.decode("utf-8", "replace")
        self.assertIn("Video: h264", info)
        self.assertIn("1280x720", info)
        self.assertIn("Audio: aac", info)
        self.assertEqual(info.count("Chapter #"), 3)
        for title in ("보험금 지급 안내", "지급 기한", "면책 기간"):
            self.assertIn(title, info)
        self.assertIn("Duration: 00:00:0", info)

    def test_failure_modes(self):
        class Done:
            returncode = 1
        with self.assertRaises(StudioError) as caught:
            video.compose_mp4([b"x"], [{"start_ms": 0, "end_ms": 1000}], b"", [], runner=lambda *a, **k: Done())
        self.assertEqual(caught.exception.code, "VIDEO_ENCODE_FAILED")

        def timeout(*a, **k):
            raise subprocess.TimeoutExpired("ffmpeg", 1)
        with self.assertRaises(StudioError) as caught:
            video.compose_mp4([b"x"], [{"start_ms": 0, "end_ms": 1000}], b"", [], runner=timeout)
        self.assertEqual(caught.exception.code, "VIDEO_ENCODE_FAILED")
        from unittest import mock
        with mock.patch.object(video, "ffmpeg_path", return_value=None), self.assertRaises(StudioError) as caught:
            video.compose_mp4([b"x"], [{"start_ms": 0, "end_ms": 1000}], b"", [], runner=lambda *a, **k: Done())
        self.assertEqual(caught.exception.code, "VIDEO_ENCODER_UNAVAILABLE")


class GeneratorTests(unittest.TestCase):
    def make(self, *, gate=None, client=None, data=None, engine_over=None, composer=None):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(config_file(directory, **(engine_over or {})))
        self.composed = {}

        def fake_composer(pngs, spans, wav, chapters):
            self.composed.update(pngs=pngs, spans=spans, wav=wav, chapters=chapters)
            return b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
        client = client or FakeClient(seconds=0.4)
        generator = video.VideoOverviewGenerator(FakeReader(), ScriptedLLM(data or SCENES), config, egress_gate=gate,
                                                 client_factory=lambda engine: client, composer=composer or fake_composer)
        return generator, client

    def test_generates_scenes_chapters_cues_and_mp4_asset(self):
        generator, client = self.make()
        result = generator.generate(gen_ctx("video_overview", {"voice_a": "F2"})[0])
        body = result.content["body"]
        self.assertEqual(len(body["scenes"]), 4)
        self.assertEqual(len(body["chapters"]), 4)
        self.assertEqual(body["chapters"][1]["title"], "지급 기한")
        self.assertEqual(body["voice"], "F2")
        self.assertTrue(all(c[1] == "F2" for c in client.calls))
        # speech가 있는 장면은 읽는 형태로 합성하고, 자막은 원문 문장을 쓴다
        self.assertTrue(any("삼 일" in call[0] for call in client.calls))
        self.assertFalse(any("3일 이내에 지급합니다" in call[0] for call in client.calls))
        scene = body["scenes"][1]
        self.assertEqual(scene["start_ms"], body["chapters"][1]["start_ms"])
        self.assertEqual([c["text"] for c in scene["cues"]][0], "보험금은 청구서류를 접수한 날부터 3일 이내에 지급합니다.")
        self.assertEqual(len(self.composed["pngs"]), 4)
        self.assertEqual(self.composed["spans"][-1]["end_ms"], body["duration_ms"])
        asset = result.assets[0]
        self.assertEqual((asset["kind"], asset["content_type"]), ("mp4", "video/mp4"))
        self.assertEqual(result.generated_with["tts_engine"], "supertonic")
        self.assertTrue(client.closed)
        vtt = video.render_vtt(body).decode("utf-8")
        self.assertIn("보험금은 청구서류를 접수한 날부터 3일 이내에 지급합니다.", vtt)

    def test_policy_gate_masking_and_errors(self):
        gate = StubGate(False)
        generator, client = self.make(gate=gate, engine_over={"provider_kind": "external_api"})
        with self.assertRaises(StudioError) as caught:
            generator.generate(gen_ctx("video_overview")[0])
        self.assertEqual(caught.exception.code, "EGRESS_DESTINATION_DENIED")
        self.assertEqual(client.calls, [])
        pii = {**SCENES, "scenes": [{**s, "speech": "연락처 010-1234-5678"} if i == 0 else s for i, s in enumerate(SCENES["scenes"])]}
        generator, client = self.make(gate=StubGate(True, masked=True), data=pii)
        generator.generate(gen_ctx("video_overview")[0])
        self.assertEqual(client.calls[0][0], "연락처 [전화번호]")
        generator, _ = self.make()
        with self.assertRaises(StudioError) as caught:
            generator.generate(gen_ctx("video_overview", {"voice_a": "M9"})[0])
        self.assertEqual(caught.exception.code, "TTS_VOICE_UNKNOWN")

        class Down(FakeClient):
            def health(self):
                return False
        generator, _ = self.make(client=Down())
        with self.assertRaises(StudioError) as caught:
            generator.generate(gen_ctx("video_overview")[0])
        self.assertEqual(caught.exception.code, "TTS_ENGINE_UNREACHABLE")

        class Broken(FakeClient):
            def synthesize(self, *a):
                raise TtsError("TTS_ENGINE_AUTH_FAILED")
        generator, _ = self.make(client=Broken())
        with self.assertRaises(StudioError) as caught:
            generator.generate(gen_ctx("video_overview")[0])
        self.assertEqual(caught.exception.code, "TTS_ENGINE_AUTH_FAILED")

    def test_no_encoder_blocks_generation(self):
        from unittest import mock
        generator, client = self.make()
        with mock.patch.object(video, "ffmpeg_path", return_value=None):
            with self.assertRaises(StudioError) as caught:
                generator.generate(gen_ctx("video_overview")[0])
        self.assertEqual(caught.exception.code, "VIDEO_ENCODER_UNAVAILABLE")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
