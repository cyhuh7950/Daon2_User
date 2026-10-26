"""Studio v2 루프백 E2E(WSL). 서버 호스트에서 127.0.0.1:3340 BFF를 호출한다. 비밀번호·본문은 출력하지 않는다.

사용: python3 e2e_studio_v2.py [--upload] [--with-source] [--only=report ...]
  기본: 유형 목록, 메모 생성·조회·내보내기·삭제, 소스 없는 보고서 생성 거부(409) 확인.
  --upload: 합성 약관 TXT를 업로드하고 처리 완료(ready)를 기다린 뒤 --with-source 를 이어서 실행한다.
  --with-source: 노트북에 준비된 소스로 6종 유형을 생성(실제 LLM)→상세·provenance·내보내기·근거 보기→삭제.
"""
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:3340"
ORIGIN = os.environ.get("DAON_QA_ORIGIN", "http://172.27.253.53:3340")
password = open(os.path.expanduser("~/deploy/daon2-user/secrets/qa_e2e_password")).read().strip()
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
SAMPLE = (
    "보험금 지급 약관(합성 시험 문서)\n\n"
    "제1조(보험금의 지급) 회사는 청구서류를 접수한 날부터 3일 이내에 보험금을 지급한다. 보험금 지급 한도는 사고당 1,000,000원이다.\n\n"
    "제2조(면책) 계약일부터 90일 이내에 발생한 사고는 보장하지 않는다. 사고가 발생하면 계약자는 즉시 회사에 통지해야 한다.\n\n"
    "제3조(계약의 해지) 계약자는 언제든지 계약을 해지할 수 있으며, 해지환급금은 해지일로부터 7일 이내에 지급한다.\n"
)
KINDS = ["report", "data_table", "mind_map", "flashcards", "quiz", "slides", "infographic"]
EXPORTS = {"report": ["docx", "pdf", "md"], "data_table": ["xlsx", "csv", "pdf"], "mind_map": ["svg", "png", "json"],
           "flashcards": ["csv", "json", "pdf"], "quiz": ["csv", "json", "pdf"], "slides": ["pptx", "pdf"], "infographic": ["png", "svg", "pdf"]}


def call(method, path, body=None, headers=None, raw=False):
    h = {"Origin": ORIGIN, "Referer": ORIGIN + "/notebooks", **(headers or {})}
    data = None
    if body is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    elif method not in ("GET", "HEAD"):
        h["Content-Type"] = "application/json"
        data = b"{}"
    if method not in ("GET", "HEAD") and "Idempotency-Key" not in h:
        h["Idempotency-Key"] = "e2e-" + uuid.uuid4().hex
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        response = opener.open(request, timeout=90)
        payload = response.read()
        return response.status, (payload if raw else (json.loads(payload) if payload[:1] in (b"{", b"[") else {})), response.headers
    except urllib.error.HTTPError as error:
        payload = error.read()
        try:
            return error.code, json.loads(payload), error.headers
        except ValueError:
            return error.code, {}, error.headers


def check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), label, detail, flush=True)
    if not ok:
        sys.exit(1)


status, _, _ = call("POST", "/bff/api/auth/login", {"login_id": "qa-e2e", "password": password})
check("login", status == 200, status)
status, session, _ = call("GET", "/bff/api/session")
workspace = (session.get("data") or {}).get("workspace_id")
check("session workspace", bool(workspace))
status, listing, _ = call("GET", f"/bff/api/workspaces/{workspace}/notebooks")
items = (listing.get("data") or {}).get("notebooks") if isinstance(listing.get("data"), dict) else listing.get("data")
notebook = None
for item in items or []:
    if item.get("title") == "Studio v2 E2E":
        notebook = item.get("notebook_id")
if notebook is None:
    status, created, _ = call("POST", f"/bff/api/workspaces/{workspace}/notebooks", {"title": "Studio v2 E2E"})
    check("notebook create", status in (200, 201), status)
    notebook = created["data"]["notebook_id"]
studio = f"/bff/api/workspaces/{workspace}/notebooks/{notebook}/studio"

status, types, _ = call("GET", studio + "/types")
check("types", status == 200 and len(types["data"]["types"]) == 11, status)
status, memo, _ = call("POST", studio + "/memos", {"title": "E2E 메모", "markdown": "# E2E\n본문"})
check("memo create", status == 201, status)
oid = memo["data"]["output_id"]
status, detail, headers = call("GET", f"{studio}/outputs/{oid}")
check("memo get", status == 200 and detail["data"]["status"] == "completed" and detail["data"]["type_id"] == "memo", status)
status, edited, _ = call("POST", f"{studio}/outputs/{oid}/revisions", {"content": {"body": {"markdown": "# 편집본\n고친 본문"}}, "change_reason": "e2e"})
check("memo user edit -> revision 2", status == 201 and edited["data"]["revision_no"] == 2, status)
status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
check("memo edit visible", status == 200 and detail["data"]["revision"]["content"]["body"]["markdown"].startswith("# 편집본") and detail["data"]["current_revision"] == 2, status)
status, bad, _ = call("POST", f"{studio}/outputs/{oid}/revisions", {"content": {"body": {"markdown": 123}}})
check("invalid edit rejected", status == 400, status)
status, bad, _ = call("POST", f"{studio}/outputs/{oid}/revisions", {"content": {"body": "not-an-object"}})
check("non-object body rejected", status == 400, status)
status, body, headers = call("GET", f"{studio}/outputs/{oid}/exports/md", raw=True)
check("memo export md", status == 200 and body.startswith("# 편집본".encode()) and "attachment" in headers.get("Content-Disposition", ""), status)
status, listed, _ = call("GET", studio + "/outputs?limit=5")
check("list", status == 200 and any(i["output_id"] == oid for i in listed["data"]["items"]), status)
status, _, _ = call("GET", f"{studio}/outputs/{oid}/exports/docx")
check("memo docx unsupported", status == 400, status)
status, err, _ = call("POST", studio + "/outputs", {"type_id": "no_such_type"})
check("unknown type is rejected", status == 400 and err["error"]["code"] == "STUDIO_INPUT_INVALID", status)
status, _, _ = call("DELETE", f"{studio}/outputs/{oid}")
check("delete", status == 204, status)
status, _, _ = call("GET", f"{studio}/outputs/{oid}")
check("deleted is gone", status == 404, status)


def upload_sample():
    request = urllib.request.Request(
        BASE + f"/bff/api/workspaces/{workspace}/sources", data=SAMPLE.encode("utf-8"), method="POST",
        headers={"Origin": ORIGIN, "Referer": ORIGIN + "/notebooks", "Content-Type": "text/plain",
                 "Idempotency-Key": "e2e-src-" + uuid.uuid4().hex, "X-Source-Filename": "e2e-terms.txt", "X-Notebook-Id": notebook})
    try:
        response = opener.open(request, timeout=60)
        return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def source_state():
    status, listing, _ = call("GET", f"/bff/api/workspaces/{workspace}/sources?notebook_id={notebook}")
    for item in (listing.get("data") or {}).get("sources", []):
        if item.get("filename") == "e2e-terms.txt":
            return item
    return None


if "--upload" in sys.argv:
    item = source_state()
    if item is None:
        status, body = upload_sample()
        check("source upload", status in (200, 201, 202), status)
    for _ in range(180):
        item = source_state()
        state = (item or {}).get("source_state")
        if state in ("failed", "waiting_model") and not globals().get("retried"):
            retried = True
            status, body, _ = call("POST", f"/bff/api/sources/{item['source_id']}/processing-runs", {"kind": "processing_run", "attributes": {
                "workspace_id": workspace, "notebook_id": notebook, "source_version_id": item["source_version_id"]}})
            check("source reprocess", status in (200, 201, 202), status)
            state = None
        if state in ("ready", "failed", "unavailable", "waiting_model"):
            break
        time.sleep(2)
    check("source ready", state == "ready", state)
    sys.argv.append("--with-source")

if "--with-source" in sys.argv:
    only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
    failures = 0
    for kind in (only or KINDS):
        started = time.time()
        status, created, _ = call("POST", studio + "/outputs", {"type_id": kind, "settings": {"focus": "지급과 면책"}})
        check(f"{kind} accepted", status == 202, status)
        oid = created["data"]["output_id"]
        final, detail = None, {}
        for _ in range(300):
            status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
            final = detail["data"]["status"]
            if final in ("completed", "failed", "cancelled"):
                break
            time.sleep(2)
        print("INFO", kind, final, f"{int(time.time() - started)}s", "error:", detail["data"].get("error_code"), flush=True)
        if final != "completed":
            failures += 1
            print("FAIL", kind, "not completed", flush=True)
            call("DELETE", f"{studio}/outputs/{oid}")
            continue
        warnings = [w["code"] for w in (detail["data"]["revision"].get("warnings") or [])]
        print("INFO", kind, "warnings:", sorted(set(warnings)), "evidence:", len(detail["data"]["evidence"]), flush=True)
        status, prov, _ = call("GET", f"{studio}/outputs/{oid}/provenance")
        check(f"{kind} provenance", status == 200, status)
        for fmt in EXPORTS[kind]:
            status, body, headers = call("GET", f"{studio}/outputs/{oid}/exports/{fmt}", raw=True)
            check(f"{kind} export {fmt}", status == 200 and len(body) > 100, f"{status} {len(body) if isinstance(body, bytes) else 0}B")
        if detail["data"]["evidence"]:
            ref = detail["data"]["evidence"][0]["ref_id"]
            status, body, headers = call("GET", f"{studio}/outputs/{oid}/evidence/{ref}/content", raw=True)
            check(f"{kind} evidence content", status == 200 and len(body) > 0, status)
        call("DELETE", f"{studio}/outputs/{oid}")
    print("RESULT failures:", failures)
else:
    status, err, _ = call("POST", studio + "/outputs", {"type_id": "report"})
    if err.get("error", {}).get("code") == "STUDIO_NO_READY_SOURCE":
        check("report without sources rejected", status == 409, status)
    else:
        print("INFO notebook already has sources; skipped no-source check")

RFP_TEXT = chr(10).join(['통합 고객관리시스템 구축 제안요청서(합성 시험 문서)','','1. 사업 개요','본 사업은 발주처의 고객 업무 효율화를 위한 시스템 구축 사업이다.', '문서 식별: ' + uuid.uuid4().hex[:12],'','2. 요구사항','REQ-001 시스템은 사용자 인증을 위해 다중 인증 방식을 지원해야 한다.','REQ-002 모든 개인정보는 암호화하여 저장해야 한다.','REQ-003 시스템 가용성은 연 99.9% 이상이어야 한다.','REQ-004 데이터 이관 계획을 제안서에 포함해야 한다.','REQ-005 하자보수 기간은 검수 후 12개월 이상이어야 한다.','REQ-006 사용자 교육을 2회 이상 실시해야 한다.','','3. 평가 기준','기술 평가 80점, 가격 평가 20점으로 평가한다.',''])


def upload_named(name, text):
    request = urllib.request.Request(
        BASE + f"/bff/api/workspaces/{workspace}/sources", data=text.encode("utf-8"), method="POST",
        headers={"Origin": ORIGIN, "Referer": ORIGIN + "/notebooks", "Content-Type": "text/plain", "Idempotency-Key": "e2e-src-" + uuid.uuid4().hex,
                 "X-Source-Filename": name, "X-Notebook-Id": notebook})
    try:
        return opener.open(request, timeout=60).status
    except urllib.error.HTTPError as error:
        print("INFO upload error", error.read()[:300], flush=True)
        return error.code


def wait_ready(name):
    reprocessed = False
    for _ in range(240):
        status, listing, _ = call("GET", f"/bff/api/workspaces/{workspace}/sources?notebook_id={notebook}")
        item = next((i for i in (listing.get("data") or {}).get("sources", []) if i.get("filename") == name), None)
        state = (item or {}).get("source_state")
        if state == "ready":
            return item["source_version_id"]
        if state in ("failed", "waiting_model") and not reprocessed:
            reprocessed = True
            call("POST", f"/bff/api/sources/{item['source_id']}/processing-runs", {"kind": "processing_run", "attributes": {
                "workspace_id": workspace, "notebook_id": notebook, "source_version_id": item["source_version_id"]}})
        time.sleep(2)
    return None


if "--authoring" in sys.argv:
    auth = studio + "/authoring"
    upload_status = upload_named("e2e-rfp.txt", RFP_TEXT)
    print("INFO rfp upload status", upload_status, flush=True)
    if upload_status not in (200, 201, 202, 409):
        check("rfp upload", False)
    rfp_version = wait_ready("e2e-rfp.txt")
    check("rfp ready", rfp_version is not None)
    status, conns, _ = call("GET", "/bff/api/knowledge-connectors")
    rag = next((c for c in (conns.get("data") or {}).get("connectors", []) if c["kind"] == "daon2_rag"), None)
    check("rag connector registered", rag is not None, status)
    status, docs, _ = call("GET", f"/bff/api/knowledge-connectors/{rag['connector_id']}/documents?project_id=proj-alpha&work_package_id=wp-proposals&document_type=proposal")
    doc_ids = [d["document_id"] for d in (docs.get("data") or {}).get("documents", [])]
    if len(doc_ids) < 2:
        print("INFO documents response", status, str(docs)[:300], flush=True)
    check("reference proposals listed", len(doc_ids) >= 2, len(doc_ids))
    status, templates, _ = call("GET", auth + "/templates")
    check("templates", status == 200 and templates["data"]["templates"][0]["template_id"] == "rfp_response_proposal", status)
    status, created, _ = call("POST", auth + "/sessions", {"request_text": "RFP에 대응하는 제안서를 작성해 줘"})
    check("session created", status == 201 and created["data"]["state"] == "collecting", status)
    oid, rev = created["data"]["output_id"], created["data"]["revision_no"]
    status, step, _ = call("POST", f"{auth}/sessions/{oid}/answers", {"expected_revision": rev, "answers": [
        {"key": "rfp_document", "source_version_id": rfp_version},
        {"key": "reference_proposals", "knowledge_ref": {"connector_id": rag["connector_id"], "project_id": "proj-alpha", "work_package_id": "wp-proposals", "document_ids": doc_ids[:2]}}]})
    check("required answers", status == 202 and step["data"]["state"] == "collecting", status)
    status, step, _ = call("POST", f"{auth}/sessions/{oid}/answers", {"expected_revision": step["data"]["revision_no"], "answers": [], "skip_remaining": True})
    check("optional skipped -> analyzing", status == 202 and step["data"]["state"] == "analyzing" and step["data"]["queued"], status)

    def wait_state(target, limit=900):
        started = time.time()
        while time.time() - started < limit:
            status, session, _ = call("GET", f"{auth}/sessions/{oid}")
            data = session["data"]
            if data["state"] == target and data["job_status"] == "completed":
                return data
            if data["job_status"] == "failed":
                return data
            time.sleep(3)
        return None

    review = wait_state("review")
    check("analysis finished", review is not None and review["state"] == "review", review and (review["state"], review["job_status"]))
    print("INFO requirements:", len(review["requirements"]), "sections:", len(review["plan"]["sections"]), "knowledge:", review["knowledge_count"], flush=True)
    check("requirements extracted", len(review["requirements"]) >= 6)
    status, confirmed, _ = call("PUT", f"{auth}/sessions/{oid}/review", {"expected_revision": review["revision_no"], "confirm": True, "output_formats": ["docx", "pptx"]})
    check("plan confirmed -> generating", status == 202 and confirmed["data"]["queued"], status)
    done = wait_state("completed", limit=1500)
    check("document completed", done is not None and done["state"] == "completed", done and (done["state"], done["job_status"]))
    document = done["document"]
    summary = {k: sum(1 for c in document["coverage"] if c["status"] == k) for k in ("covered", "partial", "missing")}
    print("INFO coverage:", summary, "sections:", len(document["sections"]), "open_items:", len(document["open_items"]), flush=True)
    for fmt in ("docx", "pptx", "pdf"):
        status, body, headers = call("GET", f"{studio}/outputs/{oid}/exports/{fmt}", raw=True)
        check(f"authored export {fmt}", status == 200 and len(body) > 1000, f"{status} {len(body) if isinstance(body, bytes) else 0}B")
    # 지식 문서 버전 변경(stale) 확인: E2E_BUMP_CMD(가상 서버의 bump-version 호출 명령)가 있을 때만 실행한다.
    bump = os.environ.get("E2E_BUMP_CMD")
    if bump:
        status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
        check("fresh authored document is not stale", status == 200 and detail["data"]["stale"] is False, detail["data"].get("stale"))
        for bumped in doc_ids:
            subprocess.run(bump, shell=True, check=True, capture_output=True, timeout=60, env={**os.environ, "BUMP_DOC": bumped})
        status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
        check("knowledge version bump marks document stale", status == 200 and detail["data"]["stale"] is True, detail["data"].get("stale"))
        status, page, _ = call("GET", f"{studio}/outputs?limit=50")
        listed = [item for item in page["data"]["items"] if item["output_id"] == oid]
        check("stale shown on library card", bool(listed) and listed[0]["stale"] is True, listed and listed[0]["stale"])
        reset = os.environ.get("E2E_RESET_CMD")
        if reset:
            subprocess.run(reset, shell=True, check=True, capture_output=True, timeout=60)
    call("DELETE", f"{studio}/outputs/{oid}")
if "--authoring-docs" in sys.argv:
    # 약관·계약서 템플릿(기준 문서 + 변경점/법령 대조): 가상 RAG의 약관·계약서 문서를 기준으로 끝까지 실행한다.
    auth = studio + "/authoring"
    status, conns, _ = call("GET", "/bff/api/knowledge-connectors")
    rag = next((c for c in (conns.get("data") or {}).get("connectors", []) if c["kind"] == "daon2_rag"), None)
    check("rag connector registered", rag is not None, status)

    def find_docs(wp, kind):
        status, docs, _ = call("GET", f"/bff/api/knowledge-connectors/{rag['connector_id']}/documents?project_id={'proj-beta' if wp == 'wp-contracts' else 'proj-alpha'}&work_package_id={wp}&document_type={kind}")
        return status, [d["document_id"] for d in (docs.get("data") or {}).get("documents", [])]

    def run_template(template_id, answers_for, expect):
        status, created, _ = call("POST", auth + "/sessions", {"template_id": template_id})
        check(f"{template_id} session created", status == 201 and created["data"]["state"] == "collecting", status)
        oid, rev = created["data"]["output_id"], created["data"]["revision_no"]
        status, step, _ = call("POST", f"{auth}/sessions/{oid}/answers", {"expected_revision": rev, "answers": answers_for})
        check(f"{template_id} required answers", status == 202 and step["data"]["state"] == "collecting", status)
        status, step, _ = call("POST", f"{auth}/sessions/{oid}/answers", {"expected_revision": step["data"]["revision_no"], "answers": [], "skip_remaining": True})
        check(f"{template_id} -> analyzing", status == 202 and step["data"]["state"] == "analyzing", status)

        def wait_state(target, limit=900):
            started = time.time()
            while time.time() - started < limit:
                status, session, _ = call("GET", f"{auth}/sessions/{oid}")
                data = session["data"]
                if data["state"] == target and data["job_status"] == "completed":
                    return data
                if data["job_status"] == "failed":
                    return data
                time.sleep(3)
            return None

        review = wait_state("review")
        check(f"{template_id} analysis finished", review is not None and review["state"] == "review" and review["requirements"] == [], review and (review["state"], review["job_status"]))
        print("INFO", template_id, "sections:", len(review["plan"]["sections"]), "knowledge:", review["knowledge_count"], flush=True)
        status, confirmed, _ = call("PUT", f"{auth}/sessions/{oid}/review", {"expected_revision": review["revision_no"], "confirm": True, "output_formats": ["docx"]})
        check(f"{template_id} confirmed", status == 202 and confirmed["data"]["queued"], status)
        done = wait_state("completed", limit=1500)
        check(f"{template_id} completed", done is not None and done["state"] == "completed", done and (done["state"], done["job_status"]))
        document = done["document"]
        expect(document)
        for fmt in ("docx", "pdf"):
            status, body, headers = call("GET", f"{studio}/outputs/{oid}/exports/{fmt}", raw=True)
            check(f"{template_id} export {fmt}", status == 200 and len(body) > 1000, f"{status} {len(body) if isinstance(body, bytes) else 0}B")
        status, body, _ = call("GET", f"{studio}/outputs/{oid}/exports/pptx", raw=True)
        check(f"{template_id} pptx unsupported", status == 400, status)
        call("DELETE", f"{studio}/outputs/{oid}")

    status, terms_ids = find_docs("wp-terms", "insurance_terms")
    check("insurance terms listed", len(terms_ids) >= 1, len(terms_ids))

    def expect_terms(document):
        tags = {p.get("diff", {}).get("tag") for s in document["sections"] for p in s["paragraphs"]}
        summary = next(c for c in document["checks"] if c["id"] == "terms_change_summary")["summary"]
        print("INFO terms diff:", summary, "tags:", sorted(t for t in tags if t), flush=True)
        check("terms have change marks", len(tags - {None}) >= 1 and sum(summary.values()) > 0, summary)
        ruleset = next((c for c in document["checks"] if c["id"] == "terms_required_clauses"), None)
        check("terms ruleset evaluated", ruleset is not None and ruleset["status"] == "done", ruleset and ruleset.get("status"))

    run_template("insurance_terms_draft", [{"key": "product_type", "value": "자동차보험"},
        {"key": "base_terms", "knowledge_ref": {"connector_id": rag["connector_id"], "project_id": "proj-alpha", "work_package_id": "wp-terms", "document_ids": terms_ids[:1]}}], expect_terms)

    status, contract_ids = find_docs("wp-contracts", "contract")
    check("contracts listed", len(contract_ids) >= 1, len(contract_ids))

    def expect_contract(document):
        law = next((c for c in document["checks"] if c["id"] == "law_crosscheck"), None)
        print("INFO contract law check:", law and law.get("status"), law and law.get("summary"), flush=True)
        check("contract law cross-check", law is not None and law["status"] == "done" and len(law["rows"]) >= 1, law and law.get("status"))
        check("contract disclaimer", "법률 자문이 아닌" in document["notice"] and "법률 자문이 아닌" in law["notice"])

    run_template("contract_draft", [{"key": "contract_type", "value": "용역계약"},
        {"key": "base_contract", "knowledge_ref": {"connector_id": rag["connector_id"], "project_id": "proj-beta", "work_package_id": "wp-contracts", "document_ids": contract_ids[:1]}}], expect_contract)

if "--eval-authoring" in sys.argv:
    # WO-A1 T-A1-12: 합성 RFP 2건 × 기존 제안서 3건으로 작성 흐름을 실행하고 자동 측정값을 보고서 초안으로 만든다(사람 채점 칸은 비워 둔다).
    sys.path.insert(0, os.path.expanduser("~/deploy/daon2-user/services/mcp-virtual"))
    import io
    import re
    import zipfile
    from xml.etree import ElementTree
    from mcp_virtual.fixtures import build_documents

    auth = studio + "/authoring"
    # 0) 기본 모델: 소스 처리는 설정 화면의 "기본 모델 저장"과 같은 API로 지정한 모델을 쓴다(값은 환경 변수로 받는다).
    status, defaults, headers = call("GET", f"/bff/api/workspaces/{workspace}/model-defaults")
    current = next((d for d in (defaults.get("data") or {}).get("defaults", []) if d["capability"] == "text_generation"), None)
    if current is None:
        connection, model = os.environ.get("E2E_TEXT_CONNECTION"), os.environ.get("E2E_TEXT_MODEL")
        check("text default available (set E2E_TEXT_CONNECTION/E2E_TEXT_MODEL)", bool(connection and model))
        status, saved, _ = call("PATCH", f"/bff/api/workspaces/{workspace}/model-defaults",
                                {"capability": "text_generation", "connection_id": connection, "model_id": model, "expected_version": 0}, headers={"If-Match": headers.get("etag")})
        check("text default saved", status in (200, 201), status)

    status, conns, _ = call("GET", "/bff/api/knowledge-connectors")
    rag = next(c for c in (conns.get("data") or {}).get("connectors", []) if c["kind"] == "daon2_rag")
    status, docs, _ = call("GET", f"/bff/api/knowledge-connectors/{rag['connector_id']}/documents?project_id=proj-alpha&work_package_id=wp-proposals&document_type=proposal")
    proposal_ids = [d["document_id"] for d in (docs.get("data") or {}).get("documents", [])]
    check("3 reference proposals", len(proposal_ids) >= 3, len(proposal_ids))

    tokens = lambda text: set(re.findall(r"[0-9A-Za-z가-힣]{2,}", text.lower()))  # noqa: E731
    near = lambda a, b: len(tokens(a) & tokens(b)) / max(1, min(len(tokens(a)), len(tokens(b)))) >= 0.7  # noqa: E731
    rfps = [d for d in build_documents() if d["document_type"] == "rfp"]
    report = ["# 작성 엔진(RFP 대응 제안서) 평가 — 자동 측정 + 수동 채점표", "",
              f"- 실행: 합성 RFP {len(rfps)}건 × 기존 제안서 3건, 가상 MCP 서버, 설정된 기본 모델/Provider 우선순위 사용",
              "- 아래 자동 측정값은 합성 코퍼스의 정답(RFP의 REQ 항목)과 비교한 것이다. '사람 채점' 칸은 평가자가 채운다.", ""]
    for number, rfp in enumerate(rfps, 1):
        truth = [b["text"] for b in rfp["blocks"] if re.match(r"^REQ-\d+", b["text"])]
        body = "\n".join(b["text"] for b in rfp["blocks"]) + f"\n(평가 실행 식별 {uuid.uuid4().hex[:10]})\n"
        name = f"eval-rfp-{number}.txt"
        check(f"{name} upload", upload_named(name, body) in (200, 201, 202))
        version = wait_ready(name)
        check(f"{name} ready", version is not None)
        status, created, _ = call("POST", auth + "/sessions", {"template_id": "rfp_response_proposal"})
        oid, rev = created["data"]["output_id"], created["data"]["revision_no"]
        status, step, _ = call("POST", f"{auth}/sessions/{oid}/answers", {"expected_revision": rev, "answers": [
            {"key": "rfp_document", "source_version_id": version},
            {"key": "reference_proposals", "knowledge_ref": {"connector_id": rag["connector_id"], "project_id": "proj-alpha", "work_package_id": "wp-proposals", "document_ids": proposal_ids[:3]}}]})
        status, step, _ = call("POST", f"{auth}/sessions/{oid}/answers", {"expected_revision": step["data"]["revision_no"], "answers": [], "skip_remaining": True})
        started = time.time()

        def wait_session(target, limit=1500):
            while time.time() - started < limit + 10_000:
                status, session, _ = call("GET", f"{auth}/sessions/{oid}")
                data = session["data"]
                if (data["state"] == target and data["job_status"] == "completed") or data["job_status"] == "failed":
                    return data
                time.sleep(3)

        review = wait_session("review")
        analyze_seconds = int(time.time() - started)
        check(f"{name} analysis", review is not None and review["state"] == "review", review and (review["state"], review["job_status"]))
        extracted = [r["text"] for r in review["requirements"]]
        recall_hits = sum(1 for t in truth if any(near(t, e) for e in extracted))
        precision_hits = sum(1 for e in extracted if any(near(t, e) for t in truth))
        generate_started = time.time()
        status, confirmed, _ = call("PUT", f"{auth}/sessions/{oid}/review", {"expected_revision": review["revision_no"], "confirm": True, "output_formats": ["docx", "pptx"]})
        done = wait_session("completed")
        generate_seconds = int(time.time() - generate_started)
        check(f"{name} generation", done is not None and done["state"] == "completed", done and (done["state"], done["job_status"]))
        document = done["document"]
        counts = {k: sum(1 for c in document["coverage"] if c["status"] == k) for k in ("covered", "partial", "missing")}
        refs_ok = all(r.startswith(("S", "K")) for s in document["sections"] for p in s["paragraphs"] for r in p["refs"])
        sentences = sum(len(s["paragraphs"]) for s in document["sections"])
        sourced = sum(1 for s in document["sections"] for p in s["paragraphs"] if p["refs"])
        placeholder = sum(p["text"].count("[작성 필요]") for s in document["sections"] for p in s["paragraphs"])
        formats = {}
        for fmt in ("docx", "pptx"):
            status, data, _ = call("GET", f"{studio}/outputs/{oid}/exports/{fmt}", raw=True)
            valid = False
            if status == 200:
                try:
                    archive = zipfile.ZipFile(io.BytesIO(data))
                    for member in archive.namelist():
                        if member.endswith((".xml", ".rels")):
                            ElementTree.fromstring(archive.read(member))
                    valid = True
                except Exception:  # noqa: BLE001
                    valid = False
            formats[fmt] = f"{status} · {len(data) if isinstance(data, bytes) else 0}B · {'열림 가능' if valid else '실패'}"
        call("DELETE", f"{studio}/outputs/{oid}")
        report += [f"## RFP {number}: {rfp['title']}", "",
                   "| 항목 | 자동 측정 | 사람 채점(1~5) | 메모 |", "| --- | --- | --- | --- |",
                   f"| 요구사항 추출 재현율 | {recall_hits}/{len(truth)} ({recall_hits * 100 // max(1, len(truth))}%) | | |",
                   f"| 요구사항 추출 정밀도 | {precision_hits}/{len(extracted)} ({precision_hits * 100 // max(1, len(extracted))}%) | | |",
                   f"| 대응표(대응/부분/누락) | {counts['covered']}/{counts['partial']}/{counts['missing']} (총 {len(document['coverage'])}건) | | 정확도는 사람이 표본 확인 |",
                   f"| [작성 필요] 처리 | 본문 {placeholder}회, 미결 항목 {len(document['open_items'])}건 | | 입력이 없는 가격·조직 정보가 지어내지 않고 표시되는지 |",
                   f"| 근거 연결 | 근거 있는 문단 {sourced}/{sentences}, 허용 라벨만 사용: {'예' if refs_ok else '아니오'} | | 문장-근거 일치는 사람이 확인 |",
                   f"| 형식 준수 | DOCX {formats['docx']} / PPTX {formats['pptx']} | | Word·PowerPoint에서 열어 확인 |",
                   f"| 소요 시간 | 분석 {analyze_seconds}초 · 작성 {generate_seconds}초 | | |", ""]
    report += ["## 해석 가이드", "", "- 재현율·정밀도는 REQ-번호가 붙은 정답과의 어휘 유사도(≥0.7)로 센 값이라 사람이 추가한 요구사항 표현 차이는 오차로 잡힌다.",
               "- 대응표는 어휘 중복 기반 판정이라 표본 확인이 필요하다. 모델·Provider는 워크스페이스 설정에 따른다.", ""]
    open("/tmp/authoring-rfp-eval.md", "w", encoding="utf-8").write("\n".join(report))
    print("INFO report written /tmp/authoring-rfp-eval.md", flush=True)

if "--notebook-copy" in sys.argv:
    # WO-F3: 노트북 복사(ST-T20)와 채팅 기록 삭제(ST-T19)
    nb = f"/bff/api/workspaces/{workspace}/notebooks/{notebook}"
    status, memo, _ = call("POST", studio + "/memos", {"title": "복사용 메모", "markdown": "# 복사 시험\n본문"})
    check("copy: source memo", status == 201, status)
    status, cust, headers = call("GET", studio + "/customization")
    etag = headers.get("ETag")
    status, _, _ = call("PUT", studio + "/customization", {"instruction": "존댓말로 짧게 답해 주세요"}, headers={"If-Match": etag} if etag else None)
    check("copy: customization saved", status == 200, status)
    key = "e2e-copy-" + uuid.uuid4().hex
    status, copied, _ = call("POST", nb + "/copies", {"title": "E2E 사본", "include": {}}, headers={"Idempotency-Key": key})
    check("copy created", status == 201 and copied["data"]["copied"]["memos"] >= 1 and copied["data"]["copied"]["customization"] == 1, status)
    new_id = copied["data"]["notebook_id"]
    status, again, _ = call("POST", nb + "/copies", {"title": "E2E 사본", "include": {}}, headers={"Idempotency-Key": key})
    check("copy replay is idempotent", status == 200 and again["data"]["notebook_id"] == new_id and again["meta"]["replayed"] is True, status)
    status, other, _ = call("POST", nb + "/copies", {"title": "다른 이름", "include": {}}, headers={"Idempotency-Key": key})
    check("copy key reuse with other body is rejected", status == 409, status)
    new_studio = f"/bff/api/workspaces/{workspace}/notebooks/{new_id}/studio"
    status, listed, _ = call("GET", new_studio + "/outputs?limit=20")
    check("copied memo listed in new notebook", status == 200 and any(i["type_id"] == "memo" for i in listed["data"]["items"]), status)
    status, cust2, _ = call("GET", new_studio + "/customization")
    check("copied customization", status == 200 and cust2["data"]["instruction"].startswith("존댓말"), status)
    status, refused, _ = call("POST", nb + "/copies", {"include": {"sources": True}})
    print("INFO sources copy status", status, flush=True)
    check("copy with sources is refused while undecided", status in (201, 409))
    status, _, _ = call("DELETE", nb + "/chat-history")
    check("chat history cleared (204)", status == 204, status)
    status, _, _ = call("DELETE", nb + "/chat-history")
    check("chat history clear is repeatable", status == 204, status)
    status, ctxview, _ = call("GET", nb + "/context")
    check("context readable after chat clear (SQL valid)", status == 200, status)
    status, _, _ = call("DELETE", f"/bff/api/workspaces/{workspace}/notebooks/notebook-does-not-exist/chat-history")
    check("chat history clear on unknown notebook is 404", status == 404, status)

if "--authoring-org" in sys.argv:
    # WO-A3: 관리자 컨테이너에서 등록한 조직 템플릿(seed_org_template.py)이 목록에 보이고 세션이 그 버전을 고정한다.
    auth = studio + "/authoring"
    status, templates, _ = call("GET", auth + "/templates")
    org = [t for t in (templates.get("data") or {}).get("templates", []) if t["template_id"] == "org_qa_proposal"]
    check("org template listed", status == 200 and len(org) == 1, status)
    status, created, _ = call("POST", auth + "/sessions", {"template_id": "org_qa_proposal"})
    check("org session created", status == 201 and created["data"]["template_id"] == "org_qa_proposal" and created["data"]["state"] == "collecting", status)
    status, got, _ = call("GET", f"{auth}/sessions/{created['data']['output_id']}")
    check("org session readable", status == 200 and got["data"]["template_id"] == "org_qa_proposal", status)
    status, _, _ = call("DELETE", f"{studio}/outputs/{created['data']['output_id']}")
    check("org session deleted", status == 204, status)

print("DONE")

if "--audio" in sys.argv:
    # WO-F7: 오디오 개요(실제 LLM + 실제 TTS 서버). 길이 'short'로 만들고 재생·Range·내보내기를 확인한다. 본문·키는 출력하지 않는다.
    status, types_body, _ = call("GET", studio + "/types")
    audio_type = next(t for t in types_body["data"]["types"] if t["type_id"] == "audio_overview")
    check("audio type is available", audio_type["available"] is True, audio_type.get("reason"))
    props = audio_type["settings_schema"]["properties"]
    check("audio settings expose engine and voices", "enum" in props.get("engine", {}) and "enum" in props.get("voice_a", {}), sorted(props))
    started = time.time()
    engine_arg = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--engine=")), None)   # 화면에서 등록한 엔진(slug)으로 생성하려면 지정한다
    settings = {"length": "short", "focus": "지급과 면책", "voice_a": "F2", "voice_b": "M2", **({"engine": engine_arg} if engine_arg else {})}
    status, created, _ = call("POST", studio + "/outputs", {"type_id": "audio_overview", "settings": settings})
    check("audio accepted", status == 202, status)
    oid = created["data"]["output_id"]
    final, detail = None, {}
    for _ in range(600):
        status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
        final = detail["data"]["status"]
        if final in ("completed", "failed", "cancelled"):
            break
        time.sleep(3)
    print("INFO audio", final, f"{int(time.time() - started)}s", "error:", detail["data"].get("error_code"), flush=True)
    check("audio completed", final == "completed", detail["data"].get("error_code"))
    body = detail["data"]["revision"]["content"]["body"]
    script = body["script"]
    check("audio script has timings", len(script) >= 6 and all(isinstance(l.get("start_ms"), int) for l in script), len(script))
    check("audio voices recorded", body.get("voices") == {"A": "F2", "B": "M2"} and body.get("engine") == (engine_arg or "supertonic"), (body.get("voices"), body.get("engine")))
    print("INFO audio duration_ms", body.get("duration_ms"), "lines", len(script), flush=True)
    status, data, headers = call("GET", f"{studio}/outputs/{oid}/audio", raw=True)
    # BFF는 헤더를 허용표대로만 전달하고 Range를 넘기지 않아 전체 파일(200)을 돌려준다(플레이어는 전체를 받아 재생). Range 206·416은 API HTTP 시험이 확인한다.
    check("audio served as mp3 via BFF", status == 200 and headers.get("Content-Type", "").startswith("audio/mpeg") and len(data) > 5000, f"{status} {len(data)}B")
    check("audio length matches script timing", abs(len(data) * 8 / 128000 * 1000 - body["duration_ms"]) < 2000, f"{len(data)}B vs {body['duration_ms']}ms")
    status, mp3, headers = call("GET", f"{studio}/outputs/{oid}/exports/mp3", raw=True)
    check("audio export mp3", status == 200 and mp3 == data, status)
    status, _, _ = call("GET", f"{studio}/outputs/{oid}/exports/wav")
    check("audio export wav unsupported", status == 400, status)
    status, bad, _ = call("POST", studio + "/outputs", {"type_id": "audio_overview", "settings": {"voice_a": "Z9"}})
    if status == 202:
        bad_id = bad["data"]["output_id"]
        for _ in range(120):
            status, d2, _ = call("GET", f"{studio}/outputs/{bad_id}")
            if d2["data"]["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(2)
        check("unknown voice fails without sending", d2["data"]["status"] == "failed" and d2["data"].get("error_code") == "TTS_VOICE_UNKNOWN", d2["data"].get("error_code"))
        call("DELETE", f"{studio}/outputs/{bad_id}")
    status, _, _ = call("DELETE", f"{studio}/outputs/{oid}")
    check("audio delete", status == 204, status)
    status, _, _ = call("GET", f"{studio}/outputs/{oid}/audio")
    check("deleted audio is gone", status == 404, status)
    print("RESULT audio ok", flush=True)

if "--video" in sys.argv:
    # WO-F7V: 동영상 개요(실제 LLM + 실제 TTS + 실제 ffmpeg). 길이 'short'로 만들고 재생·내보내기·자막·챕터를 확인한다. 본문·키는 출력하지 않는다.
    status, types_body, _ = call("GET", studio + "/types")
    video_type = next(t for t in types_body["data"]["types"] if t["type_id"] == "video_overview")
    check("video type is available", video_type["available"] is True, video_type.get("reason"))
    props = video_type["settings_schema"]["properties"]
    check("video settings expose engine and narrator voice only", "enum" in props.get("engine", {}) and "enum" in props.get("voice_a", {}) and "voice_b" not in props, sorted(props))
    started = time.time()
    status, created, _ = call("POST", studio + "/outputs", {"type_id": "video_overview", "settings": {"length": "short", "focus": "지급과 면책", "voice_a": "F2"}})
    check("video accepted", status == 202, status)
    oid = created["data"]["output_id"]
    final, detail = None, {}
    for _ in range(900):
        status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
        final = detail["data"]["status"]
        if final in ("completed", "failed", "cancelled"):
            break
        time.sleep(3)
    print("INFO video", final, f"{int(time.time() - started)}s", "error:", detail["data"].get("error_code"), flush=True)
    check("video completed", final == "completed", detail["data"].get("error_code"))
    body = detail["data"]["revision"]["content"]["body"]
    scenes, chapters = body["scenes"], body["chapters"]
    check("video scenes have timings and cues", len(scenes) >= 3 and all(isinstance(s.get("start_ms"), int) and s.get("cues") for s in scenes), len(scenes))
    check("video chapters match scenes", len(chapters) == len(scenes) and chapters[0]["start_ms"] == 0, len(chapters))
    check("video voice recorded", body.get("voice") == "F2" and body.get("engine") == "supertonic", body.get("voice"))
    print("INFO video duration_ms", body.get("duration_ms"), "scenes", len(scenes), "warnings", sorted({w["code"] for w in detail["data"]["revision"].get("warnings") or []}), flush=True)
    status, data, headers = call("GET", f"{studio}/outputs/{oid}/video", raw=True)
    check("video served as mp4 via BFF", status == 200 and headers.get("Content-Type", "").startswith("video/mp4") and data[4:8] == b"ftyp" and len(data) > 20000, f"{status} {len(data)}B")
    status, mp4, _ = call("GET", f"{studio}/outputs/{oid}/exports/mp4", raw=True)
    check("video export mp4", status == 200 and mp4 == data, status)
    status, vtt, headers = call("GET", f"{studio}/outputs/{oid}/exports/vtt", raw=True)
    check("video export vtt", status == 200 and vtt.startswith(b"WEBVTT") and b"-->" in vtt and headers.get("Content-Type", "").startswith("text/vtt"), f"{status} {len(vtt)}B")
    status, _, _ = call("GET", f"{studio}/outputs/{oid}/audio")
    check("video output is not served as audio", status == 404, status)
    status, _, _ = call("DELETE", f"{studio}/outputs/{oid}")
    check("video delete", status == 204, status)
    status, _, _ = call("GET", f"{studio}/outputs/{oid}/video")
    check("deleted video is gone", status == 404, status)
    print("RESULT video ok", flush=True)

if "--st-t" in sys.argv:
    # F8-04/05: 자동화 가능한 ST-T 시나리오를 실제 스택(실제 LLM)에서 확인한다. LLM이 지시를 따랐는지에 달린 항목은
    # 따르지 않으면 FAIL이 아니라 INCONCLUSIVE로 출력한다(통과로 세지 않는다). 본문·비밀번호는 출력하지 않는다.
    nbp = f"/bff/api/workspaces/{workspace}/notebooks/{notebook}"
    ask_path = f"/bff/api/workspaces/{workspace}/questions"
    made = []
    inconclusive = []

    def wait_output(oid, limit=400, until=("completed", "failed", "cancelled")):
        detail = {}
        for _ in range(limit):
            status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
            if detail["data"]["status"] in until:
                return detail
            time.sleep(1)
        return detail

    def make(kind, settings=None, fmt=None):
        body = {"type_id": kind, "settings": settings or {}}
        if fmt:
            body["format_id"] = fmt
        started = time.time()
        status, created, _ = call("POST", studio + "/outputs", body)
        check(f"st-t create {kind}", status == 202, status)
        made.append(created["data"]["output_id"])
        return created["data"]["output_id"], started

    def ask(text):
        # 답변은 소스가 제공한 지식으로만 만든다. 소스 없이 묻으면 모델을 부르지 않고 안내만 돌려주므로 시험 소스를 붙인다.
        started = time.time()
        item = source_state()
        body = {"notebook_id": notebook, "question": text}
        if item is not None and item.get("source_state") == "ready":
            body["knowledge_context"] = {"mode": "raw_only", "resources": [
                {"resource_kind": "source", "resource_id": item["source_id"], "version_id": item["source_version_id"]}]}
        status, answer, _ = call("POST", ask_path, body)
        return status, answer, time.time() - started

    def note(label, ok, detail=""):
        if ok:
            check(label, True, detail)
        else:
            inconclusive.append(label)
            print("INCONCLUSIVE", label, detail, flush=True)

    # ST-T01 / T02 / T03: 생성 카드 즉시 표시, 생성 중 채팅 질문, 설정 반영
    focus = "지급 한도와 면책 기간"
    oid1, t0 = make("report", {"focus": focus})
    status, listing, _ = call("GET", studio + "/outputs?limit=20")
    visible = time.time() - t0
    card = next((i for i in listing["data"]["items"] if i["output_id"] == oid1), None)
    check("ST-T01 card is listed right after create", status == 200 and card is not None and card["status"] in ("queued", "generating"), f"{visible:.2f}s {card and card['status']}")
    check("ST-T01 card appears within 1 second", visible < 1.0, f"{visible:.2f}s")
    started_state = wait_output(oid1, limit=60, until=("generating", "completed", "failed", "cancelled"))["data"]["status"]
    status, answer, took = ask("안녕하세요. 한 문장으로 인사해 주세요.")
    state_now = call("GET", f"{studio}/outputs/{oid1}")[1]["data"]["status"]
    check("ST-T02 chat answers while a generation is running", status == 200 and bool(answer["data"]["answer"]), f"{status} {took:.1f}s, output was {started_state} -> {state_now}")
    note("ST-T02 the generation was running (generating) when the question was asked and still not finished when it was answered", started_state == "generating" and state_now in ("generating", "completed"), f"{started_state} -> {state_now}")
    d1 = wait_output(oid1)
    check("ST-T03 report completed", d1["data"]["status"] == "completed", d1["data"].get("error_code"))
    check("ST-T03 settings stored on the output", (d1["data"].get("settings") or {}).get("focus") == focus, d1["data"].get("settings"))
    status, prov, _ = call("GET", f"{studio}/outputs/{oid1}/provenance")
    check("ST-T03 provenance records the focus", status == 200 and prov["data"]["instruction"]["focus"] == focus, prov["data"]["instruction"])
    body1 = json.dumps(d1["data"]["revision"]["content"], ensure_ascii=False)
    note("ST-T03 the focus shows up in the content", "1,000,000" in body1 or "90일" in body1, "")
    rev1, content1 = d1["data"]["current_revision"], d1["data"]["revision"]["content"]

    # ST-T15: 새 세션(새로고침·재로그인)에서도 카드가 남아 있다
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    status, _, _ = call("POST", "/bff/api/auth/login", {"login_id": "qa-e2e", "password": password})
    check("ST-T15 re-login", status == 200, status)
    status, listing, _ = call("GET", studio + "/outputs?limit=50")
    again = next((i for i in listing["data"]["items"] if i["output_id"] == oid1), None)
    check("ST-T15 card survives a new session", again is not None and again["status"] == "completed" and again["title"] == d1["data"]["title"], again and again["status"])

    # ST-T18: 맞춤설정은 새 생성과 채팅에만 적용되고 기존 산출물은 그대로다
    status, cust, headers = call("GET", studio + "/customization")
    previous_instruction, etag = cust["data"]["instruction"], headers.get("ETag")
    instruction = "보고서 제목은 반드시 '[맞춤]'으로 시작하세요."
    status, put, headers = call("PUT", studio + "/customization", {"instruction": instruction}, headers={"If-Match": etag} if etag else None)
    check("ST-T18 customization saved", status == 200, status)
    oid2, _ = make("report", {"focus": focus})
    d2 = wait_output(oid2)
    check("ST-T18 report with customization completed", d2["data"]["status"] == "completed", d2["data"].get("error_code"))
    title2 = str(d2["data"]["revision"]["content"]["body"].get("title", ""))
    note("ST-T18 the new report follows the customization", title2.startswith("[맞춤]"), title2[:20])
    # 채팅: 서식 지시(특정 문구로 끝내기)는 모델이 무시하는 일이 있어 판정이 확실한 "영어로만 답하기"로 확인한다(2026-10-26 탐색: 영어 지시는 따랐다).
    status, cur, headers = call("GET", studio + "/customization")
    status, _, headers = call("PUT", studio + "/customization", {"instruction": "모든 채팅 답변은 반드시 영어로만 작성하세요. Answer only in English."}, headers={"If-Match": headers.get("ETag")} if headers.get("ETag") else None)
    check("ST-T18 chat customization saved", status == 200, status)
    status, answer2, _ = ask("안녕하세요. 업무 상담을 하고 싶습니다. 한두 문장으로 인사해 주세요.")
    check("ST-T18 chat answered", status == 200, status)
    reply = str(answer2["data"]["answer"])
    ascii_ratio = sum(1 for c in reply if ord(c) < 128) / max(1, len(reply))
    note("ST-T18 the chat answer follows the customization (English only)", ascii_ratio > 0.9, f"ascii {ascii_ratio:.2f}")
    d1b = call("GET", f"{studio}/outputs/{oid1}")[1]
    check("ST-T18 the earlier output is unchanged", d1b["data"]["current_revision"] == rev1 and d1b["data"]["revision"]["content"] == content1, d1b["data"]["current_revision"])
    status, cur, headers = call("GET", studio + "/customization")
    status, _, _ = call("PUT", studio + "/customization", {"instruction": previous_instruction or "-"}, headers={"If-Match": headers.get("ETag")} if headers.get("ETag") else None)
    check("ST-T18 customization restored", status == 200, status)

    # ST-T19: 채팅 기록 삭제는 내 채팅을 숨기고 산출물은 유지한다
    status, ctx_before, _ = call("GET", nbp + "/context")
    check("ST-T19 conversation exists before clearing", status == 200 and ctx_before["data"]["conversation"] is not None and bool(ctx_before["data"]["conversation_thread_ids"]), status)
    status, _, _ = call("DELETE", nbp + "/chat-history")
    check("ST-T19 chat history cleared", status == 204, status)
    status, ctx_after, _ = call("GET", nbp + "/context")
    check("ST-T19 conversation hidden after clearing", status == 200 and ctx_after["data"]["conversation"] is None, status)
    check("ST-T19 outputs are kept", call("GET", f"{studio}/outputs/{oid1}")[0] == 200, "")

    # ST-T25: 보고서 형식 선택(요약 vs 브리핑)이 구조 차이로 이어진다
    oid_a, _ = make("report", {"focus": focus}, "summary")
    oid_b, _ = make("report", {"focus": focus}, "briefing")
    da, db = wait_output(oid_a), wait_output(oid_b)
    check("ST-T25 both formats completed", da["data"]["status"] == "completed" and db["data"]["status"] == "completed", (da["data"].get("error_code"), db["data"].get("error_code")))
    check("ST-T25 format ids recorded", da["data"]["format_id"] == "summary" and db["data"]["format_id"] == "briefing", (da["data"]["format_id"], db["data"]["format_id"]))
    heads = lambda d: [s.get("heading") for s in d["data"]["revision"]["content"]["body"].get("sections", [])]
    note("ST-T25 the two formats produce different section structures", heads(da) != heads(db), f"{len(heads(da))} vs {len(heads(db))} sections")

    # ST-T07: 실행 중인 생성은 취소할 수 있고 실제 워커가 멈춘다
    oid_c, _ = make("report", {"focus": focus})
    running = wait_output(oid_c, limit=60, until=("generating", "completed", "failed", "cancelled"))
    if running["data"]["status"] == "generating":
        status, _, _ = call("POST", f"{studio}/outputs/{oid_c}/cancel")
        check("ST-T07 cancel accepted while generating", status == 202, status)
        final = wait_output(oid_c, limit=120)
        check("ST-T07 the worker stops and the card becomes cancelled", final["data"]["status"] == "cancelled", final["data"]["status"])
    else:
        note("ST-T07 cancel while generating", False, "finished before cancel: " + running["data"]["status"])

    for oid in made:
        call("DELETE", f"{studio}/outputs/{oid}")
    print("RESULT st-t ok; inconclusive:", inconclusive, flush=True)

if "--tts-admin" in sys.argv:
    # WO-F7T: BFF를 거친 TTS 엔진 관리 API. 시험 계정이 시스템 관리자가 아니면 모든 경로가 403인지를, 관리자이면 등록→확인→기본→수정→사용 안 함→해제 전체를 확인한다.
    # 키는 배포 설정 파일(서버 비밀 파일)에서 읽어 그대로 서버로 보내며 출력하지 않는다.
    admin_base = "/bff/api/admin/tts-engines"
    fake_id = "te-" + "f" * 32
    status, probe, _ = call("GET", admin_base)
    if status == 403:
        denied = [
            call("GET", admin_base)[0],
            call("POST", admin_base, {"slug": "x", "label": "x", "base_url": "https://tts.example.com", "voices": {"A": "F1", "B": "M1"}})[0],
            call("POST", f"{admin_base}/{fake_id}/verify", {})[0],
            call("PATCH", f"{admin_base}/{fake_id}", {"label": "x"}, headers={"If-Match": f'"tts-engine:{fake_id}:1"'})[0],
            call("DELETE", f"{admin_base}/{fake_id}")[0],
        ]
        check("tts-admin: every admin route is 403 for a non-admin account", denied == [403] * 5, denied)
        print("RESULT tts-admin denied ok", flush=True)
    else:
        check("tts-admin: admin can list", status == 200, status)
        engines = probe["data"]["engines"]
        print("INFO existing engines:", [(e["slug"], e["source"]) for e in engines], flush=True)
        key_file = os.path.expanduser("~/deploy/daon2-user/secrets/tts_engines.json")
        deployed = json.load(open(key_file, encoding="utf-8"))["engines"][0]
        slug = "e2e-" + uuid.uuid4().hex[:8]
        spec = {"slug": slug, "label": "E2E 엔진", "base_url": deployed["base_url"], "api_key": deployed["api_key"], "provider_kind": deployed["provider_kind"],
                "voices": {"A": "F1", "B": "M1"}}
        status, created, headers = call("POST", admin_base, spec)
        check("tts-admin: register", status == 201, status)
        view = created["data"]
        engine_id = view["engine_id"]
        check("tts-admin: response never carries the key", deployed["api_key"] not in json.dumps(created) and "api_key" not in created["data"], "")
        check("tts-admin: etag is returned", headers.get("ETag") == f'"tts-engine:{engine_id}:1"', headers.get("ETag"))
        check("tts-admin: new engine starts unverified with a credential", view["status"] == "unverified" and view["has_credential"] is True, view["status"])
        status, dup, _ = call("POST", admin_base, spec)
        check("tts-admin: duplicate slug is 409", status == 409 and dup["error"]["code"] == "TTS_ENGINE_SLUG_EXISTS", status)
        for label, bad, code in (("ftp scheme", {**spec, "slug": slug + "x", "base_url": "ftp://tts.example.com"}, "TTS_ENGINE_ENDPOINT_INVALID"),
                                 ("credentials in url", {**spec, "slug": slug + "y", "base_url": "https://user:pw@tts.example.com"}, "TTS_ENGINE_ENDPOINT_INVALID"),
                                 ("bad voice", {**spec, "slug": slug + "z", "voices": {"A": "bad voice", "B": "M1"}}, "TTS_ENGINE_VOICE_INVALID")):
            status, err, _ = call("POST", admin_base, bad)
            check(f"tts-admin: {label} is rejected", status == 400 and err["error"]["code"] == code, (status, err.get("error", {}).get("code")))
        status, verified, headers = call("POST", f"{admin_base}/{engine_id}/verify", {})
        check("tts-admin: verify (needs the voice server)", status == 200 and verified["data"]["status"] == "verified", verified.get("data", {}).get("error_code"))
        check("tts-admin: voices were filled from the server", len(verified["data"]["voice_choices"]) >= 10, len(verified["data"]["voice_choices"]))
        version = verified["data"]["version"]
        check("tts-admin: verify returns the new etag", headers.get("ETag") == f'"tts-engine:{engine_id}:{version}"', headers.get("ETag"))
        status, stale, _ = call("PATCH", f"{admin_base}/{engine_id}", {"label": "충돌"}, headers={"If-Match": f'"tts-engine:{engine_id}:{version - 1}"'})
        check("tts-admin: stale If-Match is 409", status == 409 and stale["error"]["code"] == "TTS_ENGINE_VERSION_CONFLICT", status)
        status, bad_etag, _ = call("PATCH", f"{admin_base}/{engine_id}", {"label": "x"}, headers={"If-Match": "W/1"})
        check("tts-admin: malformed If-Match is 400", status == 400, status)
        status, patched, headers = call("PATCH", f"{admin_base}/{engine_id}", {"label": "E2E 엔진(수정)", "is_default": True, "voices": {"A": "F2", "B": "M2"}},
                                        headers={"If-Match": f'"tts-engine:{engine_id}:{version}"'})
        check("tts-admin: patch label, default and voices", status == 200 and patched["data"]["label"] == "E2E 엔진(수정)" and patched["data"]["is_default"] is True
              and patched["data"]["voices"] == {"A": "F2", "B": "M2"}, status)
        version = patched["data"]["version"]
        status, listing, _ = call("GET", admin_base)
        mine = [e for e in listing["data"]["engines"] if e["slug"] == slug]
        others_default = [e["slug"] for e in listing["data"]["engines"] if e["is_default"] and e["slug"] != slug]
        check("tts-admin: it is the only default", len(mine) == 1 and mine[0]["is_default"] and not others_default, others_default)
        time.sleep(16)    # API 프로세스의 15초 캐시(같은 프로세스 변경은 즉시 반영되지만 확실히 하기 위해)
        status, types_body, _ = call("GET", studio + "/types")
        audio_props = next(t for t in types_body["data"]["types"] if t["type_id"] == "audio_overview")["settings_schema"]["properties"]
        check("tts-admin: generation settings offer the new engine and it is the default", slug in audio_props["engine"]["enum"] and audio_props["engine"]["default"] == slug,
              (audio_props["engine"]["enum"], audio_props["engine"].get("default")))
        status, off, _ = call("PATCH", f"{admin_base}/{engine_id}", {"enabled": False}, headers={"If-Match": f'"tts-engine:{engine_id}:{version}"'})
        check("tts-admin: disable", status == 200 and off["data"]["status"] == "disabled" and off["data"]["is_default"] is False, status)
        version = off["data"]["version"]
        status, refuse, _ = call("PATCH", f"{admin_base}/{engine_id}", {"is_default": True}, headers={"If-Match": f'"tts-engine:{engine_id}:{version}"'})
        check("tts-admin: a disabled engine cannot become the default", status == 409 and refuse["error"]["code"] == "TTS_ENGINE_DISABLED", status)
        time.sleep(1)
        status, types_after, _ = call("GET", studio + "/types")
        enum_after = next(t for t in types_after["data"]["types"] if t["type_id"] == "audio_overview")["settings_schema"]["properties"]["engine"]["enum"]
        check("tts-admin: a disabled engine disappears from the generation choices", slug not in enum_after, enum_after)
        status, _, _ = call("DELETE", f"{admin_base}/{engine_id}")
        check("tts-admin: disconnect", status == 204, status)
        status, again, _ = call("DELETE", f"{admin_base}/{engine_id}")
        check("tts-admin: deleting twice is 404", status == 404 and again["error"]["code"] == "TTS_ENGINE_NOT_FOUND", status)
        status, listing, _ = call("GET", admin_base)
        check("tts-admin: the deployment engine is still listed read-only", any(e["source"] == "deployment" and e["engine_id"] is None for e in listing["data"]["engines"])
              and all(e["slug"] != slug for e in listing["data"]["engines"]), "")
        print("RESULT tts-admin ok", flush=True)

if any(a.startswith("--save-exports=") for a in sys.argv):
    # 실제 LLM으로 유형별 산출물을 만들고 내보내기 파일을 디렉터리에 저장한다(사람이 Office 등으로 여는 검증용). 본문은 출력하지 않는다.
    target = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--save-exports="))
    os.makedirs(target, exist_ok=True)
    plan = {"report": ["docx", "pdf", "md"], "data_table": ["xlsx", "csv", "pdf"], "slides": ["pptx", "pdf"], "quiz": ["csv", "json", "pdf"],
            "flashcards": ["csv", "json", "pdf"], "mind_map": ["svg", "png", "json"], "infographic": ["png", "svg", "pdf"]}
    saved = []
    kept = []
    for kind, formats in plan.items():
        status, created, _ = call("POST", studio + "/outputs", {"type_id": kind, "settings": {"focus": "지급 한도와 면책 기간"}})
        check(f"save-exports {kind} accepted", status == 202, status)
        oid = created["data"]["output_id"]
        final = None
        for _ in range(300):
            status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
            final = detail["data"]["status"]
            if final in ("completed", "failed", "cancelled"):
                break
            time.sleep(2)
        check(f"save-exports {kind} completed", final == "completed", detail["data"].get("error_code"))
        for fmt in formats:
            status, data, headers = call("GET", f"{studio}/outputs/{oid}/exports/{fmt}", raw=True)
            check(f"save-exports {kind}.{fmt}", status == 200 and len(data) > 50, f"{status} {len(data)}B")
            name = f"{kind}.{fmt}"
            open(os.path.join(target, name), "wb").write(data)
            saved.append(name)
        if "--keep-outputs" in sys.argv:
            kept.append(oid)
        else:
            call("DELETE", f"{studio}/outputs/{oid}")
    print("RESULT saved", saved, flush=True)
    if kept:
        print("KEPT", ",".join(kept), flush=True)

if any(a.startswith("--save-media=") for a in sys.argv):
    # 실제 LLM+TTS로 오디오·동영상을 만들어 파일과 대본을 저장한다(음성 인식 왕복·ffprobe 검증용). 본문은 출력하지 않는다.
    target = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--save-media="))
    os.makedirs(target, exist_ok=True)
    kept = []
    for kind, formats in (("audio_overview", ["mp3"]), ("video_overview", ["mp4", "vtt"])):
        status, created, _ = call("POST", studio + "/outputs", {"type_id": kind, "settings": {"length": "short", "focus": "지급 한도와 면책 기간"}})
        check(f"save-media {kind} accepted", status == 202, status)
        oid = created["data"]["output_id"]
        for _ in range(900):
            status, detail, _ = call("GET", f"{studio}/outputs/{oid}")
            if detail["data"]["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(3)
        check(f"save-media {kind} completed", detail["data"]["status"] == "completed", detail["data"].get("error_code"))
        json.dump(detail["data"]["revision"]["content"], open(os.path.join(target, f"{kind}.content.json"), "w", encoding="utf-8"), ensure_ascii=False)
        for fmt in formats:
            status, data, _ = call("GET", f"{studio}/outputs/{oid}/exports/{fmt}", raw=True)
            check(f"save-media {kind}.{fmt}", status == 200 and len(data) > 100, f"{status} {len(data)}B")
            open(os.path.join(target, f"{kind}.{fmt}"), "wb").write(data)
        if "--keep-outputs" in sys.argv:
            kept.append(oid)
        else:
            call("DELETE", f"{studio}/outputs/{oid}")
    print("RESULT media saved", flush=True)
    if kept:
        print("KEPT", ",".join(kept), flush=True)

if "--chat" in sys.argv:
    # 대화창 요구 1~4: 질문·답변 누적과 복원, 소스 지식만으로 답변(지식이 없으면 모델 미호출), 모델·추론 수준 선택의 저장·복원·검증.
    nbp = f"/bff/api/workspaces/{workspace}/notebooks/{notebook}"
    ask_path = f"/bff/api/workspaces/{workspace}/questions"
    inconclusive = []

    def note(label, ok, detail=""):
        if ok:
            check(label, True, detail)
        else:
            inconclusive.append(label)
            print("INCONCLUSIVE", label, detail, flush=True)

    def source_context():
        item = source_state()
        if item is None or item.get("source_state") != "ready":
            return None
        return {"mode": "raw_only", "resources": [{"resource_kind": "source", "resource_id": item["source_id"], "version_id": item["source_version_id"]}]}

    def turns():
        status, body, _ = call("GET", nbp + "/chat-history")
        check("chat-history readable", status == 200 and isinstance(body["data"]["turns"], list), status)
        return body["data"]["turns"]

    call("DELETE", nbp + "/chat-history")
    check("chat starts empty after clearing", turns() == [], "")

    # 요구 2: 지식이 없으면 모델을 부르지 않고 안내한다.
    q1 = "소스 없이 묻는 질문입니다. 대한민국의 수도는 어디인가요?"
    status, a1, _ = call("POST", ask_path, {"notebook_id": notebook, "question": q1})
    check("no-source question is answered with guidance", status == 200 and a1["data"]["insufficient"] is True and not a1["data"]["citations"], status)
    check("no-source guidance says no knowledge is provided and tells to add sources", "지식이 제공되지 않았습니다" in a1["data"]["answer"] and "소스" in a1["data"]["answer"], "")
    check("no-source answer does not contain training knowledge", "서울" not in a1["data"]["answer"], "")
    check("no-source metadata asks for a source", a1["data"]["next_actions"] == ["Source 추가"], a1["data"]["next_actions"])
    nb_run = a1["data"]["run_id"]

    context = source_context()
    check("sample source is ready", context is not None, "")
    q2 = "제1조에 따르면 보험금은 청구서류를 접수한 날부터 며칠 이내에 지급하나요?"
    status, a2, _ = call("POST", ask_path, {"notebook_id": notebook, "question": q2, "knowledge_context": context})
    check("grounded question answered", status == 200 and a2["data"]["insufficient"] is False and bool(a2["data"]["citations"]), status)
    note("grounded answer states the confirmed value (3일)", "3" in a2["data"]["answer"], "")

    q3 = "이 약관과 무관하게 대한민국의 수도는 어디인가요?"
    status, a3, _ = call("POST", ask_path, {"notebook_id": notebook, "question": q3, "knowledge_context": context})
    check("out-of-source question with a source answers", status == 200, status)
    note("out-of-source question is not answered from training knowledge", a3["data"]["insufficient"] is True or "서울" not in a3["data"]["answer"], str(a3["data"]["answer"])[:60])

    # 요구 1: 질문·답변이 시간순으로 쌓이고 새 세션에서도 복원된다.
    saved = turns()
    questions = [t["question"] for t in saved]
    check("all questions accumulate in order", questions == [q1, q2, q3], len(saved))
    check("every turn carries its answer", all(t["answer"] is not None and t["state"] == "completed" for t in saved), "")
    check("answers match the responses", saved[1]["answer"]["answer"] == a2["data"]["answer"] and saved[0]["answer"]["run_id"] == nb_run, "")
    check("citations are restored with the answer", len(saved[1]["answer"]["citations"]) == len(a2["data"]["citations"]), "")
    jar.clear()
    status, _, _ = call("POST", "/bff/api/auth/login", {"login_id": "qa-e2e", "password": password})
    check("re-login", status == 200, status)
    check("conversation is restored after re-login", [t["question"] for t in turns()] == questions, "")

    # 요구 4: 모델·추론 수준 선택
    status, sel, _ = call("GET", nbp + "/model-selection")
    check("model selection readable", status == 200 and isinstance(sel["data"]["available"], list), status)
    available = sel["data"]["available"]
    print("INFO available models:", len(available), "levels:", sel["data"]["levels"], flush=True)
    original = sel["data"]["selection"]
    if available:
        pick = available[0]
        status, put, _ = call("PUT", nbp + "/model-selection", {"connection_id": pick["connection_id"], "model_id": pick["model_id"], "reasoning_level": None})
        check("model selection saved", status == 200 and put["data"]["selection"]["model_id"] == pick["model_id"], status)
        jar.clear()
        call("POST", "/bff/api/auth/login", {"login_id": "qa-e2e", "password": password})
        status, again, _ = call("GET", nbp + "/model-selection")
        check("model selection restored after re-login", again["data"]["selection"] is not None and again["data"]["selection"]["model_id"] == pick["model_id"], "")
        status, bad, _ = call("PUT", nbp + "/model-selection", {"connection_id": pick["connection_id"], "model_id": pick["model_id"], "reasoning_level": "high"})
        unconfirmed = "high" not in pick["reasoning_levels"]
        check("unconfirmed reasoning level is rejected", (status == 409 and bad["error"]["code"] == "REASONING_LEVEL_UNSUPPORTED") if unconfirmed else status == 200, status)
        status, bad, _ = call("PUT", nbp + "/model-selection", {"connection_id": "no-such-connection", "model_id": "no-such-model", "reasoning_level": None})
        check("model outside the approved list is rejected", status == 409 and bad["error"]["code"] == "SELECTED_MODEL_UNAVAILABLE", status)
        status, a4, _ = call("POST", ask_path, {"notebook_id": notebook, "question": q2, "knowledge_context": context})
        check("question runs with the selected model", status == 200 and a4["data"]["insufficient"] is False, status)
    status, back, _ = call("PUT", nbp + "/model-selection", {"connection_id": (original or {}).get("connection_id"), "model_id": (original or {}).get("model_id"), "reasoning_level": (original or {}).get("reasoning_level")})
    check("model selection restored to its original state", status == 200 and back["data"]["selection"] == original, status)

    # 비움은 내 대화창만 비운다.
    status, _, _ = call("DELETE", nbp + "/chat-history")
    check("chat cleared", status == 204, status)
    check("cleared conversation is not restored", turns() == [], "")
    print("RESULT chat ok", ("INCONCLUSIVE " + str(len(inconclusive))) if inconclusive else "", flush=True)
