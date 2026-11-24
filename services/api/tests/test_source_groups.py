"""소스 묶음 저장·조회 계약(WO-N1 N1-5, NB3-F2, 결정 D-11 노트북 공유, 정정 C-4 질문 상한 8개 유지)."""
from __future__ import annotations

import copy
import re
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from daon2_user_api import source_groups as sg
from daon2_user_api.cloud_storage import CloudDatabaseError
from daon2_user_api.source_groups import SourceGroupsContext, SourceGroupsError, SourceGroupsService

CTX = SourceGroupsContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1")
OTHER = SourceGroupsContext("tenant-1", "workspace-1", "actor-2", "trace-2", "policy-1")
KEY = "idem-key-0000000001"
CANON = ("sources", "source_versions", "notebook_bindings", "notebook_source_unbindings")


class FakeDb:
    """정본 표는 '노트북에 있는 소스' 판정 결과(in_notebook)로만 흉내 낸다. 새 표 두 개는 행으로 둔다."""

    def __init__(self):
        self.notebooks = {"notebook-1", "notebook-2"}
        # 노트북 소스 목록 판정(연결됨·떼지 않음·삭제 요청 없음·내 접근 거부 없음)을 통과하는 소스.
        self.in_notebook = {"notebook-1": {"src-a", "src-b", "src-c", "src-d"}, "notebook-2": {"src-x"}}
        self.denied: dict[str, set[str]] = {}   # actor -> 접근 거부된 소스
        self.groups: dict[str, dict] = {}
        self.members: dict[tuple[str, str], dict] = {}  # (notebook, source) -> {group_id, position}
        self.executed: list[tuple[str, tuple]] = []
        self.scopes: list[tuple] = []
        self.locks: list[str] = []
        self.clock = datetime(2026, 11, 24, tzinfo=timezone.utc)
        self.fail = False

    @contextmanager
    def _transaction(self, scope):
        if self.fail:
            raise CloudDatabaseError("DB_DOWN", retryable=True)
        self.scopes.append((scope.tenant_id, scope.workspace_id, scope.actor_id, scope.capability))
        snapshot = copy.deepcopy((self.groups, self.members))
        try:
            yield FakeConnection(self, scope)
        except Exception:
            self.groups, self.members = snapshot
            raise

    def visible(self, notebook_id, actor_id):
        return self.in_notebook.get(notebook_id, set()) - self.denied.get(actor_id, set())

    def tick(self):
        self.clock += timedelta(seconds=1)
        return self.clock


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, db, scope):
        self.db, self.scope = db, scope

    def execute(self, sql, params=()):
        db, p = self.db, tuple(params)
        db.executed.append((sql, p))
        if sql in (sg._RENAME_SQL, sg._POSITION_SQL):  # SET 값이 먼저, 범위 키가 뒤에 온다
            p = p[1:] + p[:1]
        assert p[:2] == (self.scope.tenant_id, self.scope.workspace_id) or sql == sg._LOCK_SQL, sql
        if sql == sg._LOCK_SQL:
            db.locks.append(p[0])
            return _Result([(None,)])
        if sql == sg._NOTEBOOK_SQL:
            return _Result([(1,)] if p[2] in db.notebooks else [])
        if sql == sg._GROUPS_SQL:
            rows = sorted((g for g in db.groups.values() if g["notebook_id"] == p[2]),
                          key=lambda g: (g["position"], g["created_at"], g["group_id"]))
            return _Result([(g["group_id"], g["name"], g["position"]) for g in rows])
        if sql == sg._VISIBLE_MEMBERS_SQL:
            assert p[3] == self.scope.actor_id
            visible = db.visible(p[2], p[3])
            rows = sorted(((m["group_id"], s, m["position"]) for (nb, s), m in db.members.items() if nb == p[2] and s in visible),
                          key=lambda r: (r[0], r[2], r[1]))
            return _Result([(g, s) for g, s, _ in rows])
        if sql == sg._IN_NOTEBOOK_SQL:
            assert p[3] == self.scope.actor_id
            visible = db.visible(p[2], p[3])
            return _Result([(s,) for s in sorted(set(p[4]) & visible)])
        if sql == sg._GROUP_SQL:
            g = db.groups.get(p[2])
            return _Result([] if g is None else [(g["notebook_id"], g["name"])])
        if sql == sg._COUNT_GROUPS_SQL:
            rows = [g for g in db.groups.values() if g["notebook_id"] == p[2]]
            return _Result([(len(rows), max((g["position"] for g in rows), default=-1) + 1)])
        if sql == sg._INSERT_GROUP_SQL:
            _, _, notebook_id, group_id, name, position, created_by = p
            assert group_id not in db.groups
            now = db.tick()
            db.groups[group_id] = {"notebook_id": notebook_id, "group_id": group_id, "name": name, "position": position,
                                   "created_by": created_by, "created_at": now, "updated_at": now}
            return _Result([(1,)])
        if sql == sg._RENAME_SQL:
            g = db.groups[p[3]]
            assert g["notebook_id"] == p[2]
            g["name"], g["updated_at"] = p[4], db.tick()
            return _Result([(1,)])
        if sql == sg._POSITION_SQL:
            g = db.groups[p[3]]
            g["position"], g["updated_at"] = p[4], db.tick()
            return _Result([(1,)])
        if sql == sg._DELETE_GROUP_SQL:
            g = db.groups.pop(p[3])
            assert g["notebook_id"] == p[2]
            for key in [k for k, m in db.members.items() if m["group_id"] == p[3]]:  # FK cascade
                del db.members[key]
            return _Result([(1,)])
        if sql == sg._MOVED_SQL:
            return _Result([(sum(1 for (nb, s), m in db.members.items() if nb == p[2] and s in p[4] and m["group_id"] != p[3]),)])
        if sql == sg._CLEAR_MEMBERS_SQL:
            for key in [k for k, m in db.members.items() if k[0] == p[2] and (m["group_id"] == p[3] or k[1] in p[4])]:
                del db.members[key]
            return _Result([])
        if sql == sg._INSERT_MEMBER_SQL:
            _, _, notebook_id, group_id, source_id, position = p
            assert (notebook_id, source_id) not in db.members
            assert db.groups[group_id]["notebook_id"] == notebook_id
            db.members[(notebook_id, source_id)] = {"group_id": group_id, "position": position}
            return _Result([])
        if sql == sg._TOUCH_SQL:
            db.groups[p[3]]["updated_at"] = db.tick()
            return _Result([(1,)])
        raise AssertionError(f"unexpected SQL {sql}")


def gid_ok(value):
    return re.fullmatch(r"sg-[0-9a-f]{32}", value) is not None


class SourceGroupsServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self.service = SourceGroupsService(self.db)

    def create(self, name, key=None, notebook="notebook-1", context=CTX):
        self._n = getattr(self, "_n", 0) + 1
        return self.service.create(context, notebook, name=name, idempotency_key=key or f"idem-key-{self._n:010d}")

    def etag(self, notebook="notebook-1", context=CTX):
        return self.service.list(context, notebook).etag

    def test_empty_list_has_groups_key_and_stable_etag(self):
        first = self.service.list(CTX, "notebook-1")
        second = self.service.list(CTX, "notebook-1")
        self.assertEqual(first.data, {"groups": []})
        self.assertEqual(first.etag, second.etag)
        self.assertRegex(first.etag, r'^"sg-[0-9a-f]{32}"$')

    def test_create_returns_group_id_and_appends_position(self):
        a = self.create("계약 조건")
        b = self.create("  가격  ")
        self.assertTrue(gid_ok(a.data["group_id"]) and gid_ok(b.data["group_id"]))
        self.assertEqual(set(a.data), {"group_id"})
        self.assertFalse(a.replayed)
        groups = self.service.list(CTX, "notebook-1").data["groups"]
        self.assertEqual([(g["name"], g["position"], g["source_ids"]) for g in groups], [("계약 조건", 0, []), ("가격", 1, [])])
        self.assertEqual(list(groups[0]), ["group_id", "name", "position", "source_ids"])
        self.assertEqual(b.etag, self.etag())
        self.assertEqual(self.db.groups[a.data["group_id"]]["created_by"], "actor-1")

    def test_create_with_same_idempotency_key_replays(self):
        first = self.create("묶음", key=KEY)
        again = self.create("묶음", key=KEY)
        self.assertEqual(first.data, again.data)
        self.assertTrue(again.replayed)
        self.assertEqual(len(self.db.groups), 1)
        with self.assertRaises(SourceGroupsError) as caught:
            self.create("다른 이름", key=KEY)
        self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_GROUP_IDEMPOTENCY_KEY_REUSED", 409))
        # 같은 키라도 사용자가 다르면 다른 묶음이다.
        other = self.create("묶음", key=KEY, context=OTHER)
        self.assertNotEqual(other.data["group_id"], first.data["group_id"])

    def test_name_length_is_1_to_80(self):
        self.assertEqual(self.create("가" * 80).data["group_id"][:3], "sg-")
        for bad in ("", "   ", "가" * 81, "줄\n바꿈", "탭\t", None, 3):
            with self.subTest(name=bad), self.assertRaises(SourceGroupsError) as caught:
                self.create(bad)
            self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_GROUP_INVALID", 422))
        self.assertEqual(len(self.db.groups), 1)

    def test_limit_50_groups_per_notebook(self):
        for index in range(sg.MAX_GROUPS):
            self.create(f"묶음 {index}")
        with self.assertRaises(SourceGroupsError) as caught:
            self.create("하나 더")
        self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_GROUP_LIMIT", 409))
        self.assertEqual(sg.MAX_GROUPS, 50)
        # 다른 노트북은 따로 센다.
        self.assertTrue(gid_ok(self.create("다른 노트북", notebook="notebook-2").data["group_id"]))

    def test_unknown_notebook_is_404(self):
        for call in (lambda: self.service.list(CTX, "notebook-x"), lambda: self.create("묶음", notebook="notebook-x")):
            with self.assertRaises(SourceGroupsError) as caught:
                call()
            self.assertEqual((caught.exception.code, caught.exception.status), ("NOTEBOOK_NOT_FOUND", 404))

    def test_set_members_keeps_order_and_moves_from_other_group(self):
        a = self.create("A").data["group_id"]
        b = self.create("B").data["group_id"]
        r1 = self.service.set_members(CTX, "notebook-1", a, ["src-c", "src-a", "src-b"], expected_etag=self.etag())
        self.assertEqual(r1.moved, 0)
        self.assertEqual(r1.data["groups"][0]["source_ids"], ["src-c", "src-a", "src-b"])
        r2 = self.service.set_members(CTX, "notebook-1", b, ["src-a", "src-d"], expected_etag=r1.etag)
        self.assertEqual(r2.moved, 1)
        groups = {g["group_id"]: g["source_ids"] for g in self.service.list(CTX, "notebook-1").data["groups"]}
        self.assertEqual(groups, {a: ["src-c", "src-b"], b: ["src-a", "src-d"]})
        self.assertEqual(r2.data, self.service.list(CTX, "notebook-1").data)
        # 빈 목록은 묶음을 비운다(소스는 묶음 밖으로).
        r3 = self.service.set_members(CTX, "notebook-1", a, [], expected_etag=r2.etag)
        self.assertEqual({g["group_id"]: g["source_ids"] for g in r3.data["groups"]}, {a: [], b: ["src-a", "src-d"]})

    def test_source_not_in_notebook_is_422_and_nothing_changes(self):
        a = self.create("A").data["group_id"]
        self.service.set_members(CTX, "notebook-1", a, ["src-a"], expected_etag=self.etag())
        before = copy.deepcopy(self.db.members)
        for ids in (["src-b", "src-x"], ["src-zzz"]):
            with self.subTest(ids=ids), self.assertRaises(SourceGroupsError) as caught:
                self.service.set_members(CTX, "notebook-1", a, ids, expected_etag=self.etag())
            self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_NOT_IN_NOTEBOOK", 422))
        self.assertEqual(self.db.members, before)

    def test_unbound_deleted_or_denied_source_is_hidden_and_cannot_be_added(self):
        a = self.create("A").data["group_id"]
        self.service.set_members(CTX, "notebook-1", a, ["src-a", "src-b", "src-c"], expected_etag=self.etag())
        # 떼어짐(unbinding)·삭제 요청은 노트북 소스 목록 판정에서 빠진다 → 묶음 조회에서도 숨긴다.
        self.db.in_notebook["notebook-1"] -= {"src-b"}
        self.assertEqual(self.service.list(CTX, "notebook-1").data["groups"][0]["source_ids"], ["src-a", "src-c"])
        # 행은 지우지 않는다(정본 표 변화에 맞춰 쓰지 않음). 다시 연결되면 다시 보인다.
        self.assertIn(("notebook-1", "src-b"), self.db.members)
        with self.assertRaises(SourceGroupsError) as caught:
            self.service.set_members(CTX, "notebook-1", a, ["src-b"], expected_etag=self.etag())
        self.assertEqual(caught.exception.code, "SOURCE_NOT_IN_NOTEBOOK")
        # 내 접근이 거부된 소스도 노트북 소스 목록과 같이 숨긴다.
        self.db.denied["actor-2"] = {"src-a"}
        self.assertEqual(self.service.list(OTHER, "notebook-1").data["groups"][0]["source_ids"], ["src-c"])
        self.assertEqual(self.service.list(CTX, "notebook-1").data["groups"][0]["source_ids"], ["src-a", "src-c"])

    def test_members_input_validation(self):
        a = self.create("A").data["group_id"]
        for ids in (["src-a", "src-a"], ["bad id"], "src-a", [1], ["s"] * (sg.MAX_MEMBERS + 1)):
            with self.subTest(ids=str(ids)[:30]), self.assertRaises(SourceGroupsError) as caught:
                self.service.set_members(CTX, "notebook-1", a, ids, expected_etag=self.etag())
            self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_GROUP_INVALID", 422))

    def test_group_in_other_notebook_or_unknown_is_404(self):
        x = self.create("다른 노트북", notebook="notebook-2").data["group_id"]
        for gid in (x, "sg-" + "0" * 32):
            with self.subTest(gid=gid):
                for call in (lambda: self.service.update(CTX, "notebook-1", gid, name="새", expected_etag=self.etag()),
                             lambda: self.service.delete(CTX, "notebook-1", gid, expected_etag=self.etag()),
                             lambda: self.service.set_members(CTX, "notebook-1", gid, [], expected_etag=self.etag())):
                    with self.assertRaises(SourceGroupsError) as caught:
                        call()
                    self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_GROUP_NOT_FOUND", 404))
        self.assertIn(x, self.db.groups)

    def test_rename_and_move_position(self):
        a = self.create("A").data["group_id"]
        b = self.create("B").data["group_id"]
        c = self.create("C").data["group_id"]
        r = self.service.update(CTX, "notebook-1", a, name="가", expected_etag=self.etag())
        self.assertEqual([g["name"] for g in r.data["groups"]], ["가", "B", "C"])
        r = self.service.update(CTX, "notebook-1", c, position=0, expected_etag=r.etag)
        self.assertEqual([(g["group_id"], g["position"]) for g in r.data["groups"]], [(c, 0), (a, 1), (b, 2)])
        r = self.service.update(CTX, "notebook-1", c, position=49, expected_etag=r.etag)  # 끝을 넘으면 맨 끝
        self.assertEqual([g["group_id"] for g in r.data["groups"]], [a, b, c])
        self.assertEqual([g["position"] for g in r.data["groups"]], [0, 1, 2])
        for bad in ({}, {"position": -1}, {"position": 50}, {"position": True}, {"name": ""}):
            with self.subTest(bad=bad), self.assertRaises(SourceGroupsError) as caught:
                self.service.update(CTX, "notebook-1", a, expected_etag=r.etag, **bad)
            self.assertEqual(caught.exception.code, "SOURCE_GROUP_INVALID")

    def test_delete_keeps_sources_and_releases_members(self):
        a = self.create("A").data["group_id"]
        b = self.create("B").data["group_id"]
        self.service.set_members(CTX, "notebook-1", a, ["src-a", "src-b"], expected_etag=self.etag())
        r = self.service.delete(CTX, "notebook-1", a, expected_etag=self.etag())
        self.assertEqual(r.removed, 2)
        self.assertEqual(r.data, {"groups": [{"group_id": b, "name": "B", "position": 1, "source_ids": []}]})
        self.assertEqual(self.db.members, {})
        # 소스 자체(노트북 소스 목록)는 그대로다. 묶음 밖 소스는 다른 묶음으로 옮길 수 있다.
        self.assertEqual(self.db.in_notebook["notebook-1"], {"src-a", "src-b", "src-c", "src-d"})
        self.service.set_members(CTX, "notebook-1", b, ["src-a"], expected_etag=r.etag)

    def test_stale_etag_is_412_and_nothing_changes(self):
        a = self.create("A").data["group_id"]
        stale = self.etag()
        self.create("B")
        for call in (lambda: self.service.update(CTX, "notebook-1", a, name="새", expected_etag=stale),
                     lambda: self.service.delete(CTX, "notebook-1", a, expected_etag=stale),
                     lambda: self.service.set_members(CTX, "notebook-1", a, ["src-a"], expected_etag=stale),
                     lambda: self.service.set_members(CTX, "notebook-1", a, ["src-a"], expected_etag="*")):
            with self.assertRaises(SourceGroupsError) as caught:
                call()
            self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_GROUP_ETAG_MISMATCH", 412))
        self.assertEqual(self.db.groups[a]["name"], "A")
        self.assertEqual(self.db.members, {})

    def test_every_mutation_takes_notebook_advisory_lock_first(self):
        a = self.create("A").data["group_id"]
        self.service.update(CTX, "notebook-1", a, name="B", expected_etag=self.etag())
        self.service.set_members(CTX, "notebook-1", a, ["src-a"], expected_etag=self.etag())
        self.service.delete(CTX, "notebook-1", a, expected_etag=self.etag())
        self.assertEqual(self.db.locks, ["source-groups|tenant-1|workspace-1|notebook-1"] * 4)
        writes = [i for i, (sql, _) in enumerate(self.db.executed) if sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE"))]
        locks = [i for i, (sql, _) in enumerate(self.db.executed) if sql == sg._LOCK_SQL]
        self.assertTrue(writes and locks and locks[0] < writes[0])

    def test_sql_never_writes_or_locks_canon_tables(self):
        texts = [value for name, value in vars(sg).items() if name.endswith("_SQL") and isinstance(value, str)]
        self.assertGreaterEqual(len(texts), 10)
        for text in texts:
            upper = text.upper()
            self.assertNotIn("FOR UPDATE", upper)
            self.assertNotIn("FOR SHARE", upper)
            self.assertNotRegex(upper, r"\bLOCK\s+TABLE\b")
            for canon in CANON:
                self.assertNotRegex(text, rf"(?i)\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(public\.)?{canon}\b")
            written = re.findall(r"(?i)\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:public\.)?([a-z_]+)", text)
            self.assertTrue(set(written) <= {"source_groups", "source_group_members"}, (written, text))

    def test_in_notebook_rule_matches_notebook_source_list(self):
        # 노트북 소스 목록 판정(notebook_postgres.read_selected_context)과 같은 조건을 쓴다.
        for text in (sg._VISIBLE_MEMBERS_SQL, sg._IN_NOTEBOOK_SQL):
            for fragment in ("notebook_bindings", "binding_kind='source'", "notebook_source_unbindings",
                             "deletion_requests", "source_active=false", "identity_auth_source_access", "allowed=0"):
                self.assertIn(fragment, text)

    def test_capabilities_and_database_failure(self):
        self.service.list(CTX, "notebook-1")
        self.create("A")
        self.assertEqual([s[3] for s in self.db.scopes], ["source_groups.read", "source_groups.write"])
        self.db.fail = True
        with self.assertRaises(SourceGroupsError) as caught:
            self.service.list(CTX, "notebook-1")
        self.assertEqual((caught.exception.code, caught.exception.status), ("SOURCE_GROUPS_UNAVAILABLE", 503))

    def test_question_service_is_untouched(self):
        # 정정 C-4: 묶음은 화면 편의다. 질문 범위 상한(8개)과 질문 서비스는 이 모듈을 쓰지 않는다.
        import pathlib
        root = pathlib.Path(sg.__file__).parent
        for path in root.glob("question_answering*.py"):
            self.assertNotIn("source_group", path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
