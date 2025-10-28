from flask import Flask, request, redirect, url_for, Response
import requests
import re

app = Flask(__name__)

BASE_URL = "https://beaufortsc.powerschool.com"
session = requests.Session()

def _scheme():
    return request.headers.get("X-Forwarded-Proto", request.scheme)

def _host_root():
    return f"{_scheme()}://{request.host}/"

def replace_urls(html):
    html = re.sub(r'(href|src|action)="(/[^"]*)"', r'\1="/proxy\2"', html)
    html = re.sub(r"(href|src|action)='(/[^']*)'", r"\1='/proxy\2'", html)
    html = html.replace(BASE_URL, _host_root() + "proxy")
    return html

def _clean_headers():
    hop = {"host","connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailers","transfer-encoding","upgrade","content-length"}
    headers = {k:v for k,v in request.headers.items() if k.lower() not in hop}
    headers["Host"] = "beaufortsc.powerschool.com"
    return headers

def _set_cookies(resp_obj, upstream_resp):
    secure = _scheme() == "https"
    for c in upstream_resp.cookies:
        resp_obj.set_cookie(
            c.name,
            c.value,
            path="/",
            secure=secure,
            httponly=False,
            samesite="Lax"
        )

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

@app.route("/", methods=["GET","POST"])
def home():
    if request.method == "POST":
        return redirect(url_for("home"))
    r = session.get(f"{BASE_URL}/public/home.html", headers=_clean_headers(), allow_redirects=False)
    content_type = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in content_type:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    resp = _build_response(r, body)
    _set_cookies(resp, r)
    _rewrite_location(r, resp)
    return resp

@app.route("/proxy/<path:path>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def proxy(path):
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    headers = _clean_headers()
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    r = session.request(method, url, headers=headers, data=data, allow_redirects=False)
    content_type = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in content_type:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    elif "javascript" in content_type or "text/css" in content_type:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root() + "proxy").encode("utf-8")
    resp = _build_response(r, body)
    _set_cookies(resp, r)
    _rewrite_location(r, resp)
    return resp

@app.route("/<path:path>", methods=["GET","POST","PUT","DELETE","OPTIONS","PATCH"])
def catch_all(path):
    if path == "eade-to-the-call-make-to-looken-the-good-What-ge":
        return Response("", content_type="application/javascript")
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    headers = _clean_headers()
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    r = session.request(method, url, headers=headers, data=data, allow_redirects=False)
    content_type = r.headers.get("content-type","").lower()
    body = r.content
    if "text/html" in content_type:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    elif "javascript" in content_type or "text/css" in content_type:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root() + "proxy").encode("utf-8")
    resp = _build_response(r, body)
    _set_cookies(resp, r)
    _rewrite_location(r, resp)
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
