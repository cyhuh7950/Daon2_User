"""완료 자료 대화 수정의 저장과 반영(WO-K5 §5.3, §6)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from psycopg.types.json import Jsonb

from .studio_chat_edit import AUTHORED_TYPE, CHAT_EDIT_TYPES, ChatEditInvalid, apply_changes, authored_known_refs
from .studio_v2_queue import CHAT_EDIT_MODE
from .studio_workspace import StudioContext, StudioError

MAX_INSTRUCTION_CHARS = 2000
COLUMNS = ("turn_id", "output_id", "job_id", "base_revision", "instruction", "state", "reply", "changes_json", "new_evidence_json",
           "error_code", "applied_revision", "created_at")
_SELECT = "SELECT " + ",".join(COLUMNS) + " FROM studio_v2_edit_turns WHERE tenant_id=%s AND workspace_id=%s AND "
_PUBLIC_CHANGE = ("op", "id", "before_text", "after_text", "reason")


def _record(row: Sequence[Any]) -> dict[str, Any]:
    return dict(zip(COLUMNS, row))


def _public(record: Mapping[str, Any]) -> dict[str, Any]:
    created = record["created_at"]
    return {"turn_id": record["turn_id"], "output_id": record["output_id"], "base_revision": record["base_revision"], "instruction": record["instruction"],
            "state": record["state"], "reply": record["reply"], "changes": [{key: change.get(key) for key in _PUBLIC_CHANGE} for change in record["changes_json"]],
            "error_code": record["error_code"], "applied_revision": record["applied_revision"], "created_at": created.isoformat() if hasattr(created, "isoformat") else created}


class StudioV2EditTurnsMixin:
    """`PostgresStudioV2Repository`에 섞어 쓴다. 저장소의 연결·자료 조회·리비전 저장을 그대로 쓴다."""

    def _turn(self, connection, context: StudioContext, turn_id: str, *, lock: bool = False) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        row = connection.execute(_SELECT + "turn_id=%s" + (" FOR UPDATE" if lock else ""), (context.tenant_id, context.workspace_id, turn_id)).fetchone()
        if row is None:
            raise StudioError("RESOURCE_UNAVAILABLE", 404)
        return _record(row)

    def enqueue_edit_turn(self, context: StudioContext, output_id: str, instruction: str, idempotency_key: str) -> dict[str, Any]:
        from .studio_v2_postgres import opaque, sha256_hex
        notebook_id = self._require_notebook(context)  # type: ignore[attr-defined]
        text = instruction.strip() if isinstance(instruction, str) else ""
        if not 1 <= len(text) <= MAX_INSTRUCTION_CHARS or not isinstance(idempotency_key, str) or not 16 <= len(idempotency_key) <= 128:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        key_sha = sha256_hex(idempotency_key)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:  # type: ignore[attr-defined]
            row = self._owned_output(connection, context, output_id, lock=True)  # type: ignore[attr-defined]
            existing = connection.execute(_SELECT + "owner_actor_id=%s AND idempotency_key_sha256=%s",
                                          (context.tenant_id, context.workspace_id, context.actor_id, key_sha)).fetchone()
            if existing is not None:
                record = _record(existing)
                if record["instruction"] != text or record["output_id"] != output_id:
                    raise StudioError("IDEMPOTENCY_CONFLICT", 409)
                return {"turn_id": record["turn_id"], "job_id": record["job_id"], "state": record["state"], "replayed": True}
            if row[1] not in CHAT_EDIT_TYPES:
                raise StudioError("CHAT_EDIT_UNSUPPORTED", 409)
            if row[4] != "completed":
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            active = connection.execute("SELECT 1 FROM studio_v2_edit_turns WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND state IN ('queued','working')",
                                        (context.tenant_id, context.workspace_id, output_id)).fetchone()
            if active is not None:
                raise StudioError("CHAT_EDIT_BUSY", 409)
            turn_id, job_id = opaque("svt", output_id, key_sha), opaque("sve", output_id, key_sha)
            connection.execute(
                "INSERT INTO studio_v2_edit_turns(tenant_id,workspace_id,turn_id,output_id,owner_actor_id,job_id,base_revision,instruction,state,idempotency_key_sha256) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'queued',%s)",
                (context.tenant_id, context.workspace_id, turn_id, output_id, context.actor_id, job_id, int(row[8]), text, key_sha))
            self._insert_job(connection, context, output_id, job_id, CHAT_EDIT_MODE, str(row[1]), None, {"turn_id": turn_id}, [], notebook_id)  # type: ignore[attr-defined]
        return {"turn_id": turn_id, "job_id": job_id, "state": "queued", "replayed": False}

    def list_edit_turns(self, context: StudioContext, output_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:  # type: ignore[attr-defined]
            self._owned_output(connection, context, output_id)  # type: ignore[attr-defined]
            rows = connection.execute(_SELECT + "output_id=%s ORDER BY created_at DESC LIMIT %s", (context.tenant_id, context.workspace_id, output_id, limit)).fetchall()
        return [_public(_record(row)) for row in reversed(rows)]

    def chat_material_scope(self, context: StudioContext, output_id: str) -> dict[str, Any]:
        """자료 찾기 범위: 자료에 연결된 Source와 이미 쓰인 근거 번호."""
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:  # type: ignore[attr-defined]
            row = self._owned_output(connection, context, output_id)  # type: ignore[attr-defined]
            refs = connection.execute("SELECT ref_id FROM studio_v2_evidence WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
                                      (context.tenant_id, context.workspace_id, output_id, row[8])).fetchall()
        return {"versions": list(row[7] or []), "refs": {str(ref[0]) for ref in refs}}

    def edit_turn_for_job(self, context: StudioContext, turn_id: str) -> dict[str, Any]:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:  # type: ignore[attr-defined]
            return self._turn(connection, context, turn_id)

    def _update_active_turn(self, context: StudioContext, turn_id: str, assignments: str, values: Sequence[Any]) -> None:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:  # type: ignore[attr-defined]
            connection.execute(f"UPDATE studio_v2_edit_turns SET {assignments},updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND turn_id=%s AND state IN ('queued','working')",
                               (*values, context.tenant_id, context.workspace_id, turn_id))

    def mark_edit_turn_working(self, context: StudioContext, turn_id: str) -> None:
        self._update_active_turn(context, turn_id, "state='working'", ())

    def save_edit_turn_result(self, context: StudioContext, turn_id: str, *, reply: str, changes: Sequence[Mapping[str, Any]], new_evidence: Sequence[Mapping[str, Any]]) -> None:
        state = "ready" if changes else "no_change"
        self._update_active_turn(context, turn_id, "state=%s,reply=%s,changes_json=%s,new_evidence_json=%s", (state, reply, Jsonb(list(changes)), Jsonb(list(new_evidence))))

    def fail_edit_turn(self, context: StudioContext, turn_id: str, code: str) -> None:
        self._update_active_turn(context, turn_id, "state='failed',error_code=%s", (code,))

    def apply_edit_turn(self, context: StudioContext, output_id: str, turn_id: str) -> int:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:  # type: ignore[attr-defined]
            row = self._owned_output(connection, context, output_id, lock=True)  # type: ignore[attr-defined]
            turn = self._turn(connection, context, turn_id, lock=True)
            if turn["output_id"] != output_id:
                raise StudioError("RESOURCE_UNAVAILABLE", 404)
            if turn["state"] == "applied":
                return int(turn["applied_revision"])
            if turn["state"] != "ready":
                raise StudioError("CHAT_EDIT_STATE_INVALID", 409)
            if row[4] != "completed":
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            current = int(row[8])
            if current != int(turn["base_revision"]):
                raise StudioError("CHAT_EDIT_STALE", 409)
            if row[1] == AUTHORED_TYPE:
                number = self._apply_authored_turn(connection, context, output_id, current, list(row[7] or []), turn)
            else:
                number = self._apply_turn_content(connection, context, output_id, str(row[1]), current, turn)
            connection.execute("UPDATE studio_v2_edit_turns SET state='applied',applied_revision=%s,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND turn_id=%s",
                               (number, context.tenant_id, context.workspace_id, turn_id))
            return number

    def _apply_authored_turn(self, connection, context: StudioContext, output_id: str, current: int, versions: list[str], turn: Mapping[str, Any]) -> int:  # type: ignore[no-untyped-def]
        """문서는 세션에 반영한 뒤 기존 재개 경로로 근거·용어 점검을 다시 돌린다(WO-K5 §6)."""
        from .authoring import session as authoring_session
        evidence = turn["new_evidence_json"]

        def mutate(content: Mapping[str, Any]) -> dict[str, Any]:
            known = authored_known_refs(content) | {str(row["ref"]) for row in evidence}
            try:
                updated = apply_changes(AUTHORED_TYPE, content, turn["changes_json"], known)
            except ChatEditInvalid:
                raise StudioError("CHAT_EDIT_INVALID", 422) from None
            updated["knowledge"] = [*(updated.get("knowledge") or []), *evidence]
            return authoring_session.resume(authoring_session.reopen(updated))

        result = self.authoring_apply(context, output_id, current, mutate, enqueue_step="generate", source_version_ids=versions, connection=connection,  # type: ignore[attr-defined]
                                      generated_with={"edited_by": "llm_chat", "change_reason": str(turn["instruction"])[:200]})
        return int(result["revision_no"])

    def _apply_turn_content(self, connection, context: StudioContext, output_id: str, type_id: str, current: int, turn: Mapping[str, Any]) -> int:  # type: ignore[no-untyped-def]
        scope = (context.tenant_id, context.workspace_id, output_id, current)
        previous = connection.execute("SELECT content_json FROM studio_v2_revisions WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s", scope).fetchone()
        if previous is None:
            raise StudioError("STUDIO_VERSION_CONFLICT", 409)
        known = {str(r[0]) for r in connection.execute("SELECT ref_id FROM studio_v2_evidence WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s", scope).fetchall()}
        evidence = turn["new_evidence_json"]
        known |= {str(item["ref_id"]) for item in evidence}
        try:
            content = apply_changes(type_id, previous[0], turn["changes_json"], known)
        except ChatEditInvalid:
            raise StudioError("CHAT_EDIT_INVALID", 422) from None
        number = self.add_revision(context, output_id, "user_edit", content, warnings=[], evidence=evidence, connection=connection,  # type: ignore[attr-defined]
                                   generated_with={"edited_by": "llm_chat", "change_reason": str(turn["instruction"])[:200]})
        self._copy_lineage(connection, context, output_id, number, current)  # type: ignore[attr-defined]
        return number

    def discard_edit_turn(self, context: StudioContext, output_id: str, turn_id: str) -> None:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:  # type: ignore[attr-defined]
            turn = self._turn(connection, context, turn_id, lock=True)
            if turn["output_id"] != output_id:
                raise StudioError("RESOURCE_UNAVAILABLE", 404)
            if turn["state"] != "ready":
                raise StudioError("CHAT_EDIT_STATE_INVALID", 409)
            connection.execute("UPDATE studio_v2_edit_turns SET state='discarded',updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND turn_id=%s",
                               (context.tenant_id, context.workspace_id, turn_id))
