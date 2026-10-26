"""가상 MCP 서버(Daon2-RAG·Daon2 대역). 운영 기동 금지. 표준 라이브러리만 쓴다. WO-M0 T-M0-04.

- JSON-RPC over HTTP(POST /mcp). 판본: 2026-07-28(server/discover) 또는 2025-06-18(initialize) — MCP_VIRTUAL_PROTOCOL.
- 인증: Authorization Bearer(HS256 JWT) aud/scope/허용 쌍 검사. 시험 모드(MCP_VIRTUAL_FAULTS=true)에서 X-Virtual-Fault 결함 주입.
- 결과는 결정적이다(점수 내림차순, 동률은 block_id 오름차순).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from .contracts import AUDIENCES, SERVERS
from .fixtures import CONCEPTS, RULESETS, build_documents

MAX_RESPONSE_BYTES = 1024 * 1024
PROTOCOLS = ("2026-07-28", "2025-06-18", "2025-11-25")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(key: bytes, *, aud: str, pairs: list[dict[str, str]] | None = None, scopes: list[str] | None = None, ttl: int = 3600, now: float | None = None) -> str:
    """시험·시드용 HS256 토큰."""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"aud": aud, "exp": int((now if now is not None else time.time()) + ttl), "scope": scopes or ["read"], "pairs": pairs or []}
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signature = _b64(hmac.new(key, f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def verify_token(key: bytes, token: str, audience: str, now: float | None = None) -> Mapping[str, Any] | None:
    try:
        header, body, signature = token.split(".")
        expected = _b64(hmac.new(key, f"{header}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if claims.get("aud") != audience or claims.get("exp", 0) < (now if now is not None else time.time()):
        return None
    return claims


def _grams(text: str) -> set[str]:
    clean = re.sub(r"\s+", "", text.lower())
    return {clean[i:i + 2] for i in range(len(clean) - 1)} if len(clean) > 1 else {clean}


def _score(query: str, text: str) -> float:
    q, t = _grams(query), _grams(text)
    return round(len(q & t) / len(q), 4) if q else 0.0


class ToolError(Exception):
    def __init__(self, code: str, status: int = 200) -> None:
        super().__init__(code)
        self.code, self.status = code, status


class VirtualServer:
    def __init__(self, kind: str, key: bytes, *, protocol: str = "2026-07-28", faults: bool = False, admin_token: str | None = None) -> None:
        if kind not in SERVERS:
            raise ValueError("VIRTUAL_MCP_KIND_INVALID")
        if os.environ.get("ENV") == "production" or os.environ.get("DAON_RUNTIME_PROFILE") == "production":
            raise RuntimeError("VIRTUAL_MCP_FORBIDDEN_IN_PRODUCTION")
        self.kind, self.key, self.protocol, self.faults, self.admin_token = kind, key, protocol, faults, admin_token
        self.tools = SERVERS[kind]
        self.audience = AUDIENCES[kind]
        self.reset()

    def reset(self) -> None:
        self.documents = {d["document_id"]: copy.deepcopy(d) for d in build_documents()}
        self.versions = {doc_id: d["version_id"] for doc_id, d in self.documents.items()}
        self._bumped: set[str] = set()

    def bump_version(self, document_id: str | None = None) -> str:
        """문서 버전을 올린다(stale 시험). document_id가 없으면 첫 문서."""
        doc_id = document_id or sorted(self.documents)[0]
        new_version = f"{self.documents[doc_id]['version_id']}-v2"
        self.versions[doc_id] = new_version
        self._bumped.add(doc_id)
        return doc_id

    # ---------------------------------------------------------------- 입구
    def handle(self, headers: Mapping[str, str], body: bytes, path: str = "/mcp") -> tuple[int, dict[str, str], bytes]:
        h = {k.lower(): v for k, v in headers.items()}
        if path.startswith("/_admin/"):
            return self._admin(h, path, body)
        fault = h.get("x-virtual-fault", "") if self.faults else ""
        if fault == "timeout":
            time.sleep(30)
        if fault.startswith("delay="):
            time.sleep(min(int(fault.split("=", 1)[1] or 0), 30000) / 1000)
        auth = h.get("authorization", "")
        if not auth.startswith("Bearer "):
            return self._http(401, {"error": "unauthenticated"})
        claims = verify_token(self.key, auth[7:], self.audience)
        if claims is None:
            return self._http(401, {"error": "unauthenticated"})
        if fault == "forbidden":
            return self._http(403, {"error": "forbidden"})
        try:
            request = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._rpc_error(None, -32700, "parse")
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return self._rpc_error(None, -32600, "invalid")
        rid, method, params = request.get("id"), request.get("method"), request.get("params") or {}
        if rid is None:  # 알림
            return 202, {}, b""
        try:
            result = self._dispatch(method, params, claims, fault)
        except ToolError as error:
            if error.code == "METHOD_NOT_FOUND":
                return self._rpc_error(rid, -32601, "method not found")
            return self._rpc_error(rid, -32000, error.code, {"code": error.code, "retryable": error.code in {"UNAVAILABLE", "NOT_READY"}}, status=error.status)
        payload = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}, ensure_ascii=False, separators=(",", ":")).encode()
        if len(payload) > MAX_RESPONSE_BYTES:
            return self._rpc_error(rid, -32000, "LIMIT_EXCEEDED", {"code": "LIMIT_EXCEEDED"})
        headers_out = {"Content-Type": "application/json"}
        if method == "initialize" and self.protocol != "2026-07-28":
            headers_out["Mcp-Session-Id"] = "virtual-session"
        return 200, headers_out, payload

    @staticmethod
    def _http(status: int, payload: Mapping[str, Any]) -> tuple[int, dict[str, str], bytes]:
        return status, {"Content-Type": "application/json"}, json.dumps(payload).encode()

    @staticmethod
    def _rpc_error(rid: Any, code: int, message: str, data: Mapping[str, Any] | None = None, status: int = 200):  # type: ignore[no-untyped-def]
        body = {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message, **({"data": dict(data)} if data else {})}}
        return status, {"Content-Type": "application/json"}, json.dumps(body, ensure_ascii=False).encode()

    def _admin(self, h: Mapping[str, str], path: str, body: bytes):  # type: ignore[no-untyped-def]
        if not self.admin_token or h.get("authorization") != f"Bearer {self.admin_token}":
            return self._http(401, {"error": "unauthenticated"})
        if path == "/_admin/reset":
            self.reset()
            return self._http(200, {"ok": True})
        if path == "/_admin/bump-version":
            requested = json.loads(body or b"{}").get("document_id") if body else None
            return self._http(200, {"document_id": self.bump_version(requested)})
        return self._http(404, {"error": "not_found"})

    # ---------------------------------------------------------------- 프로토콜
    def _dispatch(self, method: str, params: Mapping[str, Any], claims: Mapping[str, Any], fault: str) -> Mapping[str, Any]:
        info = {"name": f"knowledge-{self.kind}-virtual", "version": "0.1.0", "virtual": True}
        if method == "server/discover":
            if self.protocol != "2026-07-28":
                raise ToolError("METHOD_NOT_FOUND")
            return {"supportedVersions": [self.protocol], "serverInfo": info, "capabilities": {"tools": {}, "resources": {}}}
        if method == "initialize":
            if self.protocol == "2026-07-28":
                raise ToolError("METHOD_NOT_FOUND")
            return {"protocolVersion": self.protocol, "serverInfo": info, "capabilities": {"tools": {}, "resources": {}}}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [{"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"], "outputSchema": spec["outputSchema"]}
                              for name, spec in self.tools.items()]}
        if method == "tools/call":
            name = params.get("name")
            if name not in self.tools:
                raise ToolError("NOT_FOUND")
            return self._call_tool(name, params.get("arguments") or {}, claims, fault)
        if method == "resources/read":
            return self._read_resource(str(params.get("uri", "")), claims)
        raise ToolError("METHOD_NOT_FOUND")

    def _scoped(self, args: Mapping[str, Any], claims: Mapping[str, Any]) -> list[dict[str, Any]]:
        pair = {"project_id": args.get("project_id"), "work_package_id": args.get("work_package_id")}
        if pair not in claims.get("pairs", []):
            raise ToolError("SCOPE_FORBIDDEN", status=403)
        return [d for d in self.documents.values() if d["project_id"] == pair["project_id"] and d["work_package_id"] == pair["work_package_id"]]

    def _document(self, args: Mapping[str, Any], claims: Mapping[str, Any]) -> dict[str, Any]:
        docs = {d["document_id"]: d for d in self._scoped(args, claims)}
        doc = docs.get(str(args.get("document_id")))
        if doc is None:
            raise ToolError("NOT_FOUND")  # 타 scope 문서는 존재를 드러내지 않는다
        return doc

    @staticmethod
    def _uri(doc: Mapping[str, Any], block_id: str) -> str:
        return f"virtual-rag://documents/{doc['document_id']}/versions/{doc['version_id']}/runs/{doc['run_id']}/blocks/{block_id}"

    def _result(self, doc: Mapping[str, Any], block: Mapping[str, Any], score: float) -> dict[str, Any]:
        return {"document_id": doc["document_id"], "version_id": doc["version_id"], "run_id": doc["run_id"], "block_id": block["block_id"], "page": block["page"],
                "excerpt": block["text"][:8000], "score": score, "score_kind": "ngram_overlap", "resource_uri": self._uri(doc, block["block_id"])}

    def _call_tool(self, name: str, args: Mapping[str, Any], claims: Mapping[str, Any], fault: str) -> Mapping[str, Any]:
        if fault == "not_ready":
            raise ToolError("NOT_READY")
        if fault == "empty":
            data: dict[str, Any] = {"results": [], "documents": [], "concepts": [], "items": []}
            return self._wrap(name, {k: v for k, v in data.items() if k in self.tools[name]["outputSchema"]["required"]})
        if fault == "invalid_schema":
            return {"structuredContent": {"unexpected": True}, "content": [{"type": "text", "text": "{}"}], "isError": False}
        out = getattr(self, f"_t_{name}")(args, claims)
        if fault == "model_mismatch" and name == "search_document_evidence":
            out = {**out, "model_mismatch": True}
        return self._wrap(name, out)

    @staticmethod
    def _wrap(name: str, structured: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"structuredContent": structured, "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)[:2000]}], "isError": False}

    def _read_resource(self, uri: str, claims: Mapping[str, Any]) -> Mapping[str, Any]:
        match = re.fullmatch(r"virtual-rag://documents/([^/]+)/versions/([^/]+)/runs/([^/]+)/blocks/([^/]+)", uri)
        if not match:
            raise ToolError("INVALID_ARGUMENT")
        for doc in self.documents.values():
            allowed = {"project_id": doc["project_id"], "work_package_id": doc["work_package_id"]} in claims.get("pairs", [])
            if doc["document_id"] == match.group(1) and allowed:
                for block in doc["blocks"]:
                    if block["block_id"] == match.group(4):
                        return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": block["text"]}]}
        raise ToolError("NOT_FOUND")

    # ---------------------------------------------------------------- RAG 도구
    def _t_search_document_evidence(self, args, claims):  # type: ignore[no-untyped-def]
        docs = self._scoped(args, claims)
        if args.get("document_id"):
            docs = [d for d in docs if d["document_id"] == args["document_id"]]
        limit = int(args.get("limit", 5))
        scored = [(self._result(d, b, _score(str(args["question"]), b["text"])), ) for d in docs for b in d["blocks"]]
        ranked = sorted((s[0] for s in scored if s[0]["score"] > 0), key=lambda r: (-r["score"], r["block_id"]))
        return {"results": ranked[:limit]}

    def _t_get_document_evidence(self, args, claims):  # type: ignore[no-untyped-def]
        doc = self._document(args, claims)
        for block in doc["blocks"]:
            if block["block_id"] == args["block_id"]:
                return {"evidence": self._result(doc, block, 1.0)}
        raise ToolError("NOT_FOUND")

    def _t_list_documents(self, args, claims):  # type: ignore[no-untyped-def]
        docs = self._scoped(args, claims)
        if args.get("document_type"):
            docs = [d for d in docs if d["document_type"] == args["document_type"]]
        return {"documents": [{"document_id": d["document_id"], "title": d["title"], "document_type": d["document_type"], "version_id": self.versions[d["document_id"]]}
                              for d in sorted(docs, key=lambda d: d["document_id"])]}

    def _t_get_document_outline(self, args, claims):  # type: ignore[no-untyped-def]
        doc = self._document(args, claims)
        return {"document_id": doc["document_id"], "version_id": self.versions[doc["document_id"]], "nodes": doc["outline"]}

    def _t_read_document_section(self, args, claims):  # type: ignore[no-untyped-def]
        doc = self._document(args, claims)
        node = next((n for n in doc["outline"] if n["node_id"] == args["node_id"]), None)
        if node is None:
            raise ToolError("NOT_FOUND")
        blocks = {b["block_id"]: b for b in doc["blocks"]}
        start = int(args.get("cursor") or 0)
        chosen = node["block_ids"][start:start + 20]
        nxt = str(start + 20) if start + 20 < len(node["block_ids"]) else None
        return {"node_id": node["node_id"], "blocks": [{"block_id": i, "page": blocks[i]["page"], "text": blocks[i]["text"], "resource_uri": self._uri(doc, i)} for i in chosen],
                "next_cursor": nxt}

    def _t_get_document_version_status(self, args, claims):  # type: ignore[no-untyped-def]
        doc = self._document(args, claims)
        current = self.versions[doc["document_id"]]
        return {"document_id": doc["document_id"], "current_version_id": current, "changed": current != args["version_id"]}

    # ---------------------------------------------------------------- Daon2 도구
    def _t_ontology_search_concepts(self, args, claims):  # type: ignore[no-untyped-def]
        query = str(args["query"])
        scored = [(max(_score(query, c["label"]), *(_score(query, s) for s in c["synonyms"])), c) for c in CONCEPTS]
        hits = sorted([(s, c) for s, c in scored if s > 0], key=lambda x: (-x[0], x[1]["concept_id"]))
        return {"concepts": [c for _, c in hits[:int(args.get("limit", 10))]]}

    def _t_ontology_get_concept(self, args, claims):  # type: ignore[no-untyped-def]
        concept = next((c for c in CONCEPTS if c["concept_id"] == args["concept_id"]), None)
        if concept is None:
            raise ToolError("NOT_FOUND")
        return {"concept": concept}

    def _t_ruleset_list(self, args, claims):  # type: ignore[no-untyped-def]
        items = [r for r in RULESETS if not args.get("applies_to") or r["applies_to"] == args["applies_to"]]
        return {"rulesets": [{k: r[k] for k in ("ruleset_id", "title", "version", "applies_to")} for r in items]}

    def _t_ruleset_get(self, args, claims):  # type: ignore[no-untyped-def]
        ruleset = next((r for r in RULESETS if r["ruleset_id"] == args["ruleset_id"]), None)
        if ruleset is None:
            raise ToolError("NOT_FOUND")
        return {"ruleset": ruleset}

    def _t_ruleset_evaluate(self, args, claims):  # type: ignore[no-untyped-def]
        ruleset = next((r for r in RULESETS if r["ruleset_id"] == args["ruleset_id"]), None)
        if ruleset is None:
            raise ToolError("NOT_FOUND")
        sections = args["draft"]["sections"]
        results = []
        for rule in ruleset["rules"]:
            needle = rule["must_contain"]
            hit = next((s for s in sections if needle in s["title"] or needle in s["text"]), None)
            results.append({"rule_id": rule["rule_id"], "status": "pass" if hit else "fail", **({"section_id": hit["id"]} if hit else {}), "evidence_refs": [],
                            "message": rule["description"] if not hit else f"'{needle}' 확인"})
        return {"results": results}

    def _t_approved_knowledge_search(self, args, claims):  # type: ignore[no-untyped-def]
        query = str(args["query"])
        items = []
        for doc in self.documents.values():
            if doc["document_type"] not in {"insurance_terms", "proposal"}:
                continue
            for block in doc["blocks"]:
                score = _score(query, block["text"])
                if score > 0:
                    items.append({"knowledge_id": f"{doc['document_id']}:{block['block_id']}", "title": doc["title"], "excerpt": block["text"][:500], "score": score})
        items.sort(key=lambda i: (-i["score"], i["knowledge_id"]))
        return {"items": items[:int(args.get("limit", 5))]}

    def _law_articles(self) -> list[dict[str, str]]:
        """가상 법령 문서의 조문(제목 블록 = 조 제목, 다음 블록들 = 본문)."""
        articles: list[dict[str, str]] = []
        for doc in self.documents.values():
            if doc["document_type"] != "law":
                continue
            current: dict[str, str] | None = None
            for block in doc["blocks"]:
                if block["text"].startswith("제") and "조(" in block["text"].split()[0]:
                    current = {"law_id": doc["document_id"], "law_title": doc["title"], "article": block["text"], "text": ""}
                    articles.append(current)
                elif current is not None:
                    current["text"] = (current["text"] + " " + block["text"]).strip()
        return articles

    def _t_search_law(self, args, claims):  # type: ignore[no-untyped-def]
        query = str(args["query"])
        found = []
        for article in self._law_articles():
            score = _score(query, article["article"] + " " + article["text"])
            if score > 0:
                found.append({"law_id": article["law_id"], "law_title": article["law_title"], "article": article["article"], "excerpt": article["text"][:300], "score": score})
        found.sort(key=lambda a: (-a["score"], a["article"]))
        return {"articles": found[:int(args.get("limit", 5))]}

    def _t_get_law_text(self, args, claims):  # type: ignore[no-untyped-def]
        for article in self._law_articles():
            if article["law_id"] == args["law_id"] and article["article"].startswith(str(args["article"])):
                return dict(article)
        raise ToolError("NOT_FOUND")


class _Handler(BaseHTTPRequestHandler):
    server_version = "VirtualMcp/0.1"
    virtual: VirtualServer

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_RESPONSE_BYTES:
            self.send_error(413)
            return
        status, headers, payload = self.virtual.handle(dict(self.headers), self.rfile.read(length), self.path)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:  # 토큰·본문을 로그에 남기지 않는다.
        return


def serve(kind: str, host: str, port: int, key: bytes, **options: Any) -> ThreadingHTTPServer:
    virtual = VirtualServer(kind, key, **options)
    handler = type("Handler", (_Handler,), {"virtual": virtual})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.virtual = virtual  # type: ignore[attr-defined]
    return httpd


def main() -> None:
    kind = os.environ.get("MCP_VIRTUAL_KIND", "rag")
    key = open(os.environ["MCP_VIRTUAL_JWT_KEY_FILE"], "rb").read().strip()
    admin = open(os.environ["MCP_VIRTUAL_ADMIN_TOKEN_FILE"]).read().strip() if os.environ.get("MCP_VIRTUAL_ADMIN_TOKEN_FILE") else None
    httpd = serve(kind, os.environ.get("MCP_VIRTUAL_HOST", "0.0.0.0"), int(os.environ.get("MCP_VIRTUAL_PORT", "8641")), key,
                  protocol=os.environ.get("MCP_VIRTUAL_PROTOCOL", "2026-07-28"), faults=os.environ.get("MCP_VIRTUAL_FAULTS") == "true", admin_token=admin)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
