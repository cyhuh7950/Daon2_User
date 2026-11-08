"""승인 지식 패키지 가져오기 라우트(시스템 관리자 전용). 응답에는 본문이 없고 식별자·다이제스트만 있다."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .authorization import Action
from .knowledge_package_import import (
    MAX_CONTENT_CHARS, KnowledgePackageImport, KnowledgePackageImportError, PostgresKnowledgePackageImporter, default_period,
)
from .studio_workspace import StudioContext

KNOWLEDGE_PACKAGE_IMPORT_CODES = frozenset({
    "KNOWLEDGE_PACKAGE_ID_INVALID", "KNOWLEDGE_PACKAGE_PRODUCER_INVALID", "KNOWLEDGE_PACKAGE_VERSION_INVALID",
    "KNOWLEDGE_PACKAGE_CONTENT_TYPE_INVALID", "KNOWLEDGE_PACKAGE_TEXT_INVALID", "KNOWLEDGE_PACKAGE_CONTENT_INVALID",
    "KNOWLEDGE_PACKAGE_PERIOD_INVALID", "KNOWLEDGE_PACKAGE_CONFLICT",
})


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str = Field(min_length=1, max_length=128)
    producer: str = Field(min_length=1, max_length=16)
    producer_version: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    content_type: str = Field(default="text/markdown", max_length=32)
    basis: str = Field(min_length=1, max_length=500)
    effective_at: datetime | None = None
    expires_at: datetime | None = None


def register_knowledge_package_import_routes(app: FastAPI, dependencies: Any, importer: PostgresKnowledgePackageImporter) -> None:
    from .runtime import _principal, _require_query_keys, _studio_idempotency_key

    @app.post("/api/v1/workspaces/{id}/knowledge-packages/import", status_code=201)
    async def import_knowledge_package(id: str, body: ImportBody, request: Request,
                                       idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        principal = _principal(request, dependencies)
        if principal.user_id not in dependencies.settings.system_admin_user_ids:
            raise HTTPException(status_code=403)
        dependencies.authorization_service.authorize_action(
            principal=principal, workspace_id=id, action=Action.EDIT, trace_id=request.state.trace_id,
            policy_version=dependencies.settings.policy_version)
        now = datetime.now().astimezone()
        start, end = default_period(now)
        spec = KnowledgePackageImport(
            package_id=body.package_id, producer=body.producer, producer_version=body.producer_version, title=body.title,
            content=body.content, content_type=body.content_type, basis=body.basis,
            effective_at=body.effective_at or start, expires_at=body.expires_at or end)
        context = StudioContext(principal.tenant_id, id, principal.user_id, request.state.trace_id,
                                dependencies.settings.policy_version)
        result = await asyncio.to_thread(importer.import_package, context, spec)
        return JSONResponse({"data": result, "meta": {"trace_id": request.state.trace_id, "workspace_id": id}},
                            status_code=200 if result["replayed"] else 201)

    @app.exception_handler(KnowledgePackageImportError)
    async def knowledge_package_import_error(request: Request, error: KnowledgePackageImportError) -> JSONResponse:
        code = error.code if error.code in KNOWLEDGE_PACKAGE_IMPORT_CODES else "KNOWLEDGE_PACKAGE_IMPORT_FAILED"
        return JSONResponse({"error": {"code": code, "retryable": error.status >= 500,
                                       "trace_id": getattr(request.state, "trace_id", "")}}, status_code=error.status)
