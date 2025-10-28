from flask import Flask, request, Response, stream_with_context
import requests, re, os, threading, datetime
from flask_compress import Compress

app = Flask(__name__)
Compress(app)

BASE_URL = "https://beaufortsc.powerschool.com"
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ips.txt")
_lock = threading.Lock()

def _scheme():
    return request.headers.get("X-Forwarded-Proto", request.scheme)

def _root():
    return f"{_scheme()}://{request.host}/"

def _client_ip():
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or ""

@app.before_request
def _log_ip():
    try:
        line = f'{datetime.datetime.utcnow().isoformat()} {_client_ip()} {request.method} {request.path}\n'
        with _lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass

def _clean_headers():
    hop = {"host","connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailers","transfer-encoding","upgrade","content-length"}
    h = {k:v for k,v in request.headers.items() if k.lower() not in hop}
    h["Host"] = "beaufortsc.powerschool.com"
    h["Referer"] = BASE_URL
    return h

def _rewrite_location(up, resp):
    if "location" in up.headers:
        loc = up.headers["location"]
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
            resp.headers["location"] = f"/proxy{loc}"
        elif loc.startswith("/"):
            resp.headers["location"] = f"/proxy{loc}"

def _set_cookies(resp, up):
    secure = _scheme() == "https"
    for c in up.cookies:
        resp.set_cookie(c.name, c.value, path="/", secure=secure, httponly=True)

def _cache_headers(ct):
    if any(p in ct for p in ["image/", "font/", "video/", "audio/", "application/octet-stream"]):
        return {"Cache-Control": "public, max-age=86400, immutable"}
    if "text/css" in ct or "javascript" in ct:
        return {"Cache-Control": "public, max-age=3600"}
    return {}

def _resp_from_up(up, body=None, extra_headers=None):
    hdrs = {k:v for k,v in up.headers.items() if k.lower() not in {"content-length","content-encoding","transfer-encoding","connection"}}
    if extra_headers:
        hdrs.update(extra_headers)
    status = up.status_code
    if body is None:
        def gen():
            for chunk in up.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        return Response(stream_with_context(gen()), status=status, headers=hdrs)
    return Response(body, status=status, headers=hdrs)

def _replace_urls_html(b):
    s = b.decode("utf-8", errors="replace")
    s = re.sub(r'(href|src|action)="(/[^"]*)"', r'\1="/proxy\2"', s)
    s = re.sub(r"(href|src|action)='(/[^']*)'", r"\1='/proxy\2'", s)
    s = s.replace(BASE_URL, _root() + "proxy")
    return s.encode("utf-8")

def _replace_urls_text(b):
    s = b.decode("utf-8", errors="replace")
    s = s.replace(BASE_URL, _root() + "proxy")
    return s.encode("utf-8")

def _forward(method, url, needs_text_rewrite=False):
    headers = _clean_headers()
    timeout = (10, 45)
    files = None
    data = None
    if method in {"POST","PUT","PATCH","DELETE"}:
        if request.files:
            files = {k:(v.filename, v.stream, v.mimetype or "application/octet-stream") for k,v in request.files.items()}
            data = request.form
        else:
            data = request.get_data()
    stream = not needs_text_rewrite
    up = requests.request(method, url, headers=headers, cookies=request.cookies, data=data, files=files, allow_redirects=False, timeout=timeout, stream=stream)
    ct = up.headers.get("content-type","").lower()
    if needs_text_rewrite or "text/html" in ct or "javascript" in ct or "text/css" in ct:
        body = up.content
        if "text/html" in ct:
            body = _replace_urls_html(body)
        else:
            body = _replace_urls_text(body)
        resp = _resp_from_up(up, body=body, extra_headers=_cache_headers(ct))
    else:
        resp = _resp_from_up(up, body=None, extra_headers=_cache_headers(ct))
    _set_cookies(resp, up)
    _rewrite_location(up, resp)
    return resp

@app.route("/", methods=["GET","POST"])
def home():
    if request.method == "POST":
        return Response("", status=303, headers={"Location": "/"})
    url = f"{BASE_URL}/public/home.html"
    return _forward("GET", url, needs_text_rewrite=True)

@app.route("/proxy/<path:path>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])
def proxy(path):
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    return _forward(request.method.upper(), url)

@app.route("/<path:path>", methods=["GET","POST","PUT","DELETE","OPTIONS","PATCH","HEAD"])
def catch_all(path):
    if path == "eade-to-the-call-make-to-looken-the-good-What-ge":
        return Response("", content_type="application/javascript")
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    return _forward(request.method.upper(), url)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False, threaded=True)
