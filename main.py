import os
import json
import uuid
from urllib.parse import urljoin
from flask import Flask, request, redirect, url_for, Response, make_response
import requests
import re
import redis
from cryptography.fernet import Fernet, InvalidToken
from requests.utils import dict_from_cookiejar, cookiejar_from_dict

app = Flask(__name__)
BASE_URL = "https://beaufortsc.powerschool.com"
session = requests.Session()
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)
FERNET_KEY = os.environ.get("COOKIE_ENCRYPTION_KEY")
fernet = Fernet(FERNET_KEY) if FERNET_KEY else None
PROXY_SID_NAME = "proxy_sid"
COOKIE_TTL = int(os.environ.get("COOKIE_TTL_SECONDS", str(60 * 60 * 24 * 7)))

def _scheme():
    return request.headers.get("X-Forwarded-Proto", request.scheme)

def _host_root():
    return f"{_scheme()}://{request.host}/"

def replace_urls(html_content):
    html = re.sub(r'(href|src|action)="(/[^"]*)"', r'\1="/proxy\2"', html_content)
    html = re.sub(r"(href|src|action)='(/[^']*)'", r"\1='/proxy\2'", html)
    html = html.replace(BASE_URL, _host_root() + "proxy")
    return html

def _clean_headers():
    hop = {"host","connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailers","transfer-encoding","upgrade","content-length"}
    headers = {k:v for k,v in request.headers.items() if k.lower() not in hop}
    headers["Host"] = "beaufortsc.powerschool.com"
    return headers

def _serialize_cookies(cookiejar):
    d = dict_from_cookiejar(cookiejar)
    payload = json.dumps(d)
    if fernet:
        token = fernet.encrypt(payload.encode("utf-8")).decode("utf-8")
        return token
    return payload

def _deserialize_cookies(payload):
    if not payload:
        return {}
    if fernet:
        try:
            dec = fernet.decrypt(payload.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return {}
        return json.loads(dec)
    else:
        return json.loads(payload)

def _get_sid():
    sid = request.cookies.get(PROXY_SID_NAME)
    if sid:
        return sid
    sid = str(uuid.uuid4())
    return sid

def _save_cookies_for_sid(sid, cookiejar):
    serialized = _serialize_cookies(cookiejar)
    redis_client.setex(f"cookies:{sid}", COOKIE_TTL, serialized)

def _load_cookies_for_sid(sid):
    data = redis_client.get(f"cookies:{sid}")
    if not data:
        return {}
    return _deserialize_cookies(data)

def _attach_cookies_to_session(s, sid):
    cookies_dict = _load_cookies_for_sid(sid)
    if cookies_dict:
        s.cookies = cookiejar_from_dict(cookies_dict)

def _persist_response_cookies(sid, upstream_resp):
    jar = upstream_resp.cookies
    if jar:
        _save_cookies_for_sid(sid, jar)

def _set_proxy_sid_cookie_in_response(resp, sid):
    secure = _scheme() == "https"
    resp.set_cookie(PROXY_SID_NAME, sid, httponly=True, secure=secure, samesite="Lax", max_age=COOKIE_TTL, path="/")

def _rewrite_location(upstream_resp, resp_obj):
    if "location" in upstream_resp.headers:
        loc = upstream_resp.headers["location"]
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
            resp_obj.headers["location"] = f"/proxy{loc}"
        elif loc.startswith("/"):
            resp_obj.headers["location"] = f"/proxy{loc}"

def _build_response(upstream_resp, raw_content):
    headers = {k:v for k,v in upstream_resp.headers.items() if k.lower() not in {"content-length","content-encoding","transfer-encoding","connection"}}
    return Response(raw_content, status=upstream_resp.status_code, headers=headers)

@app.route("/set_cookies", methods=["POST"])
def set_cookies():
    sid = request.cookies.get(PROXY_SID_NAME) or str(uuid.uuid4())
    try:
        cookies_json = request.get_json(force=True)
    except:
        return {"error":"invalid json"}, 400
    if not isinstance(cookies_json, dict):
        return {"error":"json must be object of cookie-name: value"}, 400
    jar = cookiejar_from_dict(cookies_json)
    _save_cookies_for_sid(sid, jar)
    resp = make_response({"status":"ok"})
    _set_proxy_sid_cookie_in_response(resp, sid)
    return resp

@app.route("/", methods=["GET","POST"])
def home():
    if request.method == "POST":
        return redirect(url_for("home"))
    sid = _get_sid()
    s = requests.Session()
    _attach_cookies_to_session(s, sid)
    r = s.get(f"{BASE_URL}/public/home.html", headers=_clean_headers(), allow_redirects=False)
    content_type = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in content_type:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    resp = _build_response(r, body)
    _persist_response_cookies(sid, r)
    _set_proxy_sid_cookie_in_response(resp, sid)
    _rewrite_location(r, resp)
    return resp

@app.route("/proxy/<path:path>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def proxy(path):
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    sid = _get_sid()
    s = requests.Session()
    _attach_cookies_to_session(s, sid)
    headers = _clean_headers()
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    files = None
    if request.files:
        files = {k: (f.filename, f.stream, f.mimetype) for k,f in request.files.items()}
    if files is not None:
        r = s.request(method, url, headers=headers, data=request.form or None, files=files, allow_redirects=False)
    else:
        r = s.request(method, url, headers=headers, data=data, allow_redirects=False)
    content_type = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in content_type:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    elif "javascript" in content_type or "text/css" in content_type:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root() + "proxy").encode("utf-8")
    resp = _build_response(r, body)
    _persist_response_cookies(sid, r)
    _set_proxy_sid_cookie_in_response(resp, sid)
    _rewrite_location(r, resp)
    return resp

@app.route("/<path:path>", methods=["GET","POST","PUT","DELETE","OPTIONS","PATCH"])
def catch_all(path):
    if path == "eade-to-the-call-make-to-looken-the-good-What-ge":
        return Response("", content_type="application/javascript")
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    sid = _get_sid()
    s = requests.Session()
    _attach_cookies_to_session(s, sid)
    headers = _clean_headers()
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    r = None
    if request.files:
        files = {k: (f.filename, f.stream, f.mimetype) for k,f in request.files.items()}
        r = s.request(method, url, headers=headers, data=request.form or None, files=files, allow_redirects=False)
    else:
        r = s.request(method, url, headers=headers, data=data, allow_redirects=False)
    content_type = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in content_type:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    elif "javascript" in content_type or "text/css" in content_type:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root() + "proxy").encode("utf-8")
    resp = _build_response(r, body)
    _persist_response_cookies(sid, r)
    _set_proxy_sid_cookie_in_response(resp, sid)
    _rewrite_location(r, resp)
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=False, threaded=True)
