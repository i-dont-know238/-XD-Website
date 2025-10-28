from flask import Flask, request, Response, redirect
import requests
import re
import os
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
BASE_URL = "https://beaufortsc.powerschool.com"
UP_NETLOC = urlparse(BASE_URL).netloc
session = requests.Session()

def local_base():
    return request.host_url.rstrip('/')

def rewrite_abs_urls(text):
    return text.replace("http://" + UP_NETLOC, local_base()).replace("https://" + UP_NETLOC, local_base())

def rewrite_html_attrs(text):
    text = re.sub(r'(?i)(href|src|action)\s*=\s*"https?://'+re.escape(UP_NETLOC)+r'([^"]*)"', lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = re.sub(r"(?i)(href|src|action)\s*=\s*'https?://"+re.escape(UP_NETLOC)+r"([^']*)'", lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    return text

def sanitize_resp_headers(h):
    blocked = {"content-security-policy","x-content-security-policy","x-webkit-csp","x-frame-options","referrer-policy","content-encoding","transfer-encoding","strict-transport-security"}
    return {k:v for k,v in h.items() if k.lower() not in blocked}

def upstream_headers():
    h = {k: v for k, v in request.headers if k.lower() not in ("host","content-length","accept-encoding","cookie")}
    h["Host"] = UP_NETLOC
    h["Referer"] = BASE_URL if "referer" in {k.lower() for k in request.headers.keys()} else BASE_URL
    if "origin" in {k.lower() for k in request.headers.keys()}:
        h["Origin"] = BASE_URL
    return h

def make_request(url):
    method = request.method
    headers = upstream_headers()
    data = request.get_data()
    try:
        resp = session.request(method, url, params=None, data=data if method in ("POST","PUT","PATCH","DELETE") else None, headers=headers, cookies=request.cookies, allow_redirects=False, timeout=45)
    except Exception as e:
        return Response(f"upstream error: {e}", status=502)

    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        loc = resp.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        loc = rewrite_abs_urls(loc)
        r = redirect(loc, code=resp.status_code)
        for c in resp.cookies:
            r.set_cookie(c.name, c.value, path="/")
        return r

    ctype = resp.headers.get("content-type","").lower()
    body = resp.content

    if "text/html" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_urls(t)
        t = rewrite_html_attrs(t)
        body = t.encode("utf-8")
    elif "javascript" in ctype or "json" in ctype or "text/css" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_urls(t)
        body = t.encode("utf-8")

    r = Response(body, status=resp.status_code)
    rh = sanitize_resp_headers(resp.headers)
    if "content-type" in {k.lower() for k in rh}:
        r.headers["Content-Type"] = rh.get("Content-Type", rh.get("content-type"))
    if "cache-control" in {k.lower() for k in rh}:
        r.headers["Cache-Control"] = rh.get("Cache-Control", rh.get("cache-control"))
    if "last-modified" in {k.lower() for k in rh}:
        r.headers["Last-Modified"] = rh.get("Last-Modified", rh.get("last-modified"))
    for c in resp.cookies:
        r.set_cookie(c.name, c.value, path="/")
    return r

@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"])
@app.route("/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"])
def all_paths(path):
    target = urljoin(BASE_URL + "/", path)
    if request.query_string:
        target += ("&" if "?" in target else "?") + request.query_string.decode()
    return make_request(target)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Proxy running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
