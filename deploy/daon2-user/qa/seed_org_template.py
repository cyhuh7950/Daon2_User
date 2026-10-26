"""QA 테넌트에 조직 작성 템플릿 org_qa_proposal을 등록한다(WO-A3 시험용). api 컨테이너 안에서 실행한다.

  docker exec daon2_user-api-1 python /tmp/seed_org_template.py <tenant_id>
"""
import os
import sys

from daon2_user_api.authoring.org_templates import OrgTemplateStore
from daon2_user_api.authoring.templates import AuthoringError
from daon2_user_api.cloud_storage import PostgresCloudStore

tenant = sys.argv[1]
store = PostgresCloudStore(os.environ["DAON_CLOUD_DATABASE_DSN"])
store._ensure_pool_open()  # noqa: SLF001
definition = {
    "template_id": "org_qa_proposal", "title": "QA 조직 제안서", "version": 1, "description": "조직 템플릿 시험용(RFP 대응)", "keywords": ["큐에이제안"],
    "analysis": "rfp_requirements", "style": "proposal",
    "inputs": [{"key": "rfp_document", "question": "제안요청서(RFP)로 사용할 소스를 선택해 주세요.", "kind": "source_ref", "required": True}],
    "knowledge": [],
    "sections": [{"key": "understanding", "title": "1. 사업의 이해", "guidance": "제안요청서의 배경과 목적을 정리한다.", "knowledge_hints": []},
                 {"key": "approach", "title": "2. 수행 방안", "guidance": "요구사항별 수행 방법을 정리한다.", "knowledge_hints": []}],
    "checks": [], "output": {"formats": ["docx"], "default": ["docx"]},
}
try:
    print("registered", OrgTemplateStore(store).register(tenant, "seed-script", definition)["version"])
except AuthoringError as error:
    print("exists" if error.code == "AUTHORING_TEMPLATE_EXISTS" else error.code)
store.close()
