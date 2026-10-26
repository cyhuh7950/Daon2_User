"""조직 작성 템플릿(WO-A3, F6-14). Tenant 단위로 저장하고 관리자만 등록·수정·비활성한다.

- 형식은 내장 템플릿과 같은 사전이며 `parse_template`이 먼저 검증한다. 그 위에 조직 규칙을 더한다:
  ID는 `org_`로 시작(내장 덮어쓰기 금지), 섹션 ≤ 20, 입력 ≤ 15, 문자열 길이 상한, 지시문(guidance) ≤ 500자.
- 수정은 새 버전을 쌓고(불변) 비활성은 상태만 바꾼다. 진행 중인 세션은 자기 버전으로 계속한다.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from psycopg.types.json import Jsonb

from ..cloud_storage import CloudAccessContext, CloudDatabaseError, PostgresCloudStore
from .templates import AuthoringError, parse_template

_ID = re.compile(r"^org_[a-z0-9_]{1,60}$")
MAX_SECTIONS, MAX_INPUTS, MAX_BYTES = 20, 15, 65536
_STRING_LIMITS = {"title": 120, "description": 500, "question": 300, "guidance": 500}


def _invalid(reason: str) -> AuthoringError:
    return AuthoringError(f"AUTHORING_TEMPLATE_INVALID:{reason}", 422)


def validate_org_template(raw: Any, *, expected_id: str | None = None) -> dict[str, Any]:
    """조직 규칙을 확인하고 정리된 사전을 돌려준다. 실패하면 위치가 드러나는 사유를 담은 AuthoringError."""
    if not isinstance(raw, Mapping):
        raise _invalid("not_object")
    definition = json.loads(json.dumps(raw, ensure_ascii=False))  # 깊은 복사 + JSON 가능성 확인
    if len(json.dumps(definition, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise _invalid("too_large")
    template_id = definition.get("template_id")
    if not isinstance(template_id, str) or not _ID.fullmatch(template_id):
        raise _invalid("template_id")
    if expected_id is not None and template_id != expected_id:
        raise _invalid("template_id_mismatch")
    if len(definition.get("sections") or []) > MAX_SECTIONS:
        raise _invalid("sections_limit")
    if len(definition.get("inputs") or []) > MAX_INPUTS:
        raise _invalid("inputs_limit")
    for key, limit in _STRING_LIMITS.items():
        if isinstance(definition.get(key), str) and len(definition[key]) > limit:
            raise _invalid(key)
    for index, section in enumerate(definition.get("sections") or []):
        if not isinstance(section, Mapping):
            raise _invalid(f"sections[{index}]")
        for key in ("title", "guidance"):
            if isinstance(section.get(key), str) and len(section[key]) > _STRING_LIMITS[key]:
                raise _invalid(f"sections[{index}].{key}")
    for index, item in enumerate(definition.get("inputs") or []):
        if isinstance(item, Mapping) and isinstance(item.get("question"), str) and len(item["question"]) > _STRING_LIMITS["question"]:
            raise _invalid(f"inputs[{index}].question")
    try:
        parse_template(definition)  # 내장 템플릿과 같은 구조·허용 도구·출력 형식 검증
    except AuthoringError as error:
        raise AuthoringError(error.code, 422) from None
    except (KeyError, TypeError, AttributeError, ValueError):
        raise _invalid("structure") from None
    definition["version"] = int(definition["version"])
    return definition


class OrgTemplateStore:
    """Tenant 단위 저장소. Tenant 범위 RLS(`authoring_templates_scope`)를 쓴다."""

    def __init__(self, store: PostgresCloudStore) -> None:
        self._store = store

    @staticmethod
    def _scope(tenant_id: str, actor_id: str, capability: str) -> CloudAccessContext:
        return CloudAccessContext(tenant_id, "authoring-templates", actor_id, capability)

    # ------------------------------------------------------------ 관리자
    def register(self, tenant_id: str, actor_id: str, raw: Any) -> dict[str, Any]:
        definition = validate_org_template(raw)
        definition["version"] = 1
        try:
            with self._store._transaction(self._scope(tenant_id, actor_id, "authoring_template.write")) as connection:
                if connection.execute("SELECT 1 FROM authoring_templates WHERE tenant_id=%s AND template_id=%s LIMIT 1", (tenant_id, definition["template_id"])).fetchone():
                    raise AuthoringError("AUTHORING_TEMPLATE_EXISTS", 409)
                connection.execute(
                    "INSERT INTO authoring_templates(tenant_id,template_id,version,definition_json,status,created_by) VALUES (%s,%s,1,%s,'active',%s)",
                    (tenant_id, definition["template_id"], Jsonb(definition), actor_id))
        except CloudDatabaseError:
            raise AuthoringError("AUTHORING_TEMPLATE_UNAVAILABLE", 503) from None
        return self._summary(definition, 1, "active")

    def new_version(self, tenant_id: str, actor_id: str, template_id: str, raw: Any, expected_version: int) -> dict[str, Any]:
        definition = validate_org_template(raw, expected_id=template_id)
        try:
            with self._store._transaction(self._scope(tenant_id, actor_id, "authoring_template.write")) as connection:
                latest = connection.execute("SELECT max(version) FROM authoring_templates WHERE tenant_id=%s AND template_id=%s", (tenant_id, template_id)).fetchone()[0]
                if latest is None:
                    raise AuthoringError("AUTHORING_TEMPLATE_UNKNOWN", 404)
                if int(latest) != expected_version:
                    raise AuthoringError("AUTHORING_TEMPLATE_VERSION_CONFLICT", 409)
                status = connection.execute("SELECT status FROM authoring_templates WHERE tenant_id=%s AND template_id=%s AND version=%s", (tenant_id, template_id, latest)).fetchone()[0]
                definition["version"] = int(latest) + 1
                connection.execute(
                    "INSERT INTO authoring_templates(tenant_id,template_id,version,definition_json,status,created_by) VALUES (%s,%s,%s,%s,%s,%s)",
                    (tenant_id, template_id, definition["version"], Jsonb(definition), status, actor_id))
        except CloudDatabaseError:
            raise AuthoringError("AUTHORING_TEMPLATE_UNAVAILABLE", 503) from None
        return self._summary(definition, definition["version"], status)

    def set_status(self, tenant_id: str, actor_id: str, template_id: str, status: str) -> dict[str, Any]:
        if status not in ("active", "disabled"):
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        try:
            with self._store._transaction(self._scope(tenant_id, actor_id, "authoring_template.write")) as connection:
                latest = connection.execute("SELECT max(version) FROM authoring_templates WHERE tenant_id=%s AND template_id=%s", (tenant_id, template_id)).fetchone()[0]
                if latest is None:
                    raise AuthoringError("AUTHORING_TEMPLATE_UNKNOWN", 404)
                connection.execute("UPDATE authoring_templates SET status=%s WHERE tenant_id=%s AND template_id=%s AND version=%s", (status, tenant_id, template_id, latest))
                row = connection.execute("SELECT definition_json FROM authoring_templates WHERE tenant_id=%s AND template_id=%s AND version=%s", (tenant_id, template_id, latest)).fetchone()
        except CloudDatabaseError:
            raise AuthoringError("AUTHORING_TEMPLATE_UNAVAILABLE", 503) from None
        return self._summary(row[0], int(latest), status)

    def list_all(self, tenant_id: str, actor_id: str) -> list[dict[str, Any]]:
        """관리자 목록: 템플릿마다 최신 버전."""
        try:
            with self._store._transaction(self._scope(tenant_id, actor_id, "authoring_template.read")) as connection:
                rows = connection.execute(
                    "SELECT DISTINCT ON (template_id) template_id,version,status,definition_json FROM authoring_templates WHERE tenant_id=%s ORDER BY template_id,version DESC",
                    (tenant_id,)).fetchall()
        except CloudDatabaseError:
            raise AuthoringError("AUTHORING_TEMPLATE_UNAVAILABLE", 503) from None
        return [self._summary(r[3], int(r[1]), r[2]) for r in rows]

    def export(self, tenant_id: str, actor_id: str, template_id: str, version: int | None = None) -> dict[str, Any]:
        row = self._row(tenant_id, actor_id, template_id, version)
        return dict(row[0])

    # ------------------------------------------------------------ 사용자(작성 엔진)
    def active_definitions(self, tenant_id: str, actor_id: str) -> list[dict[str, Any]]:
        try:
            with self._store._transaction(self._scope(tenant_id, actor_id, "authoring_template.read")) as connection:
                rows = connection.execute(
                    "SELECT DISTINCT ON (template_id) definition_json,status FROM authoring_templates WHERE tenant_id=%s ORDER BY template_id,version DESC", (tenant_id,)).fetchall()
        except CloudDatabaseError:
            return []  # 조직 템플릿을 읽지 못해도 내장 템플릿은 쓸 수 있다
        return [dict(r[0]) for r in rows if r[1] == "active"]

    def definition(self, tenant_id: str, actor_id: str, template_id: str, version: int | None) -> dict[str, Any]:
        """세션이 고정한 버전(비활성이어도 진행 중 세션은 계속)을, 버전이 없으면 활성 최신을 돌려준다."""
        row = self._row(tenant_id, actor_id, template_id, version, active_only=version is None)
        return dict(row[0])

    def _row(self, tenant_id: str, actor_id: str, template_id: str, version: int | None, *, active_only: bool = False):  # type: ignore[no-untyped-def]
        try:
            with self._store._transaction(self._scope(tenant_id, actor_id, "authoring_template.read")) as connection:
                if version is None:
                    row = connection.execute(
                        "SELECT definition_json,status FROM authoring_templates WHERE tenant_id=%s AND template_id=%s ORDER BY version DESC LIMIT 1", (tenant_id, template_id)).fetchone()
                else:
                    row = connection.execute(
                        "SELECT definition_json,status FROM authoring_templates WHERE tenant_id=%s AND template_id=%s AND version=%s", (tenant_id, template_id, version)).fetchone()
        except CloudDatabaseError:
            raise AuthoringError("AUTHORING_TEMPLATE_UNAVAILABLE", 503) from None
        if row is None or (active_only and row[1] != "active"):
            raise AuthoringError("AUTHORING_TEMPLATE_UNKNOWN", 404)
        return row

    @staticmethod
    def _summary(definition: Mapping[str, Any], version: int, status: str) -> dict[str, Any]:
        return {"template_id": definition["template_id"], "title": definition["title"], "description": definition.get("description", ""), "version": version,
                "status": status, "sections": len(definition.get("sections") or []), "style": definition.get("style", "proposal"),
                "output_formats": list((definition.get("output") or {}).get("formats", []))}


class OrgTemplateProvider:
    """TemplateRegistry가 쓰는 얇은 어댑터(읽기 전용)."""

    def __init__(self, store: OrgTemplateStore, actor_id: str = "authoring-reader") -> None:
        self._store = store
        self._actor = actor_id

    def active(self, tenant_id: str) -> Sequence[Mapping[str, Any]]:
        return self._store.active_definitions(tenant_id, self._actor)

    def get(self, tenant_id: str, template_id: str, version: int | None) -> Mapping[str, Any]:
        return self._store.definition(tenant_id, self._actor, template_id, version)
