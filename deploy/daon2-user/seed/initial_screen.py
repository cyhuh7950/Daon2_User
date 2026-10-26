"""새 설치의 초기 화면 설정(사용자별 테마). api 컨테이너 안에서 실행한다.

  python3 initial_screen.py [tenant=admin] [user=admin]

이미 저장된 설정이 있으면 건드리지 않는다(멱등). 기본 테마는 SEED_SCREEN_THEME(기본 system).
"""
import os
import sys

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.screen_preferences import ScreenPreferenceContext, ScreenPreferenceService
from daon2_user_api.screen_preferences_postgres import PostgresScreenPreferenceRepository


def apply(service, tenant, user, theme):
    context = ScreenPreferenceContext(tenant, user)
    if service._repository.read(context) is not None:
        return "kept"
    service.save(context, {"theme": theme})
    return "applied"


if __name__ == "__main__":
    tenant = sys.argv[1] if len(sys.argv) > 1 else "admin"
    user = sys.argv[2] if len(sys.argv) > 2 else "admin"
    store = PostgresCloudStore(os.environ["DAON_CLOUD_DATABASE_DSN"])
    service = ScreenPreferenceService(PostgresScreenPreferenceRepository(store))
    result = apply(service, tenant, user, os.environ.get("SEED_SCREEN_THEME", "system"))
    print("화면 설정", tenant, user, "초기값 적용" if result == "applied" else "이미 저장된 설정이 있어 건드리지 않음", service.get(ScreenPreferenceContext(tenant, user)))
    os._exit(0)
