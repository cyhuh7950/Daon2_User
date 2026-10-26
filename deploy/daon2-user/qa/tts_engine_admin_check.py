"""TTS 엔진 관리 서비스(WO-F7T)를 실제 DB·실제 암호화·실제 음성 서버로 확인한다. api 컨테이너 안에서 실행한다.

  docker exec daon2_user-api-1 python /tmp/tts_engine_admin_check.py <tenant_id> register
  docker exec daon2_user-api-1 python /tmp/tts_engine_admin_check.py <tenant_id> cleanup

register: 배포 설정 파일의 supertonic 주소·키로 화면 등록 엔진 `supertonic-ui`를 등록 → 연결 확인 → 기본 지정.
          (키는 출력하지 않는다.) 이후 다른 프로세스(API·워커)가 15초 캐시 뒤 이 엔진을 쓴다.
cleanup:  등록한 엔진을 해제한다(기본 엔진은 배포 설정으로 돌아간다).
"""
import json
import os
import sys

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.knowledge_connector_service import settings_from_env
from daon2_user_api.provider_credentials import ProviderCredentialCipher
from daon2_user_api.tts_engine_service import TtsAdminContext, TtsEngineService
from daon2_user_api.tts_engines import configured_from_env
from pathlib import Path

tenant, action = sys.argv[1], sys.argv[2]
SLUG = "supertonic-ui"
cipher = ProviderCredentialCipher(Path(os.environ["DAON_PROVIDER_CREDENTIAL_KEY_FILE"]).read_bytes(), encryption_key_version=1)
store = PostgresCloudStore(os.environ["DAON_CLOUD_DATABASE_DSN"])
file_config = configured_from_env()
service = TtsEngineService(store, cipher, file_config=file_config, allow_private=settings_from_env()["allow_private"], cache_seconds=0.0)
ctx = TtsAdminContext(tenant, "qa-admin-check", "trace-qa")


def ok(label, condition, detail=""):
    print("PASS" if condition else "FAIL", label, detail, flush=True)
    if not condition:
        sys.exit(1)


existing = next((e for e in service.list(ctx) if e["slug"] == SLUG and e["source"] == "settings"), None)
if action == "cleanup":
    if existing:
        service.disconnect(ctx, existing["engine_id"])
    left = [e["slug"] for e in service.list(ctx)]
    ok("cleanup removed the screen-registered engine", SLUG not in left, left)
    store.close()
    sys.exit(0)

deployed = file_config.engines[file_config.default]
if existing:
    service.disconnect(ctx, existing["engine_id"])
created = service.register(ctx, {"slug": SLUG, "label": "Supertonic (화면 등록)", "base_url": deployed.base_url, "api_key": deployed.api_key,
                                 "provider_kind": deployed.provider_kind, "voices": {"A": "F1", "B": "M1"}})
ok("registered (key never in the view)", created["has_credential"] and deployed.api_key not in json.dumps(created), created["status"])
verified = service.verify(ctx, created["engine_id"])
ok("verify against the real voice server", verified["status"] == "verified", verified["error_code"])
ok("voice choices were filled from the server", {"F1", "F2", "M1", "M2"} <= set(verified["voice_choices"]) and len(verified["voice_choices"]) >= 10, len(verified["voice_choices"]))
made_default = service.update(ctx, created["engine_id"], {"is_default": True}, verified["version"])
ok("set as the default engine", made_default["is_default"] is True)
config = service.for_tenant(tenant)
ok("resolver returns the screen engine with the decrypted key as default",
   config.default == SLUG and config.engines[SLUG].source == "settings" and config.engines[SLUG].api_key == deployed.api_key, config.default)
ok("deployment engine is still available", file_config.default in config.engines, sorted(config.engines))
store.close()
print("RESULT register ok", flush=True)
