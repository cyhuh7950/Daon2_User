"""조직 작성 템플릿(WO-A3): 검증 규칙, 레지스트리 겹침(내장 + 조직), 실DB 저장소(버전·상태·RLS)."""
from __future__ import annotations

import copy
import os
import unittest
import uuid

from daon2_user_api.authoring.org_templates import OrgTemplateProvider, OrgTemplateStore, validate_org_template
from daon2_user_api.authoring.templates import AuthoringError, TemplateRegistry

BASE = {
    "template_id": "org_sample", "title": "조직 템플릿", "version": 1, "description": "설명", "keywords": ["조직제안"],
    "analysis": "rfp_requirements", "style": "proposal",
    "inputs": [{"key": "rfp_document", "question": "RFP를 선택해 주세요.", "kind": "source_ref", "required": True}],
    "knowledge": [],
    "sections": [{"key": "a", "title": "1. 이해", "guidance": "정리한다.", "knowledge_hints": []}],
    "checks": [], "output": {"formats": ["docx"], "default": ["docx"]},
}


def make(**patch):
    value = copy.deepcopy(BASE)
    value.update(patch)
    return value


class ValidationTests(unittest.TestCase):
    def test_valid_template_passes_and_keeps_shape(self):
        cleaned = validate_org_template(make())
        self.assertEqual(cleaned["template_id"], "org_sample")
        self.assertEqual(cleaned["version"], 1)

    def test_rejects_ids_outside_org_namespace_and_builtin_overrides(self):
        for bad in ("rfp_response_proposal", "Org_sample", "org_", "sample", "org_" + "a" * 70):
            with self.subTest(bad=bad), self.assertRaises(AuthoringError) as raised:
                validate_org_template(make(template_id=bad))
            self.assertTrue(raised.exception.code.startswith("AUTHORING_TEMPLATE_INVALID"))
        with self.assertRaises(AuthoringError):
            validate_org_template(make(), expected_id="org_other")

    def test_rejects_unknown_tools_formats_styles_and_limits(self):
        cases = [
            make(knowledge=[{"tool": "delete_everything", "required": False}]),
            make(output={"formats": ["exe"], "default": ["exe"]}),
            make(style="freeform"),
            make(sections=[{"key": f"s{i}", "title": "t", "guidance": "g", "knowledge_hints": []} for i in range(21)]),
            make(sections=[{"key": "a", "title": "t", "guidance": "가" * 501, "knowledge_hints": []}]),
            make(title="가" * 121),
            make(inputs=[{"key": f"k{i}", "question": "q", "kind": "text", "required": False} for i in range(16)]),
            "not-an-object",
        ]
        for case in cases:
            with self.subTest(case=str(case)[:60]), self.assertRaises(AuthoringError) as raised:
                validate_org_template(case)
            self.assertEqual(raised.exception.status, 422)

    def test_error_reason_names_the_location(self):
        with self.assertRaises(AuthoringError) as raised:
            validate_org_template(make(sections=[{"key": "a", "title": "t", "guidance": "가" * 501, "knowledge_hints": []}]))
        self.assertEqual(raised.exception.code, "AUTHORING_TEMPLATE_INVALID:sections[0].guidance")


class FakeProvider:
    def __init__(self, definitions):
        self.definitions = definitions

    def active(self, tenant_id):
        return [d for t, d in self.definitions if t == tenant_id]

    def get(self, tenant_id, template_id, version):
        for t, d in self.definitions:
            if t == tenant_id and d["template_id"] == template_id and (version is None or d["version"] == version):
                return d
        raise AuthoringError("AUTHORING_TEMPLATE_UNKNOWN", 404)


class RegistryOverlayTests(unittest.TestCase):
    def test_org_templates_are_tenant_scoped_and_builtins_stay(self):
        registry = TemplateRegistry(org_provider=FakeProvider([("tenant-a", make())]))
        ids_a = {t["template_id"] for t in registry.list("tenant-a")}
        ids_b = {t["template_id"] for t in registry.list("tenant-b")}
        self.assertIn("org_sample", ids_a)
        self.assertNotIn("org_sample", ids_b)
        self.assertIn("rfp_response_proposal", ids_a & ids_b)
        self.assertEqual(registry.get("org_sample", "tenant-a", 1).title, "조직 템플릿")
        with self.assertRaises(AuthoringError) as raised:
            registry.get("org_sample", "tenant-b")
        self.assertEqual(raised.exception.status, 404)
        with self.assertRaises(AuthoringError):
            registry.get("org_sample")  # 테넌트를 모르면 조직 템플릿은 보이지 않는다
        self.assertEqual(registry.classify("조직제안 문서", "tenant-a"), ["org_sample"])
        self.assertEqual(registry.classify("조직제안 문서", "tenant-b"), [])

    def test_org_template_cannot_shadow_a_builtin(self):
        shadow = make(template_id="rfp_response_proposal", title="가짜")
        registry = TemplateRegistry(org_provider=FakeProvider([("tenant-a", shadow)]))
        self.assertNotEqual(registry.get("rfp_response_proposal", "tenant-a").title, "가짜")
        self.assertEqual([t["title"] for t in registry.list("tenant-a")].count("가짜"), 0)


DSN = os.environ.get("DAON_STUDIO_V2_TEST_DSN")
SEED = os.environ.get("DAON_STUDIO_V2_TEST_SEED_DSN")


@unittest.skipUnless(DSN and SEED, "DAON_STUDIO_V2_TEST_DSN / DAON_STUDIO_V2_TEST_SEED_DSN required")
class StoreIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from daon2_user_api.cloud_storage import PostgresCloudStore
        cls.store = PostgresCloudStore(DSN)
        cls.templates = OrgTemplateStore(cls.store)
        cls.tenant = "tenant-tpl-" + uuid.uuid4().hex[:8]
        cls.other = "tenant-tpl-" + uuid.uuid4().hex[:8]

    @classmethod
    def tearDownClass(cls):
        import psycopg
        with psycopg.connect(SEED, autocommit=True) as seed:
            seed.execute("DELETE FROM authoring_templates WHERE tenant_id IN (%s,%s)", (cls.tenant, cls.other))
        cls.store.close()

    def test_register_version_status_and_tenant_isolation(self):
        template_id = "org_it_" + uuid.uuid4().hex[:8]
        created = self.templates.register(self.tenant, "admin", make(template_id=template_id))
        self.assertEqual((created["version"], created["status"]), (1, "active"))
        with self.assertRaises(AuthoringError) as exists:
            self.templates.register(self.tenant, "admin", make(template_id=template_id))
        self.assertEqual(exists.exception.code, "AUTHORING_TEMPLATE_EXISTS")
        updated = self.templates.new_version(self.tenant, "admin", template_id, make(template_id=template_id, title="바뀐 제목"), 1)
        self.assertEqual(updated["version"], 2)
        with self.assertRaises(AuthoringError) as stale:
            self.templates.new_version(self.tenant, "admin", template_id, make(template_id=template_id), 1)
        self.assertEqual(stale.exception.code, "AUTHORING_TEMPLATE_VERSION_CONFLICT")
        provider = OrgTemplateProvider(self.templates)
        self.assertEqual(provider.get(self.tenant, template_id, None)["title"], "바뀐 제목")
        self.assertEqual(provider.get(self.tenant, template_id, 1)["title"], "조직 템플릿")  # 이전 버전은 그대로
        self.assertEqual([d["template_id"] for d in provider.active(self.tenant)], [template_id])
        self.assertEqual(provider.active(self.other), [])  # RLS: 다른 테넌트에는 보이지 않는다
        disabled = self.templates.set_status(self.tenant, "admin", template_id, "disabled")
        self.assertEqual(disabled["status"], "disabled")
        self.assertEqual(provider.active(self.tenant), [])
        self.assertEqual(provider.get(self.tenant, template_id, 2)["title"], "바뀐 제목")  # 진행 중 세션은 고정 버전을 계속 쓴다
        with self.assertRaises(AuthoringError):
            provider.get(self.tenant, template_id, None)  # 버전 없이는 활성만
        self.assertEqual([t["template_id"] for t in self.templates.list_all(self.tenant, "admin")], [template_id])
        with self.assertRaises(AuthoringError) as unknown:
            self.templates.set_status(self.other, "admin", template_id, "active")
        self.assertEqual(unknown.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
