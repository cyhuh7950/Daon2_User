"""승인 지식 패키지를 가져온다(운영자). api 컨테이너 안에서 실행한다.

  python3 import_knowledge_package.py <tenant_id> <workspace_id> <actor_id> <markdown_file> <package_id> <producer> <version> <title> <basis>

내용은 마크다운 파일이고 제목 경계로 나뉘어 질문 근거(Citation)가 된다. 같은 package_id·같은 내용이면 아무것도 바꾸지 않는다.
"""
import os
import sys
import uuid
from datetime import datetime

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.knowledge_package_import import (
    KnowledgePackageImport, KnowledgePackageImportError, PostgresKnowledgePackageImporter, default_period,
)
from daon2_user_api.studio_workspace import StudioContext

if __name__ == "__main__":
    tenant, workspace, actor, path, package_id, producer, version, title, basis = sys.argv[1:10]
    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    start, end = default_period(datetime.now().astimezone())
    store = PostgresCloudStore(os.environ["DAON_CLOUD_DATABASE_DSN"])
    context = StudioContext(tenant, workspace, actor, "trace-import-" + uuid.uuid4().hex[:24],
                            os.environ.get("DAON_POLICY_VERSION", "runtime-policy-v1"))
    try:
        result = PostgresKnowledgePackageImporter(store).import_package(
            context, KnowledgePackageImport(package_id, producer, version, title, content, start, end, basis))
    except KnowledgePackageImportError as error:
        print(f"가져오기 실패: {error.code} (HTTP {error.status})")
        os._exit(1)
    print({key: result[key] for key in ("package_id", "producer", "authority", "package_digest", "byte_size", "chunks", "replayed")})
    os._exit(0)  # 연결 풀 종료 시 잡음 방지
