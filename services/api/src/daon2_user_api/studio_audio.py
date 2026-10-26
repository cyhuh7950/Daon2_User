"""오디오 개요 생성기(WO-F7 F7-03): 소스 → 2화자 스크립트(LLM) → 문장별 합성 → mp3."""

from __future__ import annotations

from typing import Callable, Mapping

from . import studio_validation as V
from .studio_egress import StudioEgressGate, mask_text
from .studio_generators import _REFS, _Base
from .studio_v2_generation import GenerationContext, GenerationResult
from .studio_workspace import StudioError
from .tts_engines import AudioResult, Spoken, TtsClient, TtsConfig, TtsEngine, TtsError, synthesize_dialogue

LENGTHS = {"short": (8, 14, "약 2~3분"), "normal": (14, 30, "약 5분"), "long": (30, 50, "약 8~10분")}
_ERROR_STATUS = {"TTS_ENGINE_UNKNOWN": 409, "TTS_ENGINE_AUTH_FAILED": 502, "TTS_VOICE_UNKNOWN": 409, "TTS_INPUT_INVALID": 502}


class _EgressModel:
    """StudioEgressGate가 읽는 최소 모양(provider_kind, base_url)."""

    def __init__(self, engine: TtsEngine) -> None:
        self.provider_kind = engine.provider_kind
        self.base_url = engine.base_url


class AudioOverviewGenerator(_Base):
    type_id = "audio_overview"
    max_tokens = 6000
    SCHEMA = {"type": "object", "properties": {
        "title": {"type": "string"}, "summary": {"type": "string"},
        "script": {"type": "array", "items": {"type": "object", "properties": {
            "speaker": {"type": "string", "enum": ["A", "B"]}, "text": {"type": "string"},
            "speech": {"type": "string"}, "refs": _REFS}, "required": ["speaker", "text", "refs"]}}},
        "required": ["script"]}

    def __init__(self, reader, llm, config: "TtsConfig | Callable[[str], TtsConfig | None]", *, egress_gate: StudioEgressGate | None = None,  # type: ignore[no-untyped-def]
                 client_factory: Callable[[TtsEngine], TtsClient] = TtsClient, context_chars: int = 24_000) -> None:
        super().__init__(reader, llm, context_chars=context_chars)
        self._config = config
        self._gate = egress_gate
        self._client_factory = client_factory

    def _config_for(self, ctx: GenerationContext) -> TtsConfig:
        """조직(tenant)의 유효 TTS 설정. 정적 설정(시험) 또는 조직별 해석기(운영)를 받는다."""
        config = self._config(ctx.context.tenant_id) if callable(self._config) else self._config
        if config is None:
            raise StudioError("TTS_ENGINE_UNKNOWN", 409)
        return config

    def _engine_and_voices(self, ctx: GenerationContext, config: TtsConfig) -> tuple[TtsEngine, dict[str, str]]:
        try:
            engine = config.resolve(str(ctx.settings.get("engine") or "") or None)
        except TtsError as error:
            raise StudioError(error.code, 409) from None
        voices = dict(engine.voices)
        for speaker, key in (("A", "voice_a"), ("B", "voice_b")):
            chosen = ctx.settings.get(key)
            if chosen:
                if chosen not in engine.voice_choices:
                    raise StudioError("TTS_VOICE_UNKNOWN", 409)
                voices[speaker] = str(chosen)
        return engine, voices

    def _authorize(self, ctx: GenerationContext, engine: TtsEngine, size_bytes: int) -> bool:
        """전송 허용 여부를 판정하고, 정책이 마스킹을 요구하면 True를 돌려준다."""
        if self._gate is None:
            if engine.provider_kind == "external_api":
                raise StudioError("EGRESS_POLICY_UNAVAILABLE", 409)
            return False
        decision = self._gate.authorize(ctx.context, _EgressModel(engine), size_bytes)
        if not decision.allowed:
            raise StudioError(decision.reason, 409)
        return decision.masked

    def generate(self, ctx: GenerationContext) -> GenerationResult:
        config = self._config_for(ctx)
        engine, voices = self._engine_and_voices(ctx, config)
        pack = self._pack(ctx)
        lo, hi, span = LENGTHS.get(str(ctx.settings.get("length", "normal")), LENGTHS["normal"])
        ctx.progress(8, "스크립트 작성")
        data = self._ask(
            ctx, f"소스의 핵심을 두 사람(A=진행자, B=설명자)의 자연스러운 대화 스크립트로 만드세요({span} 분량, script {lo}~{hi}줄). "
                 "각 줄은 speaker(A 또는 B), text(화면 자막용 원문, 400자 이하), refs를 갖습니다. "
                 "text(화면 자막)에는 숫자와 기호를 소스 원문 그대로 씁니다(예: 1,000,000원, 90일). 소리 내어 읽는 형태(백만 원, 구십 일, 퍼센트)는 오직 speech에만 적고, 읽는 형태가 text와 같으면 speech를 생략합니다. "
                 "소스에 없는 사실·숫자를 만들지 마세요. 인사와 마무리를 넣고, 두 화자가 번갈아 말하게 합니다.",
            self.SCHEMA, pack, tokens=self.max_tokens)
        body, warnings, used = V.validate_audio_script(data, pack, max_lines=hi + 10)
        script: list[dict[str, object]] = body["script"]  # type: ignore[assignment]
        spoken = [Spoken(str(line["speaker"]), str(line.get("speech") or line["text"])) for line in script]
        if self._authorize(ctx, engine, sum(len(s.text.encode("utf-8")) for s in spoken)):
            spoken = [Spoken(s.speaker, mask_text(s.text)) for s in spoken]   # 정책이 요구하면 개인 식별 패턴을 가린 채 보낸다
        client = self._client_factory(engine)
        try:
            if not client.health():
                raise StudioError("TTS_ENGINE_UNREACHABLE", 503)
            ctx.progress(20, "음성 합성")

            def step(done: int, total: int) -> None:
                ctx.progress(20 + int(70 * done / total), f"음성 합성 {done}/{total}")
                ctx.cancel_check()
            try:
                audio: AudioResult = synthesize_dialogue(client, engine, spoken, voices=voices,
                                                         max_total_seconds=config.max_total_seconds, progress=step)
            except TtsError as error:
                raise StudioError(error.code, 503 if error.retryable else _ERROR_STATUS.get(error.code, 502)) from None
        finally:
            client.close()
        for line, (start, end) in zip(script, audio.segments):
            line["start_ms"], line["end_ms"] = start, end
        body.update({"duration_ms": audio.duration_ms, "engine": engine.engine_id, "voices": voices})
        result = self._finish(ctx, pack, dict(body), warnings, used)
        generated_with = {**dict(result.generated_with), "tts_engine": engine.engine_id, "tts_voices": voices}
        return GenerationResult(content=result.content, warnings=result.warnings, generated_with=generated_with, sources=result.sources,
                                evidence=result.evidence, assets=({"kind": "mp3", "content_type": "audio/mpeg", "content": audio.mp3,
                                                                   "duration_ms": audio.duration_ms},))
