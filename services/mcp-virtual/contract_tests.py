"""MCP 계약 시험 모음(가상·실제 서버 공용). WO-M0 T-M0-10.

사용: python contract_tests.py --url http://host:8641/mcp --token-file token.txt --kind rag|ops --pair proj-alpha:wp-terms --json report.json
`required` 항목이 모두 통과해야 합격이다. `pending`은 요청 항목이 수용되기 전에는 실패해도 합격을 막지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

sys.path.insert(0, __file__.rsplit("contract_tests.py", 1)[0])
from mcp_virtual.contracts import SERVERS  # noqa: E402


class Rpc:
    def __init__(self, url: str, token: str | None) -> None:
        self.url, self.token, self.n, self.version, self.session = url, token, 0, None, None

    def call(self, method: str, params: dict | None = None, *, token: str | None = "default") -> tuple[int, dict]:
        self.n += 1
        headers = {"Content-Type": "application/json"}
        use = self.token if token == "default" else token
        if use:
            headers["Authorization"] = f"Bearer {use}"
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        body = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, **({"params": params} if params is not None else {})}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url, body, headers, "POST"), timeout=30) as r:
                self.session = r.headers.get("Mcp-Session-Id", self.session)
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}


def validate(value: Any, schema: dict, path: str = "$") -> list[str]:
    t = schema.get("type")
    errors: list[str] = []
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float), "null": type(None)}
    if t is not None:
        opts = t if isinstance(t, list) else [t]
        if not any(isinstance(value, types[o]) and not (o != "boolean" and isinstance(value, bool)) for o in opts):
            return [f"{path}: type"]
    if isinstance(value, dict):
        errors += [f"{path}.{k}: required" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            if k in schema.get("properties", {}):
                errors += validate(v, schema["properties"][k], f"{path}.{k}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(value):
            errors += validate(v, schema["items"], f"{path}[{i}]")
    return errors


def run(url: str, token: str, kind: str, pair: dict[str, str]) -> dict:
    rpc = Rpc(url, token)
    results: list[dict] = []

    def case(name: str, category: str, level: str, fn: Callable[[], None]) -> None:
        try:
            fn()
            results.append({"name": name, "category": category, "level": level, "passed": True})
        except Exception as error:  # noqa: BLE001
            results.append({"name": name, "category": category, "level": level, "passed": False, "detail": str(error)[:200]})

    def discover() -> None:
        status, body = rpc.call("server/discover", {"supportedVersions": ["2026-07-28"]})
        if "result" in body:
            rpc.version = body["result"]["supportedVersions"][0]
            return
        status, body = rpc.call("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "contract", "version": "1"}})
        assert "result" in body, "neither discover nor initialize works"
        rpc.version = body["result"]["protocolVersion"]
        rpc.call("notifications/initialized")

    def tools() -> dict:
        status, body = rpc.call("tools/list", {})
        assert status == 200 and "result" in body, f"tools/list {status}"
        return {t["name"]: t for t in body["result"]["tools"]}

    def has_contract_tools() -> None:
        listed = tools()
        missing = set(SERVERS[kind]) - set(listed)
        assert not missing, f"missing tools {sorted(missing)}"

    def schemas_declared() -> None:
        for name, tool in tools().items():
            assert tool.get("inputSchema") and tool.get("outputSchema"), f"{name} lacks schemas"

    def sample_args(name: str) -> dict | None:
        if kind == "rag":
            lst = rpc.call("tools/call", {"name": "list_documents", "arguments": pair})[1]["result"]["structuredContent"]["documents"]
            doc = lst[0]
            return {"search_document_evidence": {**pair, "question": "보험금 지급"}, "list_documents": dict(pair),
                    "get_document_outline": {**pair, "document_id": doc["document_id"]},
                    "get_document_version_status": {**pair, "document_id": doc["document_id"], "version_id": doc["version_id"]}}.get(name)
        return {"ontology_search_concepts": {"query": "보험금"}, "ruleset_list": {}, "approved_knowledge_search": {"query": "보험금"}}.get(name)

    def outputs_match_schema() -> None:
        listed = tools()
        for name in SERVERS[kind]:
            args = sample_args(name)
            if args is None:
                continue
            status, body = rpc.call("tools/call", {"name": name, "arguments": args})
            assert status == 200 and "result" in body, f"{name} call {status}"
            problems = validate(body["result"]["structuredContent"], listed[name]["outputSchema"])
            assert not problems, f"{name}: {problems[:2]}"

    def auth_required() -> None:
        status, _ = rpc.call("tools/list", {}, token=None)
        assert status == 401, f"expected 401, got {status}"

    def bad_token() -> None:
        status, _ = rpc.call("tools/list", {}, token="x.y.z")
        assert status == 401, f"expected 401, got {status}"

    def scope_enforced() -> None:
        if kind != "rag":
            return
        status, body = rpc.call("tools/call", {"name": "list_documents", "arguments": {"project_id": "proj-secret", "work_package_id": "wp-hidden"}})
        assert status in (200, 403) and "error" in body, "foreign scope must be rejected"

    def deterministic() -> None:
        if kind != "rag":
            return
        a = rpc.call("tools/call", {"name": "search_document_evidence", "arguments": {**pair, "question": "보험금 지급 시기"}})[1]
        b = rpc.call("tools/call", {"name": "search_document_evidence", "arguments": {**pair, "question": "보험금 지급 시기"}})[1]
        assert a.get("result") == b.get("result"), "results differ between identical calls"

    def unknown_tool() -> None:
        _, body = rpc.call("tools/call", {"name": "no_such_tool", "arguments": {}})
        assert "error" in body, "unknown tool must error"

    case("discover/initialize", "discovery", "required", discover)
    case("계약 도구가 모두 있다", "discovery", "required", has_contract_tools)
    case("모든 도구에 입출력 스키마가 있다", "schema", "required", schemas_declared)
    case("출력이 스키마를 따른다", "schema", "required", outputs_match_schema)
    case("인증 없이는 거부된다", "auth", "required", auth_required)
    case("잘못된 토큰은 거부된다", "auth", "required", bad_token)
    case("허용되지 않은 scope는 거부된다", "scope", "required", scope_enforced)
    case("같은 질의는 같은 결과(결정성)", "evidence", "required", deterministic)
    case("알 수 없는 도구는 오류", "errors", "required", unknown_tool)
    required = [r for r in results if r["level"] == "required"]
    return {"url": url, "kind": kind, "passed": all(r["passed"] for r in required), "required_passed": sum(r["passed"] for r in required),
            "required_total": len(required), "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--kind", choices=["rag", "ops"], default="rag")
    parser.add_argument("--pair", default="proj-alpha:wp-terms")
    parser.add_argument("--json")
    args = parser.parse_args()
    project, package = args.pair.split(":", 1)
    report = run(args.url, open(args.token_file).read().strip(), args.kind, {"project_id": project, "work_package_id": package})
    if args.json:
        open(args.json, "w", encoding="utf-8").write(json.dumps(report, ensure_ascii=False, indent=2))
    for r in report["results"]:
        print(("PASS" if r["passed"] else "FAIL"), r["category"], r["name"], r.get("detail", ""))
    print(f"required {report['required_passed']}/{report['required_total']}")
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
