"""TTS 엔진 등록부 실DB 시험(WO-F7T). DAON_STUDIO_V2_TEST_DSN(daon_app 멤버 로그인, 마이그레이션 0078 적용 DB)이 있을 때만 실행한다."""
from __future__ import annotations

import os
import unittest
import uuid

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.provider_credentials import ProviderCredentialCipher
from daon2_user_api.tts_engine_service import TtsAdminContext, TtsEngineError, TtsEngineService

DSN = os.environ.get("DAON_STUDIO_V2_TEST_DSN")
SPEC = {"label": "Supertonic", "base_url": "https://tts.example.com", "api_key": "secret-key-for-it", "voices": {"A": "F1", "B": "M1"}}


@unittest.skipUnless(DSN, "DAON_STUDIO_V2_TEST_DSN required")
class TtsEnginePostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = PostgresCloudStore(DSN)
        cls.cipher = ProviderCredentialCipher(os.urandom(32), encryption_key_version=1)

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def setUp(self):
        self.tenant = "tts-it-" + uuid.uuid4().hex[:12]
        self.ctx = TtsAdminContext(self.tenant, "it-admin", "trace-it")
        self.service = TtsEngineService(self.store, self.cipher, cache_seconds=0.0)

    def tearDown(self):
        for item in self.service.list(self.ctx):
            if item["engine_id"]:
                self.service.disconnect(self.ctx, item["engine_id"])

    def register(self, slug, **over):
        return self.service.register(self.ctx, {**SPEC, "slug": slug, **over})

    def test_register_encrypts_the_key_and_the_resolver_decrypts_it(self):
        created = self.register("supertonic")
        self.assertTrue(created["is_default"])               # 첫 엔진은 기본
        self.assertTrue(created["has_credential"])
        self.assertNotIn("secret-key-for-it", str(created))
        config = self.service.for_tenant(self.tenant)
        self.assertEqual(config.default, "supertonic")
        engine = config.engines["supertonic"]
        self.assertEqual((engine.api_key, engine.base_url, engine.source, engine.voices), ("secret-key-for-it", "https://tts.example.com", "settings", {"A": "F1", "B": "M1"}))
        import psycopg
        with psycopg.connect(os.environ["DAON_STUDIO_V2_TEST_SEED_DSN"], autocommit=True) as seed:
            raw = seed.execute("SELECT credential_ciphertext FROM tts_engines WHERE tenant_id=%s", (self.tenant,)).fetchone()[0]
        self.assertNotIn(b"secret-key-for-it", bytes(raw))

    def test_one_default_per_tenant_and_promotion_on_delete(self):
        first, second = self.register("one"), self.register("two")
        self.assertEqual((first["is_default"], second["is_default"]), (True, False))
        updated = self.service.update(self.ctx, second["engine_id"], {"is_default": True}, second["version"])
        self.assertTrue(updated["is_default"])
        defaults = [i["slug"] for i in self.service.list(self.ctx) if i["is_default"]]
        self.assertEqual(defaults, ["two"])
        self.service.disconnect(self.ctx, second["engine_id"])
        self.assertEqual([i["slug"] for i in self.service.list(self.ctx) if i["is_default"]], ["one"])    # 남은 엔진이 기본이 된다

    def test_slug_is_unique_per_tenant_and_versions_are_enforced(self):
        created = self.register("dup")
        with self.assertRaises(TtsEngineError) as raised:
            self.register("dup")
        self.assertEqual((raised.exception.code, raised.exception.status), ("TTS_ENGINE_SLUG_EXISTS", 409))
        renamed = self.service.update(self.ctx, created["engine_id"], {"label": "새 이름"}, created["version"])
        self.assertEqual((renamed["label"], renamed["version"]), ("새 이름", created["version"] + 1))
        with self.assertRaises(TtsEngineError) as raised:
            self.service.update(self.ctx, created["engine_id"], {"label": "또"}, created["version"])      # 옛 버전
        self.assertEqual(raised.exception.code, "TTS_ENGINE_VERSION_CONFLICT")

    def test_other_tenants_cannot_see_or_change_the_engine(self):
        created = self.register("private")
        other = TtsAdminContext("tts-it-" + uuid.uuid4().hex[:12], "other-admin")
        self.assertEqual([i for i in self.service.list(other) if i["engine_id"]], [])
        self.assertIsNone(self.service.for_tenant(other.tenant_id))
        with self.assertRaises(TtsEngineError) as raised:
            self.service.update(other, created["engine_id"], {"label": "훔침"}, created["version"])
        self.assertEqual(raised.exception.status, 404)
        with self.assertRaises(TtsEngineError):
            self.service.disconnect(other, created["engine_id"])

    def test_disable_hides_the_engine_from_resolution_and_enable_requires_reverification(self):
        created = self.register("pausable")
        off = self.service.update(self.ctx, created["engine_id"], {"enabled": False}, created["version"])
        self.assertEqual((off["status"], off["is_default"]), ("disabled", False))
        self.assertIsNone(self.service.for_tenant(self.tenant))
        on = self.service.update(self.ctx, created["engine_id"], {"enabled": True}, off["version"])
        self.assertEqual(on["status"], "unverified")
        self.assertIsNotNone(self.service.for_tenant(self.tenant))

    def test_key_replacement_changes_the_decrypted_key_and_resets_status(self):
        created = self.register("rotate")
        updated = self.service.update(self.ctx, created["engine_id"], {"api_key": "rotated-secret-key"}, created["version"])
        self.assertEqual(updated["status"], "unverified")
        self.assertEqual(self.service.for_tenant(self.tenant).engines["rotate"].api_key, "rotated-secret-key")


if __name__ == "__main__":
    unittest.main()
