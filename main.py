# app.py
from flask import Flask, request, Response, redirect, url_for
import requests
import re
import os

app = Flask(__name__)
BASE_URL = "https://beaufortsc.powerschool.com"
session = requests.Session()

def forwarded_scheme_host():
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    return scheme, host

def proxy_origin():
    scheme, host = forwarded_scheme_host()
    return f"{scheme}://{host}"

def replace_urls_html(html):
    html = re.sub(r'((href|src|action))="(/[^"]*)"', r'\1="/proxy\3"', html)
    html = re.sub(r"((href|src|action))='(/[^']*)'", r"\1='/proxy\3'", html)
    html = html.replace(BASE_URL, f"{proxy_origin()}/proxy")
    html = re.sub(r'url\((["\']?)/([^)\s"\']*)\1?\)', r'url(\1/proxy/\2\1)', html)
    return html

def replace_urls_text(text):
    return text.replace(BASE_URL, f"{proxy_origin()}/proxy")

def set_cookies_from_upstream(resp, upstream):
    for c in upstream.cookies:
        secure = request.headers.get("X-Forwarded-Proto", request.scheme) == "https"
        resp.set_cookie(
            c.name,
            c.value,
            expires=c.expires,
            path=c.path or "/",
            secure=secure,
            httponly=False,
            samesite=None
        )

def pass_headers():
    h = {k: v for k, v in request.headers.items()}
    h["Host"] = "beaufortsc.powerschool.com"
    h["Referer"] = BASE_URL
    h.pop("Content-Length", None)
    h.pop("Cookie", None)
    return h

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        return redirect(url_for("home"))
    upstream = session.get(f"{BASE_URL}/public/home.html", cookies=request.cookies, headers=pass_headers(), allow_redirects=True)
    content_type = upstream.headers.get("content-type", "").lower()
    body = upstream.content
    if "text/html" in content_type:
        body = replace_urls_html(body.decode("utf-8", errors="replace")).encode("utf-8")
    resp = Response(body, content_type=upstream.headers.get("content-type", "text/html"))
    set_cookies_from_upstream(resp, upstream)
    loc = upstream.headers.get("location")
    if loc:
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
            resp.headers["location"] = f"/proxy{loc}"
        elif loc.startswith("/"):
            resp.headers["location"] = f"/proxy{loc}"
    return resp

@app.route("/proxy/<path:path>", methods=["GET", "POST"])
def proxy(path):
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    headers = pass_headers()
    data = None
    files = None
    if request.method == "POST":
        if request.files:
            files = {k: (v.filename, v.stream, v.mimetype) for k, v in request.files.items()}
            data = request.form or None
        else:
            data = request.get_data()
    upstream = session.request(request.method, url, headers=headers, cookies=request.cookies, data=data, files=files, allow_redirects=False)
    content = upstream.content
    ctype = upstream.headers.get("content-type", "").lower()
    if "text/html" in ctype:
        content = replace_urls_html(content.decode("utf-8", errors="replace")).encode("utf-8")
    elif "javascript" in ctype or "text/plain" in ctype or "text/css" in ctype:
        content = replace_urls_text(content.decode("utf-8", errors="replace")).encode("utf-8")
    resp = Response(content, content_type=upstream.headers.get("content-type", "text/plain"), status=upstream.status_code)
    set_cookies_from_upstream(resp, upstream)
    loc = upstream.headers.get("location")
    if loc:
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
            resp.headers["location"] = f"/proxy{loc}"
        elif loc.startswith("/"):
            resp.headers["location"] = f"/proxy{loc}"
        else:
            resp.headers["location"] = loc
    return resp

@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
def catch_all(path):
    if path == "eade-to-the-call-make-to-looken-the-good-What-ge":
        return Response("", content_type="application/javascript")
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"
    headers = pass_headers()
    data = None
    files = None
    if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
        if request.files:
            files = {k: (v.filename, v.stream, v.mimetype) for k, v in request.files.items()}
            data = request.form or None
        else:
            data = request.get_data()
    upstream = session.request(request.method, url, headers=headers, cookies=request.cookies, data=data, files=files, allow_redirects=False)
    content = upstream.content
    ctype = upstream.headers.get("content-type", "").lower()
    if "text/html" in ctype:
        content = replace_urls_html(content.decode("utf-8", errors="replace")).encode("utf-8")
    elif "javascript" in ctype or "text/plain" in ctype or "text/css" in ctype:
        content = replace_urls_text(content.decode("utf-8", errors="replace")).encode("utf-8")
    resp = Response(content, content_type=upstream.headers.get("content-type", "text/plain"), status=upstream.status_code)
    set_cookies_from_upstream(resp, upstream)
    loc = upstream.headers.get("location")
    if loc:
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
            resp.headers["location"] = f"/proxy{loc}"
        elif loc.startswith("/"):
            resp.headers["location"] = f"/proxy{loc}"
        else:
            resp.headers["location"] = loc
    return resp

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
