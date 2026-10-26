"""TTS 엔진 관리·해석 서비스(WO-F7T). 조직별 등록부(`tts_engines`)와 배포 설정 파일을 합쳐 한 조직의 유효 설정을 만든다.

API 키는 ProviderCredentialCipher로 암호화해 저장하고 호출 직전에만 복호화한다. 목록·응답에는 키가 없다.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

import httpx
from psycopg.types.json import Jsonb  # noqa: F401  (다른 서비스와 같은 import 규칙)

from .cloud_storage import CloudAccessContext, CloudDatabaseError
from .knowledge_connector_service import ConnectorError, validate_endpoint
from .provider_credentials import EncryptedCredential, ProviderCredentialCipher
from .tts_engines import TtsClient, TtsConfig, TtsEngine, TtsError

_PROVIDER_CODE = "CUSTOM"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_VOICE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_ID = re.compile(r"^te-[0-9a-f]{32}$")
_KINDS = frozenset({"external_api", "server_internal", "local", "local_runtime"})
_LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
DEFAULT_MAX_TOTAL_SECONDS = 1800.0

_COLUMNS = ("engine_id,slug,label,base_url,provider_kind,language,timeout_seconds,voice_a,voice_b,voice_choices,status,last_checked_at,error_code,"
            "is_default,version,credential_ciphertext IS NOT NULL")
_SECRET_COLUMNS = "credential_ciphertext,credential_nonce,credential_version,encryption_key_version"


class TtsEngineError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class TtsAdminContext:
    tenant_id: str
    actor_id: str
    trace_id: str = "tts-engine"


def _view(row: Sequence[Any]) -> dict[str, Any]:
    return {"engine_id": row[0], "slug": row[1], "label": row[2], "base_url": row[3], "provider_kind": row[4], "language": row[5],
            "timeout_seconds": int(row[6]), "voices": {"A": row[7], "B": row[8]}, "voice_choices": list(row[9] or []), "status": row[10],
            "last_checked_at": row[11].isoformat() if isinstance(row[11], datetime) else None, "error_code": row[12],
            "is_default": bool(row[13]), "version": int(row[14]), "has_credential": bool(row[15]), "source": "settings"}


def _engine_view(engine: TtsEngine, *, default: bool) -> dict[str, Any]:
    """배포 설정 엔진(읽기 전용). 키는 보내지 않는다."""
    return {"engine_id": None, "slug": engine.engine_id, "label": engine.label, "base_url": engine.base_url, "provider_kind": engine.provider_kind,
            "language": engine.language, "timeout_seconds": int(engine.timeout_seconds), "voices": dict(engine.voices),
            "voice_choices": list(engine.voice_choices), "status": "deployment", "last_checked_at": None, "error_code": None,
            "is_default": default, "version": 0, "has_credential": bool(engine.api_key), "source": "deployment"}


def _validate_voice(value: Any) -> str:
    if not isinstance(value, str) or not _VOICE.fullmatch(value):
        raise TtsEngineError("TTS_ENGINE_VOICE_INVALID")
    return value


def _validate_choices(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)) or len(values) > 64:
        raise TtsEngineError("TTS_ENGINE_VOICE_INVALID")
    return list(dict.fromkeys(_validate_voice(v) for v in values))


class TtsEngineService:
    def __init__(self, cloud_store, cipher: ProviderCredentialCipher, *, file_config: TtsConfig | None = None,  # type: ignore[no-untyped-def]
                 allow_private: bool = False, cache_seconds: float = 15.0, clock: Callable[[], float] = time.monotonic,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._store = cloud_store
        self._cipher = cipher
        self._file = file_config
        self._allow_private = allow_private
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._transport = transport
        self._cache: dict[str, tuple[float, TtsConfig | None]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _scope(context: TtsAdminContext, capability: str) -> CloudAccessContext:
        return CloudAccessContext(context.tenant_id, "tts-engines", context.actor_id, capability)

    def _invalidate(self, tenant_id: str) -> None:
        with self._lock:
            self._cache.pop(tenant_id, None)

    # ------------------------------------------------------------ 해석(생성기·화면 선택지)
    def for_tenant(self, tenant_id: str) -> TtsConfig | None:
        """한 조직의 유효 TTS 설정(화면 등록 엔진 + 배포 설정 엔진). 엔진이 없으면 None."""
        now = self._clock()
        with self._lock:
            hit = self._cache.get(tenant_id)
            if hit is not None and now - hit[0] < self._cache_seconds:
                return hit[1]
        config = self._build(tenant_id)
        with self._lock:
            self._cache[tenant_id] = (now, config)
        return config

    def _build(self, tenant_id: str) -> TtsConfig | None:
        engines: dict[str, TtsEngine] = dict(self._file.engines) if self._file else {}
        default = self._file.default if self._file else None
        total = self._file.max_total_seconds if self._file else DEFAULT_MAX_TOTAL_SECONDS
        try:
            rows = self._read(TtsAdminContext(tenant_id, "tts-resolver"), secrets_too=True)
        except Exception:  # noqa: BLE001 — DB 장애가 생성 화면 전체를 막지 않게 배포 설정만으로 동작한다
            rows = []
        chosen_default: str | None = None
        for row in rows:
            view = _view(row[:16])
            if view["status"] == "disabled":
                engines.pop(view["slug"], None)
                continue
            try:
                validate_endpoint(view["base_url"], allow_private=self._allow_private)
                key = self._decrypt(view["engine_id"], row[16:20]) if row[16] is not None else ""
            except (ConnectorError, TtsEngineError):
                engines.pop(view["slug"], None)
                continue
            choices = tuple(dict.fromkeys([*view["voice_choices"], view["voices"]["A"], view["voices"]["B"]]))
            engines[view["slug"]] = TtsEngine(view["slug"], view["label"], view["base_url"].rstrip("/"), key, view["provider_kind"], view["language"],
                                              float(view["timeout_seconds"]), dict(view["voices"]), choices, source="settings")
            if view["is_default"]:
                chosen_default = view["slug"]
        if not engines:
            return None
        if chosen_default in engines:
            default = chosen_default
        if default not in engines:
            default = next(iter(engines))
        return TtsConfig(engines, default, total)

    def _decrypt(self, engine_id: str, secret: Sequence[Any]) -> str:
        ciphertext, nonce, credential_version, key_version = secret
        sealed = EncryptedCredential(bytes(ciphertext), bytes(nonce), int(key_version), int(credential_version), 1)
        try:
            return self._cipher.decrypt(engine_id, _PROVIDER_CODE, int(credential_version), sealed).decode("utf-8")
        except Exception:
            raise TtsEngineError("TTS_ENGINE_CREDENTIAL_UNAVAILABLE", 503) from None

    def _read(self, context: TtsAdminContext, *, secrets_too: bool = False, engine_id: str | None = None) -> list[Sequence[Any]]:
        columns = _COLUMNS + (f",{_SECRET_COLUMNS}" if secrets_too else "")
        sql = f"SELECT {columns} FROM tts_engines WHERE tenant_id=%s"
        params: list[Any] = [context.tenant_id]
        if engine_id is not None:
            sql += " AND engine_id=%s"
            params.append(engine_id)
        with self._store._transaction(self._scope(context, "tts.read")) as connection:
            return connection.execute(sql + " ORDER BY created_at,engine_id", params).fetchall()

    # ------------------------------------------------------------ 관리
    def list(self, context: TtsAdminContext) -> list[dict[str, Any]]:
        items = [_view(r) for r in self._read(context)]
        slugs = {i["slug"] for i in items}
        if self._file:
            has_default = any(i["is_default"] for i in items)
            for engine in self._file.engines.values():
                if engine.engine_id not in slugs:   # 같은 slug를 화면에서 등록했으면 화면 등록이 이긴다
                    items.append(_engine_view(engine, default=not has_default and engine.engine_id == self._file.default))
        return items

    def get(self, context: TtsAdminContext, engine_id: str) -> dict[str, Any]:
        rows = self._read(context, engine_id=engine_id)
        if not rows:
            raise TtsEngineError("TTS_ENGINE_NOT_FOUND", 404)
        return _view(rows[0])

    def register(self, context: TtsAdminContext, spec: Mapping[str, Any]) -> dict[str, Any]:
        slug = str(spec.get("slug", ""))
        if not _SLUG.fullmatch(slug):
            raise TtsEngineError("TTS_ENGINE_SLUG_INVALID")
        label = str(spec.get("label", "")).strip()
        if not 1 <= len(label) <= 60:
            raise TtsEngineError("TTS_ENGINE_LABEL_INVALID")
        base_url = self._endpoint(spec.get("base_url"))
        kind = str(spec.get("provider_kind", "external_api"))
        if kind not in _KINDS:
            raise TtsEngineError("TTS_ENGINE_KIND_INVALID")
        language = str(spec.get("language", "ko"))
        if not _LANGUAGE.fullmatch(language):
            raise TtsEngineError("TTS_ENGINE_LANGUAGE_INVALID")
        timeout = self._timeout(spec.get("timeout_seconds", 120))
        voices = spec.get("voices")
        if not isinstance(voices, Mapping) or set(voices) != {"A", "B"}:
            raise TtsEngineError("TTS_ENGINE_VOICE_INVALID")
        voice_a, voice_b = _validate_voice(voices["A"]), _validate_voice(voices["B"])
        choices = list(dict.fromkeys([*_validate_choices(spec.get("voice_choices", [])), voice_a, voice_b]))[:64]
        api_key = spec.get("api_key")
        engine_id = "te-" + secrets.token_hex(16)
        sealed = self._seal(engine_id, api_key, 1) if api_key else None
        try:
            with self._store._transaction(self._scope(context, "tts.write")) as connection:
                first = connection.execute("SELECT count(*) FROM tts_engines WHERE tenant_id=%s", (context.tenant_id,)).fetchone()[0] == 0
                row = connection.execute(
                    "INSERT INTO tts_engines(tenant_id,engine_id,slug,label,base_url,provider_kind,language,timeout_seconds,voice_a,voice_b,voice_choices,"
                    "credential_ciphertext,credential_nonce,credential_version,encryption_key_version,is_default,created_by) "
                    f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {_COLUMNS}",
                    (context.tenant_id, engine_id, slug, label, base_url, kind, language, timeout, voice_a, voice_b, choices,
                     None if sealed is None else sealed.ciphertext, None if sealed is None else sealed.nonce, 1 if sealed else 0,
                     None if sealed is None else sealed.encryption_key_version, first, context.actor_id)).fetchone()
        except CloudDatabaseError as error:
            if error.code == "DATABASE_CONSTRAINT_VIOLATION":   # 입력 검증을 통과한 뒤의 제약 위반은 (조직, slug) 중복이다
                raise TtsEngineError("TTS_ENGINE_SLUG_EXISTS", 409) from None
            raise
        self._invalidate(context.tenant_id)
        return _view(row)

    def update(self, context: TtsAdminContext, engine_id: str, patch: Mapping[str, Any], expected_version: int) -> dict[str, Any]:
        """부분 수정. 주소·키가 바뀌면 다시 확인해야 하므로 상태를 `unverified`로 되돌린다."""
        current = self.get(context, engine_id)
        columns: dict[str, Any] = {}
        reconnect = False
        if "label" in patch:
            label = str(patch["label"]).strip()
            if not 1 <= len(label) <= 60:
                raise TtsEngineError("TTS_ENGINE_LABEL_INVALID")
            columns["label"] = label
        if "base_url" in patch:
            columns["base_url"] = self._endpoint(patch["base_url"])
            reconnect = True
        if "provider_kind" in patch:
            if patch["provider_kind"] not in _KINDS:
                raise TtsEngineError("TTS_ENGINE_KIND_INVALID")
            columns["provider_kind"] = patch["provider_kind"]
        if "timeout_seconds" in patch:
            columns["timeout_seconds"] = self._timeout(patch["timeout_seconds"])
        voice_a, voice_b = current["voices"]["A"], current["voices"]["B"]
        if "voices" in patch:
            voices = patch["voices"]
            if not isinstance(voices, Mapping) or set(voices) != {"A", "B"}:
                raise TtsEngineError("TTS_ENGINE_VOICE_INVALID")
            voice_a, voice_b = _validate_voice(voices["A"]), _validate_voice(voices["B"])
            columns["voice_a"], columns["voice_b"] = voice_a, voice_b
        if "voice_choices" in patch or "voices" in patch:
            base = _validate_choices(patch["voice_choices"]) if "voice_choices" in patch else current["voice_choices"]
            columns["voice_choices"] = list(dict.fromkeys([*base, voice_a, voice_b]))[:64]
        if patch.get("api_key"):
            version = self._next_credential_version(context, engine_id)
            sealed = self._seal(engine_id, patch["api_key"], version)
            columns.update(credential_ciphertext=sealed.ciphertext, credential_nonce=sealed.nonce, credential_version=version,
                           encryption_key_version=sealed.encryption_key_version)
            reconnect = True
        enabled = patch.get("enabled")
        if enabled not in (None, True, False):
            raise TtsEngineError("TTS_ENGINE_INPUT_INVALID")
        make_default = patch.get("is_default") is True
        if "is_default" in patch and patch["is_default"] not in (True, False):
            raise TtsEngineError("TTS_ENGINE_INPUT_INVALID")
        if enabled is False:
            columns["status"], columns["is_default"] = "disabled", False
            make_default = False
        elif current["status"] == "disabled" and enabled is True:
            columns["status"], columns["error_code"] = "unverified", None
        elif reconnect and current["status"] != "disabled":
            columns["status"], columns["error_code"] = "unverified", None
        if make_default and current["status"] == "disabled" and enabled is not True:
            raise TtsEngineError("TTS_ENGINE_DISABLED", 409)
        if patch.get("is_default") is False and "is_default" not in columns:
            columns["is_default"] = False
        if not columns and not make_default:
            raise TtsEngineError("TTS_ENGINE_INPUT_INVALID")
        if make_default:
            columns["is_default"] = True
        assignments = ",".join(f"{name}=%s" for name in columns)
        with self._store._transaction(self._scope(context, "tts.write")) as connection:
            if make_default:   # 부분 유일 인덱스: 기존 기본을 먼저 끈다
                connection.execute("UPDATE tts_engines SET is_default=false WHERE tenant_id=%s AND is_default AND engine_id<>%s", (context.tenant_id, engine_id))
            row = connection.execute(
                f"UPDATE tts_engines SET {assignments}{',' if assignments else ''}version=version+1,updated_at=now() "
                f"WHERE tenant_id=%s AND engine_id=%s AND version=%s RETURNING {_COLUMNS}",
                (*columns.values(), context.tenant_id, engine_id, expected_version)).fetchone()
            if row is None:
                raise TtsEngineError("TTS_ENGINE_VERSION_CONFLICT", 409)
        self._invalidate(context.tenant_id)
        return _view(row)

    def disconnect(self, context: TtsAdminContext, engine_id: str) -> None:
        with self._store._transaction(self._scope(context, "tts.write")) as connection:
            row = connection.execute("DELETE FROM tts_engines WHERE tenant_id=%s AND engine_id=%s RETURNING engine_id, is_default", (context.tenant_id, engine_id)).fetchone()
            if row is None:
                raise TtsEngineError("TTS_ENGINE_NOT_FOUND", 404)
            if row[1]:   # 기본 엔진을 지우면 남은 첫 엔진을 기본으로 올린다
                connection.execute(
                    "UPDATE tts_engines SET is_default=true,version=version+1 WHERE tenant_id=%s AND engine_id=(SELECT engine_id FROM tts_engines "
                    "WHERE tenant_id=%s AND status<>'disabled' ORDER BY created_at,engine_id LIMIT 1)", (context.tenant_id, context.tenant_id))
        self._invalidate(context.tenant_id)

    def verify(self, context: TtsAdminContext, engine_id: str) -> dict[str, Any]:
        """`/health` + `/v1/voices`. 성공하면 엔진이 알려 준 보이스를 선택지에 채운다. '연결됨'이지 '합성 성공'이 아니다."""
        rows = self._read(context, secrets_too=True, engine_id=engine_id)
        if not rows:
            raise TtsEngineError("TTS_ENGINE_NOT_FOUND", 404)
        row = rows[0]
        view = _view(row[:16])
        status, error, found = "verified", None, []
        try:
            validate_endpoint(view["base_url"], allow_private=self._allow_private)
            key = self._decrypt(engine_id, row[16:20]) if row[16] is not None else ""
            engine = TtsEngine(view["slug"], view["label"], view["base_url"].rstrip("/"), key, view["provider_kind"], view["language"],
                               float(view["timeout_seconds"]), dict(view["voices"]), tuple(view["voice_choices"]), source="settings")
            client = TtsClient(engine, transport=self._transport)
            try:
                if not client.health():
                    status, error = "failed", "TTS_ENGINE_UNREACHABLE"
                else:
                    found = client.voices()
                    wanted = {view["voices"]["A"], view["voices"]["B"]}
                    if found and not wanted <= set(found):
                        status, error = "failed", "TTS_VOICE_UNKNOWN"
            finally:
                client.close()
        except TtsError as exc:
            status, error = "failed", exc.code
        except ConnectorError as exc:
            status, error = "failed", exc.code
        except TtsEngineError as exc:
            status, error = "failed", exc.code
        choices = list(dict.fromkeys([*found, view["voices"]["A"], view["voices"]["B"]]))[:64] if found else view["voice_choices"]
        with self._store._transaction(self._scope(context, "tts.write")) as connection:
            updated = connection.execute(
                f"UPDATE tts_engines SET status=%s,error_code=%s,voice_choices=%s,last_checked_at=now(),updated_at=now() "
                f"WHERE tenant_id=%s AND engine_id=%s AND status<>'disabled' RETURNING {_COLUMNS}", (status, error, choices, context.tenant_id, engine_id)).fetchone()
        self._invalidate(context.tenant_id)
        return _view(updated) if updated is not None else view

    # ------------------------------------------------------------ 보조
    def _endpoint(self, value: Any) -> str:
        if not isinstance(value, str):
            raise TtsEngineError("TTS_ENGINE_ENDPOINT_INVALID")
        try:
            return validate_endpoint(value.strip().rstrip("/"), allow_private=self._allow_private)
        except ConnectorError as error:
            raise TtsEngineError("TTS_ENGINE_ENDPOINT_PRIVATE_DENIED" if error.code == "CONNECTOR_ENDPOINT_PRIVATE_DENIED" else "TTS_ENGINE_ENDPOINT_INVALID",
                                 error.status) from None

    @staticmethod
    def _timeout(value: Any) -> int:
        if type(value) is not int or not 5 <= value <= 600:
            raise TtsEngineError("TTS_ENGINE_TIMEOUT_INVALID")
        return value

    def _seal(self, engine_id: str, api_key: Any, version: int):  # type: ignore[no-untyped-def]
        if not isinstance(api_key, str) or not 8 <= len(api_key) <= 4096:
            raise TtsEngineError("TTS_ENGINE_CREDENTIAL_INVALID")
        return self._cipher.encrypt(engine_id, _PROVIDER_CODE, version, api_key.encode("utf-8"))

    def _next_credential_version(self, context: TtsAdminContext, engine_id: str) -> int:
        with self._store._transaction(self._scope(context, "tts.read")) as connection:
            row = connection.execute("SELECT credential_version FROM tts_engines WHERE tenant_id=%s AND engine_id=%s", (context.tenant_id, engine_id)).fetchone()
        if row is None:
            raise TtsEngineError("TTS_ENGINE_NOT_FOUND", 404)
        return int(row[0]) + 1
