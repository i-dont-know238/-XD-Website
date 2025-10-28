import os, json, uuid, time, re
from flask import Flask, request, redirect, url_for, Response, make_response
import requests, redis

app = Flask(__name__)

BASE_URL = "https://beaufortsc.powerschool.com"
REDIS_URL = os.environ.get("REDIS_URL", "")
rdb = redis.from_url(REDIS_URL, decode_responses=True)

def _scheme():
    return request.headers.get("X-Forwarded-Proto", request.scheme)

def _host_root():
    return f"{_scheme()}://{request.host}/"

def _sid():
    s = request.cookies.get("ps_proxy_sid")
    new = False
    if not s:
        s = uuid.uuid4().hex
        new = True
    return s, new

def _key(sid):
    return f"ps:cj:{sid}"

def _load_jar(sid):
    raw = rdb.get(_key(sid))
    jar = requests.cookies.RequestsCookieJar()
    if raw:
        try:
            arr = json.loads(raw)
            for it in arr:
                jar.set(it["name"], it["value"], domain="beaufortsc.powerschool.com", path="/")
        except:
            pass
    return jar

def _save_jar(sid, jar):
    arr = []
    for c in jar:
        arr.append({"name": c.name, "value": c.value})
    rdb.setex(_key(sid), 86400, json.dumps(arr, separators=(",",":")))

def replace_urls(html):
    html = re.sub(r'(href|src|action)="(/[^"]*)"', r'\1="/proxy\2"', html)
    html = re.sub(r"(href|src|action)='(/[^']*)'", r"\1='/proxy\2'", html)
    html = html.replace(BASE_URL, _host_root() + "proxy")
    return html

def _clean_headers():
    hop = {"host","connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailers","transfer-encoding","upgrade","content-length","cookie"}
    return {k:v for k,v in request.headers.items() if k.lower() not in hop}

def _rewrite_location(upstream_resp, resp_obj):
    if "location" in upstream_resp.headers:
        loc = upstream_resp.headers["location"]
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
            resp_obj.headers["location"] = f"/proxy{loc}"
        elif loc.startswith("/"):
            resp_obj.headers["location"] = f"/proxy{loc}"

def _build_response(upstream_resp, raw_content, set_sid=None):
    headers = {k:v for k,v in upstream_resp.headers.items() if k.lower() not in {"content-length","content-encoding","transfer-encoding","connection","set-cookie"}}
    resp = make_response(raw_content, upstream_resp.status_code)
    for k,v in headers.items():
        resp.headers[k] = v
    resp.headers["Cache-Control"] = "no-store"
    if set_sid:
        resp.set_cookie("ps_proxy_sid", set_sid, path="/", secure=_scheme()=="https", samesite="Lax", httponly=True)
    return resp

def _req_with_jar(method, url, headers, sid, data=None):
    s = requests.Session()
    s.cookies = _load_jar(sid)
    r = s.request(method, url, headers=headers, data=data, allow_redirects=False, timeout=(10,30))
    for c in r.cookies:
        expired = False
        if getattr(c, "expires", None):
            try:
                expired = int(c.expires) <= int(time.time())
            except:
                expired = False
        if expired or c.value == "":
            try:
                s.cookies.clear(domain="beaufortsc.powerschool.com", path="/", name=c.name)
            except:
                pass
        else:
            s.cookies.set(c.name, c.value, domain="beaufortsc.powerschool.com", path="/")
    _save_jar(sid, s.cookies)
    return r

@app.route("/", methods=["GET","POST"])
def home():
    sid, new = _sid()
    if request.method == "POST":
        return redirect(url_for("home"))
    headers = _clean_headers()
    headers["Host"] = "beaufortsc.powerschool.com"
    headers["Referer"] = BASE_URL
    r = _req_with_jar("GET", f"{BASE_URL}/public/home.html", headers, sid)
    ct = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in ct:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    resp = _build_response(r, body, set_sid=sid if new else None)
    _rewrite_location(r, resp)
    return resp

@app.route("/proxy/<path:path>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def proxy(path):
    sid, new = _sid()
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    headers = _clean_headers()
    headers["Host"] = "beaufortsc.powerschool.com"
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    r = _req_with_jar(method, url, headers, sid, data=data)
    ct = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in ct:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    elif "javascript" in ct or "text/css" in ct:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root() + "proxy").encode("utf-8")
    resp = _build_response(r, body, set_sid=sid if new else None)
    _rewrite_location(r, resp)
    return resp

@app.route("/<path:path>", methods=["GET","POST","PUT","DELETE","OPTIONS","PATCH"])
def catch_all(path):
    if path == "eade-to-the-call-make-to-looken-the-good-What-ge":
        return Response("", content_type="application/javascript")
    sid, new = _sid()
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    headers = _clean_headers()
    headers["Host"] = "beaufortsc.powerschool.com"
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    r = _req_with_jar(method, url, headers, sid, data=data)
    ct = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in ct:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    elif "javascript" in ct or "text/css" in ct:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root() + "proxy").encode("utf-8")
    resp = _build_response(r, body, set_sid=sid if new else None)
    _rewrite_location(r, resp)
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
