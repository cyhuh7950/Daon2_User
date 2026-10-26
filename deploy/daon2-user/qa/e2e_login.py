import json, os, secrets, urllib.request, urllib.error, http.cookiejar
BASE = "http://127.0.0.1:3340"
ORIGIN = "http://172.27.253.53:3340"
D = os.path.expanduser("~/deploy/daon2-user/secrets")
pwfile = os.path.join(D, "qa_e2e_password")
password = open(pwfile).read().strip()
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(method, path, body=None):
    headers = {"Origin": ORIGIN, "Referer": ORIGIN + "/password-change"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"; data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        r = opener.open(req, timeout=20); raw = r.read()
        return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw[:0])
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, {}
def keys(o, depth=1):
    return sorted(o.keys()) if isinstance(o, dict) else type(o).__name__
st, body = call("POST", "/bff/api/auth/login", {"login_id": "qa-e2e", "password": password})
print("1 login:", st, "data keys:", keys(body.get("data")) if isinstance(body, dict) else "-", "error:", (body.get("error") or {}).get("code") if isinstance(body, dict) else None)
st, body = call("GET", "/bff/api/session")
print("2 session:", st, "password_change_required:", (body.get("data") or {}).get("password_change_required") if isinstance(body, dict) else None)
need_change = isinstance(body, dict) and (body.get("data") or {}).get("password_change_required")
if need_change:
    new_pw = secrets.token_urlsafe(24)
    st, body = call("POST", "/bff/api/auth/password/change", {"current_password": password, "new_password": new_pw})
    print("3 password change:", st, "error:", (body.get("error") or {}).get("code") if isinstance(body, dict) else None)
    if st < 300:
        with open(pwfile, "w") as h: os.fchmod(h.fileno(), 0o600); h.write(new_pw)
        password = new_pw
        st, body = call("POST", "/bff/api/auth/login", {"login_id": "qa-e2e", "password": password})
        print("4 re-login:", st, "error:", (body.get("error") or {}).get("code") if isinstance(body, dict) else None)
st, body = call("GET", "/bff/api/session")
d = (body.get("data") or {}) if isinstance(body, dict) else {}
print("5 session:", st, "password_change_required:", d.get("password_change_required"), "workspace_id present:", bool(d.get("workspace_id")), "keys:", keys(d))
ws = d.get("workspace_id")
if ws:
    st, body = call("GET", f"/bff/api/workspaces/{ws}/notebooks")
    nb = (body.get("data") if isinstance(body, dict) else None)
    print("6 notebooks API:", st, "type:", type(nb).__name__, "count:", (len(nb) if isinstance(nb, list) else (len(nb.get("notebooks", [])) if isinstance(nb, dict) and "notebooks" in nb else "n/a")))
# page requests (HTML) with session cookie
for path in ("/notebooks", "/"):
    req = urllib.request.Request(BASE + path, headers={"Origin": ORIGIN})
    try:
        r = opener.open(req, timeout=20); html = r.read().decode("utf8", "ignore")
        print(f"7 GET {path}:", r.status, "len", len(html), "title:", (html.split("<title>")[1].split("</title>")[0] if "<title>" in html else "-"))
    except urllib.error.HTTPError as e:
        print(f"7 GET {path}:", e.code)
