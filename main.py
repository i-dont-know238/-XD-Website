from flask import Flask, request, Response, redirect, g
import requests
import re
import os
import secrets
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
BASE_URL = "https://beaufortsc.powerschool.com"
UP = urlparse(BASE_URL)
UP_NETLOC = UP.netloc
SESSIONS = {}

def local_base():
    return request.host_url.rstrip('/')

def ensure_sid():
    sid = request.cookies.get("proxy_sid")
    ua = request.headers.get("User-Agent","")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    created = False
    if not sid or sid not in SESSIONS:
        sid = secrets.token_urlsafe(32)
        SESSIONS[sid] = {"session": requests.Session(), "ua": ua, "ip": ip}
        created = True
    else:
        info = SESSIONS[sid]
        if info.get("ua") != ua or info.get("ip") != ip:
            sid = secrets.token_urlsafe(32)
            SESSIONS[sid] = {"session": requests.Session(), "ua": ua, "ip": ip}
            created = True
    g.proxy_sid = sid
    g.set_cookie = created

@app.before_request
def _before():
    ensure_sid()

@app.after_request
def _after(resp):
    if getattr(g, "set_cookie", False):
        resp.set_cookie("proxy_sid", g.proxy_sid, path="/", secure=True, httponly=True, samesite="Lax")
    return resp

def upstream_headers(target_url):
    h = {}
    for k, v in request.headers:
        kl = k.lower()
        if kl in ("host","content-length","cookie","accept-encoding","origin"):
            continue
        h[k] = v
    h["Host"] = UP_NETLOC
    h["Referer"] = urljoin(BASE_URL + "/", request.path.lstrip("/"))
    h["Origin"] = BASE_URL
    return h

def rewrite_abs_hosts(text):
    text = text.replace("https://" + UP_NETLOC, local_base()).replace("http://" + UP_NETLOC, local_base())
    text = re.sub(r"(?i)(['\"])//"+re.escape(UP_NETLOC), r"\1"+local_base(), text)
    return text

def rewrite_html_attrs(text):
    text = re.sub(r'(?i)(href|src|action)\s*=\s*"//'+re.escape(UP_NETLOC)+r'([^"]*)"', lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = re.sub(r"(?i)(href|src|action)\s*=\s*'//"+re.escape(UP_NETLOC)+r"([^']*)'", lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    text = re.sub(r'(?i)(href|src|action)\s*=\s*"/([^"]*)"', lambda m: f'{m.group(1)}="{local_base()}/{m.group(2)}"', text)
    text = re.sub(r"(?i)(href|src|action)\s*=\s*'/([^']*)'", lambda m: f"{m.group(1)}='{local_base()}/{m.group(2)}'", text)
    return text

def rewrite_css(text, resource_path=""):
    def repl(m):
        raw = m.group(1).strip()
        q = ""
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            q = raw[0]
            raw = raw[1:-1]
        u = raw
        if raw.startswith("https://"+UP_NETLOC) or raw.startswith("http://"+UP_NETLOC):
            u = local_base() + raw.split(UP_NETLOC,1)[1]
        elif raw.startswith("//"+UP_NETLOC):
            u = local_base() + raw[len("//"+UP_NETLOC):]
        elif raw.startswith("/"):
            u = local_base() + raw
        return f"url({q}{u}{q})"
    text = re.sub(r"url\(([^)]+)\)", repl, text)
    text = re.sub(r'@import\s+([\'"])//'+re.escape(UP_NETLOC)+r'([^\'"]*)([\'"])', lambda m: f"@import {m.group(1)}{local_base()}{m.group(2)}{m.group(3)}", text)
    text = re.sub(r'@import\s+([\'"])/([^\'"]*)([\'"])', lambda m: f"@import {m.group(1)}{local_base()}/{m.group(2)}{m.group(3)}", text)
    return text

def sanitize_resp_headers(h):
    drop = {"content-security-policy","x-content-security-policy","x-webkit-csp","x-frame-options","referrer-policy","content-encoding","transfer-encoding","strict-transport-security"}
    return {k:v for k,v in h.items() if k.lower() not in drop}

def process_body(body, ctype, resource_path=""):
    if "text/html" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_hosts(t)
        t = rewrite_html_attrs(t)
        return t.encode("utf-8")
    if "text/css" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_hosts(t)
        t = rewrite_css(t, resource_path)
        return t.encode("utf-8")
    if "javascript" in ctype or "application/json" in ctype or "text/json" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_hosts(t)
        return t.encode("utf-8")
    return body

def copy_set_cookies(flask_resp, req_resp):
    for c in req_resp.cookies:
        flask_resp.set_cookie(c.name, c.value, path="/")

def make_request(url):
    s = SESSIONS[g.proxy_sid]["session"]
    headers = upstream_headers(url)
    method = request.method.upper()
    data = None
    json_data = None
    files = None
    if method in ("POST","PUT","PATCH","DELETE"):
        if request.files:
            files = {k:(v.filename, v.stream, v.mimetype or "application/octet-stream") for k,v in request.files.items()}
            data = request.form.to_dict(flat=False)
        else:
            if request.is_json:
                json_data = request.get_json(silent=True)
            else:
                data = request.get_data()
    try:
        resp = s.request(method, url, headers=headers, data=data, json=json_data, files=files, allow_redirects=False, timeout=45)
    except Exception as e:
        return Response(f"upstream error: {e}", status=502)
    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        loc = resp.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL + "/", loc)
        loc = rewrite_abs_hosts(loc)
        r = redirect(loc, code=resp.status_code)
        copy_set_cookies(r, resp)
        return r
    ctype = resp.headers.get("content-type","").lower()
    body = process_body(resp.content, ctype, resource_path=urlparse(url).path)
    r = Response(body, status=resp.status_code)
    rh = sanitize_resp_headers(resp.headers)
    for k,v in rh.items():
        if k.lower() == "set-cookie":
            continue
        r.headers[k] = v
    copy_set_cookies(r, resp)
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
