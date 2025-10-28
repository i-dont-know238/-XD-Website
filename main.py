from flask import Flask, request, Response, redirect, make_response
import requests
import re
import os
import secrets
import threading
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

BASE_URL = "https://beaufortsc.powerschool.com"
UP = urlparse(BASE_URL)
UP_HOST = UP.netloc

SESSION_COOKIE = "PS_PROXY_ID"
_sessions = {}
_lock = threading.Lock()

ABS_HOST_RE = re.compile(r'(?i)\bhttps?://' + re.escape(UP_HOST))
ATTR_ABS_DBL = re.compile(r'(?i)(href|src|action)\s*=\s*"https?://' + re.escape(UP_HOST) + r'([^"]*)"')
ATTR_ABS_SGL = re.compile(r"(?i)(href|src|action)\s*=\s*'https?://" + re.escape(UP_HOST) + r"([^']*)'")
ATTR_SCHEMELESS_DBL = re.compile(r'(?i)(href|src|action)\s*=\s*"//' + re.escape(UP_HOST) + r'([^"]*)"')
ATTR_SCHEMELESS_SGL = re.compile(r"(?i)(href|src|action)\s*=\s*'//" + re.escape(UP_HOST) + r"([^']*)'")
REL_PATH_DBL = re.compile(r'(?i)(href|src|action)\s*=\s*"(\/[^"]*)"')
REL_PATH_SGL = re.compile(r"(?i)(href|src|action)\s*=\s*'(\/[^']*)'")

BLOCKED_RESP_HEADERS = {
    "content-security-policy","x-content-security-policy","x-webkit-csp",
    "x-frame-options","referrer-policy","content-encoding","transfer-encoding",
    "strict-transport-security","content-length","connection","keep-alive","upgrade",
    "proxy-authenticate","proxy-authorization","te","trailer"
}
HOP_BY_HOP_REQ = {"host","content-length","accept-encoding","connection","keep-alive","upgrade","proxy-authorization","proxy-authenticate","te","trailer","cookie"}

def is_secure_request():
    xf_proto = request.headers.get("X-Forwarded-Proto", "")
    return request.is_secure or xf_proto.lower() == "https"

def local_base():
    return request.host_url.rstrip('/')

def get_client_session():
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        sid = secrets.token_urlsafe(18)
    with _lock:
        sess = _sessions.get(sid)
        if not sess:
            sess = requests.Session()
            _sessions[sid] = sess
    return sid, sess

def upstream_headers():
    h = {k: v for k, v in request.headers if k.lower() not in HOP_BY_HOP_REQ}
    h["Host"] = UP_HOST
    if "origin" in {k.lower() for k in request.headers.keys()}:
        h["Origin"] = BASE_URL
    if "referer" in {k.lower() for k in request.headers.keys()}:
        h["Referer"] = BASE_URL
    return h

def sanitize_resp_headers(h):
    return {k: v for k, v in h.items() if k.lower() not in BLOCKED_RESP_HEADERS}

def rewrite_text_urls(text):
    text = ABS_HOST_RE.sub(local_base(), text)
    text = ATTR_ABS_DBL.sub(lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = ATTR_ABS_SGL.sub(lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    text = ATTR_SCHEMELESS_DBL.sub(lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = ATTR_SCHEMELESS_SGL.sub(lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    return text

def rewrite_rel_attrs(text):
    text = REL_PATH_DBL.sub(lambda m: f'{m.group(1)}="{m.group(2)}"', text)
    text = REL_PATH_SGL.sub(lambda m: f"{m.group(1)}='{m.group(2)}'", text)
    return text

def forward_to_upstream(url):
    sid, sess = get_client_session()
    method = request.method
    headers = upstream_headers()
    data = request.get_data() if method in ("POST","PUT","PATCH","DELETE") else None

    # Log details
    print(f"[PROXY] {sid} -> {method} {url}")
    print(f"[PROXY] Headers: {headers}")
    print(f"[PROXY] Cookies: {request.cookies}")

    try:
        resp = sess.request(method, url, headers=headers, data=data, allow_redirects=False, timeout=45)
    except Exception as e:
        r = make_response(f"upstream error: {e}", 502)
        r.headers["Cache-Control"] = "no-store"
        r.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Lax", secure=is_secure_request(), path="/")
        return r

    print(f"[PROXY] Response code: {resp.status_code}")
    print(f"[PROXY] Response headers: {resp.headers}")

    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        loc = resp.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        loc = ABS_HOST_RE.sub(local_base(), loc)
        r = redirect(loc, code=resp.status_code)
        r.headers["Cache-Control"] = "no-store"
        r.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Lax", secure=is_secure_request(), path="/")
        return r

    ctype = resp.headers.get("content-type","").lower()
    body = resp.content
    if any(t in ctype for t in ("text/html","text/css","javascript","json")):
        try:
            t = body.decode("utf-8", errors="replace")
        except:
            t = body.decode("latin-1", errors="replace")
        t = rewrite_text_urls(t)
        t = rewrite_rel_attrs(t)
        body = t.encode("utf-8")

    rh = sanitize_resp_headers(resp.headers)
    r = Response(body, status=resp.status_code)
    for k, v in rh.items():
        r.headers[k] = v
    if "Content-Type" not in r.headers and "content-type" in rh:
        r.headers["Content-Type"] = rh.get("content-type")
    r.headers["Cache-Control"] = "no-store"
    r.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Lax", secure=is_secure_request(), path="/")
    return r

@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"])
@app.route("/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"])
def all_paths(path):
    target = urljoin(BASE_URL + "/", path)
    if request.query_string:
        target += ("&" if "?" in target else "?") + request.query_string.decode()
    return forward_to_upstream(target)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
