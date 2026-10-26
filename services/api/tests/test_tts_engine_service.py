"""TTS 엔진 관리·해석 서비스(WO-F7T): 검증, 암호화, 조직별 병합·기본 엔진, 캐시, 연결 확인, 부분 수정. DB는 가짜 저장소로 대체한다(실DB는 IT)."""
from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx

from daon2_user_api.provider_credentials import ProviderCredentialCipher
from daon2_user_api.tts_engine_service import TtsAdminContext, TtsEngineError, TtsEngineService
from daon2_user_api.tts_engines import TtsConfig, TtsEngine

CTX = TtsAdminContext("tenant-1", "admin-1", "trace-1")
ENGINE_ID = "te-" + "a" * 32
OTHER_ID = "te-" + "b" * 32
KEY = "secret-key-for-engine-1"
NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeStore:
    """SQL 문장 앞부분으로 응답을 고르는 가짜 저장소. 실행된 문장·매개변수를 기록한다."""

    def __init__(self):
        self.statements = []
        self.scopes = []
        self.responses = {}   # 문장 접두어 -> rows | callable(sql, params) -> rows

    @contextmanager
    def _transaction(self, scope):
        self.scopes.append((scope.workspace_id, scope.capability))
        yield self

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), tuple(params)))
        for prefix, response in self.responses.items():
            if " ".join(sql.split()).startswith(prefix):
                rows = response(sql, params) if callable(response) else response
                return FakeCursor(rows)
        return FakeCursor([])

    def last(self, prefix):
        return [s for s in self.statements if s[0].startswith(prefix)][-1]


def view_row(engine_id=ENGINE_ID, slug="supertonic", label="Supertonic", base_url="https://tts.example.com", kind="external_api", status="unverified",
             default=False, version=1, voices=("F1", "M1"), choices=("F1", "M1"), credential=True, error=None):
    return (engine_id, slug, label, base_url, kind, "ko", 120, voices[0], voices[1], list(choices), status, None, error, default, version, credential)


def make_service(store=None, *, file_config=None, allow_private=False, clock=None, transport=None):
    cipher = ProviderCredentialCipher(os.urandom(32), encryption_key_version=1)
    return TtsEngineService(store or FakeStore(), cipher, file_config=file_config, allow_private=allow_private,
                            clock=clock or (lambda: 0.0), transport=transport), cipher


def file_config():
    engine = TtsEngine("deploy", "배포 엔진", "https://deploy.example.com", "file-key", "external_api", "ko", 120.0, {"A": "F1", "B": "M1"}, ("F1", "M1"))
    return TtsConfig({"deploy": engine}, "deploy", 900.0)


GOOD = {"slug": "supertonic", "label": "Supertonic", "base_url": "https://tts.example.com", "api_key": KEY, "voices": {"A": "F1", "B": "M1"}}


class ValidationTests(unittest.TestCase):
    def test_register_rejects_bad_input_before_touching_the_database(self):
        store = FakeStore()
        service, _ = make_service(store)
        bad = [{"slug": "Bad Slug"}, {"slug": ""}, {"label": " "}, {"label": "x" * 61}, {"base_url": "ftp://tts.example.com"}, {"base_url": "https://user:pw@tts.example.com"},
               {"base_url": "https://tts.example.com?x=1"}, {"base_url": 5}, {"provider_kind": "weird"}, {"language": "KOREAN"}, {"timeout_seconds": 4},
               {"timeout_seconds": "120"}, {"voices": {"A": "F1"}}, {"voices": {"A": "F1", "B": "bad voice"}}, {"api_key": "short"}, {"voice_choices": ["a b"]}]
        for override in bad:
            with self.subTest(override=override), self.assertRaises(TtsEngineError):
                service.register(CTX, {**GOOD, **override})
        self.assertEqual(store.statements, [])

    def test_private_and_loopback_endpoints_need_the_private_switch(self):
        service, _ = make_service(FakeStore(), allow_private=False)
        for url in ("http://127.0.0.1:8201", "http://10.1.2.3:8201", "http://[::1]:8201"):
            with self.subTest(url=url), self.assertRaises(TtsEngineError) as raised:
                service.register(CTX, {**GOOD, "base_url": url})
            self.assertEqual((raised.exception.code, raised.exception.status), ("TTS_ENGINE_ENDPOINT_PRIVATE_DENIED", 403))
        store = FakeStore()
        store.responses = {"SELECT count": [(0,)], "INSERT": lambda sql, params: [view_row(base_url=params[4])]}
        allowed, _ = make_service(store, allow_private=True)
        self.assertEqual(allowed.register(CTX, {**GOOD, "base_url": "http://127.0.0.1:8201/"})["base_url"], "http://127.0.0.1:8201")


class RegisterTests(unittest.TestCase):
    def test_key_is_sealed_and_never_returned_and_first_engine_becomes_default(self):
        store = FakeStore()
        store.responses = {"SELECT count": [(0,)], "INSERT": lambda sql, params: [view_row(slug=params[2], default=params[15])]}
        service, cipher = make_service(store)
        created = service.register(CTX, GOOD)
        sql, params = store.last("INSERT")
        self.assertNotIn(KEY.encode(), [p for p in params if isinstance(p, bytes)])
        self.assertNotIn(KEY, [p for p in params if isinstance(p, str)])
        self.assertTrue(params[15])   # is_default
        engine_id, ciphertext, nonce = params[1], params[11], params[12]
        self.assertRegex(engine_id, r"^te-[0-9a-f]{32}$")
        from daon2_user_api.provider_credentials import EncryptedCredential
        self.assertEqual(cipher.decrypt(engine_id, "CUSTOM", 1, EncryptedCredential(ciphertext, nonce, 1, 1, 1)).decode(), KEY)
        self.assertEqual(sorted(created), sorted({"engine_id", "slug", "label", "base_url", "provider_kind", "language", "timeout_seconds", "voices", "voice_choices",
                                                  "status", "last_checked_at", "error_code", "is_default", "version", "has_credential", "source"}))
        self.assertNotIn(KEY, str(created))
        self.assertEqual(store.scopes[-1], ("tts-engines", "tts.write"))

    def test_second_engine_is_not_default_and_duplicate_slug_is_a_conflict(self):
        store = FakeStore()
        store.responses = {"SELECT count": [(1,)], "INSERT": lambda sql, params: [view_row(default=params[15])]}
        service, _ = make_service(store)
        self.assertFalse(store.statements and False)
        service.register(CTX, GOOD)
        self.assertFalse(store.last("INSERT")[1][15])

        from daon2_user_api.cloud_storage import CloudDatabaseError

        def boom(sql, params):
            raise CloudDatabaseError("DATABASE_CONSTRAINT_VIOLATION", retryable=False)
        store.responses["INSERT"] = boom
        with self.assertRaises(TtsEngineError) as raised:
            service.register(CTX, GOOD)
        self.assertEqual((raised.exception.code, raised.exception.status), ("TTS_ENGINE_SLUG_EXISTS", 409))


def sealed_row(cipher, *, engine_id=ENGINE_ID, key=KEY, **kwargs):
    sealed = cipher.encrypt(engine_id, "CUSTOM", 1, key.encode())
    return (*view_row(engine_id=engine_id, **kwargs), sealed.ciphertext, sealed.nonce, 1, sealed.encryption_key_version)


class ResolveTests(unittest.TestCase):
    def test_settings_engines_override_deployment_and_pick_the_default(self):
        store = FakeStore()
        service, cipher = make_service(store, file_config=file_config())
        store.responses = {"SELECT": [sealed_row(cipher, slug="deploy", label="화면 등록", default=False, voices=("F2", "M2")),
                                      sealed_row(cipher, engine_id=OTHER_ID, slug="qwen", label="Qwen", default=True, base_url="https://q.example.com", choices=("sohee",), voices=("sohee", "sohee"))]}
        config = service.for_tenant("tenant-1")
        self.assertEqual(sorted(config.engines), ["deploy", "qwen"])
        self.assertEqual(config.default, "qwen")
        self.assertEqual(config.engines["deploy"].label, "화면 등록")        # 같은 slug면 화면 등록이 이긴다
        self.assertEqual(config.engines["deploy"].source, "settings")
        self.assertEqual(config.engines["deploy"].api_key, KEY)             # 복호화되어 호출에 쓰인다
        self.assertEqual(config.engines["deploy"].voices, {"A": "F2", "B": "M2"})
        self.assertEqual(config.max_total_seconds, 900.0)
        self.assertEqual(config.engines["qwen"].base_url, "https://q.example.com")

    def test_without_rows_the_deployment_config_is_used_and_without_both_it_is_disabled(self):
        service, _ = make_service(FakeStore(), file_config=file_config())
        config = service.for_tenant("tenant-1")
        self.assertEqual((list(config.engines), config.default, config.engines["deploy"].source), (["deploy"], "deploy", "deployment"))
        empty, _ = make_service(FakeStore())
        self.assertIsNone(empty.for_tenant("tenant-1"))

    def test_disabled_and_unsafe_rows_are_left_out(self):
        store = FakeStore()
        service, cipher = make_service(store, file_config=file_config())
        store.responses = {"SELECT": [sealed_row(cipher, slug="deploy", status="disabled"),                             # 끄면 배포 엔진도 가려진다
                                      sealed_row(cipher, engine_id=OTHER_ID, slug="evil", base_url="http://127.0.0.1:9999")]}   # 사설 주소는 해석 때도 거부
        self.assertIsNone(service.for_tenant("tenant-1"))

    def test_a_broken_key_drops_only_that_engine_and_database_errors_fall_back_to_the_file(self):
        store = FakeStore()
        service, cipher = make_service(store, file_config=file_config())
        good = sealed_row(cipher, engine_id=OTHER_ID, slug="ok")
        broken = list(sealed_row(cipher, slug="broken"))
        broken[17] = b"x" * 16        # 잘못된 nonce
        store.responses = {"SELECT": [tuple(broken), good]}
        self.assertEqual(sorted(service.for_tenant("tenant-1").engines), ["deploy", "ok"])

        def down(sql, params):
            raise RuntimeError("db down")
        store.responses = {"SELECT": down}
        fresh, _ = make_service(store, file_config=file_config())
        self.assertEqual(list(fresh.for_tenant("tenant-9").engines), ["deploy"])

    def test_results_are_cached_for_fifteen_seconds_and_writes_invalidate(self):
        store = FakeStore()
        now = [0.0]
        service, cipher = make_service(store, file_config=file_config(), clock=lambda: now[0])
        store.responses = {"SELECT": [sealed_row(cipher, slug="a")]}
        service.for_tenant("tenant-1")
        service.for_tenant("tenant-1")
        self.assertEqual(len([s for s in store.statements if s[0].startswith("SELECT")]), 1)
        now[0] = 16.0
        service.for_tenant("tenant-1")
        self.assertEqual(len([s for s in store.statements if s[0].startswith("SELECT")]), 2)
        service._invalidate("tenant-1")
        service.for_tenant("tenant-1")
        self.assertEqual(len([s for s in store.statements if s[0].startswith("SELECT")]), 3)
        service.for_tenant("tenant-2")      # 다른 조직은 따로 캐시한다
        self.assertEqual(len([s for s in store.statements if s[0].startswith("SELECT")]), 4)


class ListTests(unittest.TestCase):
    def test_deployment_engines_are_listed_read_only_without_keys(self):
        store = FakeStore()
        service, _ = make_service(store, file_config=file_config())
        store.responses = {"SELECT": [view_row()]}
        items = service.list(CTX)
        self.assertEqual([(i["slug"], i["source"]) for i in items], [("supertonic", "settings"), ("deploy", "deployment")])
        deploy = items[1]
        self.assertEqual((deploy["engine_id"], deploy["status"], deploy["version"], deploy["has_credential"]), (None, "deployment", 0, True))
        self.assertNotIn("file-key", str(items))
        self.assertTrue(deploy["is_default"])       # 화면 등록 엔진 중 기본이 없으면 배포 기본이 기본이다


def verify_service(transport, row_status="unverified", voices=("F1", "M1")):
    store = FakeStore()
    service, cipher = make_service(store, transport=transport)
    store.responses = {"SELECT": [sealed_row(cipher, voices=voices, choices=voices, status=row_status)],
                       "UPDATE": lambda sql, params: [view_row(status=params[0], error=params[1], choices=tuple(params[2]), version=2, voices=voices)]}
    return service, store


class VerifyTests(unittest.TestCase):
    def handler(self, *, health=200, voices=200, body=None):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(health, json={"ready": True})      # 상태 확인은 인증 없이 호출한다
            self.assertEqual(request.headers.get("authorization"), "Bearer " + KEY)   # 복호화된 키로 보이스 목록을 요청한다
            return httpx.Response(voices, json=body if body is not None else {"voices": [{"id": "F1"}, {"id": "F2"}, {"id": "M1"}, {"name": "M2"}, "X9", {"id": "bad id"}]})
        return handle

    def test_success_fills_voice_choices_from_the_engine(self):
        service, store = verify_service(httpx.MockTransport(self.handler()))
        result = service.verify(CTX, ENGINE_ID)
        status, error, choices = store.last("UPDATE")[1][:3]
        self.assertEqual((status, error), ("verified", None))
        self.assertEqual(choices, ["F1", "F2", "M1", "M2", "X9"])
        self.assertEqual(result["status"], "verified")

    def test_failures_are_recorded_with_a_code(self):
        cases = ((self.handler(health=503), "TTS_ENGINE_UNREACHABLE"), (self.handler(voices=401), "TTS_ENGINE_AUTH_FAILED"),
                 (self.handler(body={"voices": [{"id": "F9"}]}), "TTS_VOICE_UNKNOWN"))
        for handler, code in cases:
            with self.subTest(code=code):
                service, store = verify_service(httpx.MockTransport(handler))
                result = service.verify(CTX, ENGINE_ID)
                self.assertEqual(store.last("UPDATE")[1][:2], ("failed", code))
                self.assertEqual(result["error_code"], code)

    def test_a_missing_voices_endpoint_is_not_a_failure_and_unknown_engine_is_404(self):
        service, store = verify_service(httpx.MockTransport(self.handler(voices=404)))
        service.verify(CTX, ENGINE_ID)
        self.assertEqual(store.last("UPDATE")[1][:2], ("verified", None))
        self.assertEqual(store.last("UPDATE")[1][2], ["F1", "M1"])      # 엔진이 목록을 주지 않으면 기존 선택지를 유지한다
        empty = FakeStore()
        other, _ = make_service(empty)
        with self.assertRaises(TtsEngineError) as raised:
            other.verify(CTX, ENGINE_ID)
        self.assertEqual((raised.exception.code, raised.exception.status), ("TTS_ENGINE_NOT_FOUND", 404))


class UpdateTests(unittest.TestCase):
    def service(self, current=None):
        store = FakeStore()
        service, cipher = make_service(store)
        current = current or view_row(status="verified", default=False)
        store.responses = {"SELECT credential_version": [(1,)], "SELECT": [current],
                           "UPDATE tts_engines SET is_default=false": [],
                           "UPDATE tts_engines SET": lambda sql, params: [view_row(version=2)]}
        return service, store

    def test_address_or_key_changes_require_reverification(self):
        for patch in ({"base_url": "https://other.example.com"}, {"api_key": "another-secret-key"}):
            with self.subTest(patch=list(patch)):
                service, store = self.service()
                service.update(CTX, ENGINE_ID, patch, 1)
                sql, params = store.last("UPDATE tts_engines SET")
                self.assertIn("status=%s", sql)
                self.assertIn("unverified", params)
                self.assertNotIn("another-secret-key", [p for p in params if isinstance(p, str)])
        service, store = self.service()
        service.update(CTX, ENGINE_ID, {"label": "이름만"}, 1)
        self.assertNotIn("status=%s", store.last("UPDATE tts_engines SET")[0])

    def test_disable_enable_and_default_rules(self):
        service, store = self.service()
        service.update(CTX, ENGINE_ID, {"enabled": False}, 1)
        sql, params = store.last("UPDATE tts_engines SET")
        self.assertIn("disabled", params)
        self.assertIn("is_default=%s", sql)
        service, store = self.service(view_row(status="disabled"))
        with self.assertRaises(TtsEngineError) as raised:
            service.update(CTX, ENGINE_ID, {"is_default": True}, 1)
        self.assertEqual(raised.exception.code, "TTS_ENGINE_DISABLED")
        service.update(CTX, ENGINE_ID, {"enabled": True, "is_default": True}, 1)
        self.assertIn("unverified", store.last("UPDATE tts_engines SET")[1])
        service, store = self.service()
        service.update(CTX, ENGINE_ID, {"is_default": True}, 1)
        order = [s[0] for s in store.statements if s[0].startswith("UPDATE")]
        self.assertTrue(order[0].startswith("UPDATE tts_engines SET is_default=false"))   # 기존 기본을 먼저 끈다
        self.assertTrue(order[1].startswith("UPDATE tts_engines SET is_default=%s"))

    def test_input_validation_and_version_conflict(self):
        service, store = self.service()
        for patch in ({}, {"enabled": "yes"}, {"is_default": "no"}, {"voices": {"A": "F1"}}, {"timeout_seconds": 3}, {"provider_kind": "x"}, {"label": ""}):
            with self.subTest(patch=patch), self.assertRaises(TtsEngineError):
                service.update(CTX, ENGINE_ID, patch, 1)
        store.responses["UPDATE tts_engines SET"] = []
        with self.assertRaises(TtsEngineError) as raised:
            service.update(CTX, ENGINE_ID, {"label": "새 이름"}, 1)
        self.assertEqual((raised.exception.code, raised.exception.status), ("TTS_ENGINE_VERSION_CONFLICT", 409))

    def test_voice_choices_always_include_the_selected_voices(self):
        service, store = self.service()
        service.update(CTX, ENGINE_ID, {"voices": {"A": "F5", "B": "M5"}}, 1)
        params = store.last("UPDATE tts_engines SET")[1]
        choices = next(p for p in params if isinstance(p, list))
        self.assertTrue({"F5", "M5", "F1", "M1"} <= set(choices))


class DisconnectTests(unittest.TestCase):
    def test_deleting_the_default_promotes_another_engine_and_unknown_is_404(self):
        store = FakeStore()
        service, _ = make_service(store)
        store.responses = {"DELETE": [(ENGINE_ID, True)]}
        service.disconnect(CTX, ENGINE_ID)
        self.assertTrue(any(s[0].startswith("UPDATE tts_engines SET is_default=true") for s in store.statements))
        store.statements.clear()
        store.responses = {"DELETE": [(ENGINE_ID, False)]}
        service.disconnect(CTX, ENGINE_ID)
        self.assertFalse(any(s[0].startswith("UPDATE") for s in store.statements))
        store.responses = {"DELETE": []}
        with self.assertRaises(TtsEngineError) as raised:
            service.disconnect(CTX, ENGINE_ID)
        self.assertEqual(raised.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
