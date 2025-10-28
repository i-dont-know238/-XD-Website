from flask import Flask, request, Response, redirect, g
import requests
import re
import os
from urllib.parse import urljoin, urlparse

app = Flask(__name__)

BASE_URL = "https://beaufortsc.powerschool.com"
UP = urlparse(BASE_URL)
UP_NETLOC = UP.netloc

def local_base():
    return request.host_url.rstrip('/')

def header_lower_set(h):
    return {k.lower() for k in h.keys()}

def sanitize_resp_headers(h):
    blocked = {
        "content-security-policy","x-content-security-policy","x-webkit-csp",
        "x-frame-options","referrer-policy","content-encoding","transfer-encoding",
        "strict-transport-security","content-length","connection","keep-alive","upgrade",
        "proxy-authenticate","proxy-authorization","te","trailer"
    }
    return {k:v for k,v in h.items() if k.lower() not in blocked}

def upstream_headers():
    hop_by_hop = {"host","content-length","accept-encoding","connection","keep-alive","upgrade","proxy-authorization","proxy-authenticate","te","trailer","cookie"}
    h = {k: v for k, v in request.headers if k.lower() not in hop_by_hop}
    h["Host"] = UP_NETLOC
    if "origin" in header_lower_set(request.headers):
        h["Origin"] = BASE_URL
    if "referer" in header_lower_set(request.headers):
        h["Referer"] = BASE_URL
    return h

ABS_HOST_RE = re.compile(r'(?i)\bhttps?://' + re.escape(UP_NETLOC))
ATTR_ABS_DBL = re.compile(r'(?i)(href|src|action)\s*=\s*"https?://' + re.escape(UP_NETLOC) + r'([^"]*)"')
ATTR_ABS_SGL = re.compile(r"(?i)(href|src|action)\s*=\s*'https?://" + re.escape(UP_NETLOC) + r"([^']*)'")
ATTR_SCHEMELESS_DBL = re.compile(r'(?i)(href|src|action)\s*=\s*"//' + re.escape(UP_NETLOC) + r'([^"]*)"')
ATTR_SCHEMELESS_SGL = re.compile(r"(?i)(href|src|action)\s*=\s*'//" + re.escape(UP_NETLOC) + r"([^']*)'")

def rewrite_abs_urls(text):
    text = ABS_HOST_RE.sub(local_base(), text)
    text = ATTR_ABS_DBL.sub(lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = ATTR_ABS_SGL.sub(lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    text = ATTR_SCHEMELESS_DBL.sub(lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = ATTR_SCHEMELESS_SGL.sub(lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    return text

def rewrite_html_paths(text):
    text = re.sub(r'(?i)(href|src|action)\s*=\s*"/([^"]*)"', lambda m: f'{m.group(1)}="/{m.group(2)}"', text)
    text = re.sub(r"(?i)(href|src|action)\s*=\s*'/([^']*)'", lambda m: f"{m.group(1)}='/{m.group(2)}'", text)
    return text

def pass_set_cookies(flask_resp, upstream_resp):
    for c in upstream_resp.cookies:
        rest = getattr(c, "rest", {}) if hasattr(c, "rest") else getattr(c, "_rest", {})
        samesite = None
        for k in ("samesite","SameSite"):
            if k in rest:
                v = rest[k]
                if isinstance(v, str):
                    s = v.capitalize()
                    if s in ("Lax","None","Strict"):
                        samesite = s
                break
        httponly = any(k.lower()=="httponly" for k in rest.keys()) if rest else False
        flask_resp.set_cookie(
            c.name,
            c.value,
            path=c.path or "/",
            secure=bool(c.secure),
            httponly=httponly,
            samesite=samesite,
            expires=c.expires
        )

def forward(url):
    method = request.method
    headers = upstream_headers()
    data = request.get_data() if method in ("POST","PUT","PATCH","DELETE") else None
    try:
        resp = requests.request(method, url, headers=headers, cookies=request.cookies, data=data, allow_redirects=False, timeout=45)
    except Exception as e:
        return Response(f"upstream error: {e}", status=502)

    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        loc = resp.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        loc = ABS_HOST_RE.sub(local_base(), loc)
        r = redirect(loc, code=resp.status_code)
        pass_set_cookies(r, resp)
        r.headers["Cache-Control"] = "no-store"
        return r

    ctype = resp.headers.get("content-type","").lower()
    body = resp.content

    if "text/html" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_urls(t)
        t = rewrite_html_paths(t)
        body = t.encode("utf-8")
    elif "javascript" in ctype or "json" in ctype or "text/css" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_urls(t)
        body = t.encode("utf-8")

    r = Response(body, status=resp.status_code)
    rh = sanitize_resp_headers(resp.headers)
    for k,v in rh.items():
        r.headers[k] = v
    if "Content-Type" not in r.headers and "content-type" in rh:
        r.headers["Content-Type"] = rh.get("content-type")
    pass_set_cookies(r, resp)
    r.headers["Cache-Control"] = "no-store"
    return r

@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"])
@app.route("/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"])
def all_paths(path):
    target = urljoin(BASE_URL + "/", path)
    if request.query_string:
        target += ("&" if "?" in target else "?") + request.query_string.decode()
    return forward(target)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
