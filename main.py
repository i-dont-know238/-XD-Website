from flask import Flask, request, Response, redirect, make_response
from werkzeug.middleware.proxy_fix import ProxyFix
import requests
import re
import os
import secrets
import threading
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

BASE_URL = "https://beaufortsc.powerschool.com"
UP = urlparse(BASE_URL)
UP_HOST = UP.netloc
SESSION_COOKIE = "PS_PROXY_ID"
_sessions = {}
_lock = threading.Lock()

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"

ABS_HOST_RE = re.compile(r'(?i)\bhttps?://' + re.escape(UP_HOST))
ATTR_ABS_DBL = re.compile(r'(?i)(href|src|action)\s*=\s*"https?://' + re.escape(UP_HOST) + r'([^"]*)"')
ATTR_ABS_SGL = re.compile(r"(?i)(href|src|action)\s*=\s*'https?://" + re.escape(UP_HOST) + r"([^']*)'")
ATTR_SCHEMELESS_DBL = re.compile(r'(?i)(href|src|action)\s*=\s*"//' + re.escape(UP_HOST) + r'([^"]*)"')
ATTR_SCHEMELESS_SGL = re.compile(r"(?i)(href|src|action)\s*=\s*'//" + re.escape(UP_HOST) + r"([^']*)'")
REL_ATTR_DBL = re.compile(r'(?i)(href|src|action)\s*=\s*"(\/[^"]*)"')
REL_ATTR_SGL = re.compile(r"(?i)(href|src|action)\s*=\s*'(\/[^']*)'")
BASE_TAG_DBL = re.compile(r'(?i)<base[^>]*\bhref\s*=\s*"([^"]+)"')
BASE_TAG_SGL = re.compile(r"(?i)<base[^>]*\bhref\s*=\s*'([^']+)'")
CSS_URL_ABS = re.compile(r'url\(\s*["\']?https?://' + re.escape(UP_HOST) + r'([^)"\']*)["\']?\s*\)')
CSS_URL_SCHEMELESS = re.compile(r'url\(\s*["\']?//' + re.escape(UP_HOST) + r'([^)"\']*)["\']?\s*\)')
CSS_URL_REL = re.compile(r'url\(\s*["\']?(\/[^)"\']*)["\']?\s*\)')

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
    h["User-Agent"] = MOBILE_UA
    h["Origin"] = BASE_URL
    h["Referer"] = BASE_URL
    h["Accept"] = request.headers.get("Accept", "*/*")
    h["Accept-Language"] = request.headers.get("Accept-Language", "en-US,en;q=0.9")
    return h

def sanitize_resp_headers(h):
    return {k: v for k, v in h.items() if k.lower() not in BLOCKED_RESP_HEADERS}

def rewrite_text_urls(text):
    text = ABS_HOST_RE.sub(local_base(), text)
    text = ATTR_ABS_DBL.sub(lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = ATTR_ABS_SGL.sub(lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    text = ATTR_SCHEMELESS_DBL.sub(lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = ATTR_SCHEMELESS_SGL.sub(lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    text = BASE_TAG_DBL.sub(lambda m: f'<base href="{local_base()}/"', text)
    text = BASE_TAG_SGL.sub(lambda m: f"<base href='{local_base()}/'", text)
    return text

def rewrite_rel_attrs(text):
    text = REL_ATTR_DBL.sub(lambda m: f'{m.group(1)}="{m.group(2)}"', text)
    text = REL_ATTR_SGL.sub(lambda m: f"{m.group(1)}='{m.group(2)}'", text)
    return text

def rewrite_css(text):
    text = CSS_URL_ABS.sub(lambda m: f'url({local_base()}{m.group(1)})', text)
    text = CSS_URL_SCHEMELESS.sub(lambda m: f'url({local_base()}{m.group(1)})', text)
    text = CSS_URL_REL.sub(lambda m: f'url({m.group(1)})', text)
    return text

def inject_client_patch(html):
    patch = f"""<script>
(function(){{
  var UH = "{UP_HOST}";
  function fix(u){{
    try{{var a=new URL(u, window.location.href); if(a.host===UH){{a.protocol=window.location.protocol; a.host=window.location.host; return a.toString();}}}}catch(e){{}}
    return u;
  }}
  var ofetch = window.fetch;
  if(ofetch){{ window.fetch = function(input, init){{ if(typeof input==="string") input = fix(input); else if(input&&input.url) input.url = fix(input.url); return ofetch(input, init); }}; }}
  var OX = window.XMLHttpRequest;
  if(OX){{ window.XMLHttpRequest = function(){{ var x = new OX(); var o = x.open; x.open = function(m,u){ u = fix(u); return o.apply(this, arguments); }; return x; }}; }}
}})();
</script>"""
    if "</head>" in html.lower():
        idx = html.lower().rfind("</head>")
        return html[:idx] + patch + html[idx:]
    return patch + html

def try_mobile_fallback(url, sess, headers, data):
    p = urlparse(url)
    path = p.path
    qs = p.query
    if "/guardian/scores.html" not in path:
        return None
    q = dict(parse_qsl(qs, keep_blank_values=True))
    q["mobile"] = "1"
    candidate1 = urlunparse((p.scheme, p.netloc, "/guardian/scores.html", "", urlencode(q, doseq=True), ""))
    r1 = sess.request(request.method, candidate1, headers=headers, data=data, allow_redirects=False, timeout=45)
    if r1.status_code == 200:
        return r1
    for cand in ["/guardian/m/scores.html", "/guardian/mobile/scores.html"]:
        u = urlunparse((p.scheme, p.netloc, cand, "", urlencode(dict(parse_qsl(qs, keep_blank_values=True)), doseq=True), ""))
        r = sess.request(request.method, u, headers=headers, data=data, allow_redirects=False, timeout=45)
        if r.status_code == 200:
            return r
    return None

def forward_to_upstream(url):
    sid, sess = get_client_session()
    method = request.method
    headers = upstream_headers()
    data = request.get_data() if method in ("POST","PUT","PATCH","DELETE") else None
    try:
        resp = sess.request(method, url, headers=headers, data=data, allow_redirects=False, timeout=45)
    except Exception as e:
        r = make_response(f"upstream error: {e}", 502)
        r.headers["Cache-Control"] = "no-store"
        r.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Lax", secure=is_secure_request(), path="/")
        return r
    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        loc = resp.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        loc = ABS_HOST_RE.sub(local_base(), loc)
        r = redirect(loc, code=resp.status_code)
        r.headers["Cache-Control"] = "no-store"
        r.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Lax", secure=is_secure_request(), path="/")
        return r
    if resp.status_code != 200:
        fb = try_mobile_fallback(url, sess, headers, data)
        if fb is not None:
            resp = fb
    ctype = resp.headers.get("content-type","").lower()
    body = resp.content
    if "text/html" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_text_urls(t)
        t = rewrite_rel_attrs(t)
        t = inject_client_patch(t)
        body = t.encode("utf-8")
    elif "text/css" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_css(t)
        body = t.encode("utf-8")
    elif "javascript" in ctype or "json" in ctype or "xml" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_text_urls(t)
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

@app.route("/eade-to-the-call-make-to-looken-the-good-What-ge", methods=["GET","POST"])
def sink_beacon():
    return ("", 204) if request.method == "POST" else ("ok", 200)

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
