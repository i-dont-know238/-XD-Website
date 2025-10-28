from flask import Flask, request, Response, redirect, session
import requests
import re, os, uuid
from urllib.parse import urljoin, urlparse
from flask_session import Session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

BASE_URL = "https://beaufortsc.powerschool.com"
UP_NETLOC = urlparse(BASE_URL).netloc

def local_base():
    return request.host_url.rstrip("/")

def rewrite_abs_urls(text):
    return text.replace("https://" + UP_NETLOC, local_base()).replace("http://" + UP_NETLOC, local_base())

def rewrite_html_attrs(text):
    text = re.sub(r'(?i)(href|src|action)\s*=\s*"https?://'+re.escape(UP_NETLOC)+r'([^"]*)"', lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = re.sub(r"(?i)(href|src|action)\s*=\s*'https?://"+re.escape(UP_NETLOC)+r"([^']*)'", lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    text = re.sub(r'(?i)(href|src|action)\s*=\s*"/', lambda m: f'{m.group(1)}="{local_base()}/', text)
    text = re.sub(r"(?i)(href|src|action)\s*=\s*'/", lambda m: f"{m.group(1)}='{local_base()}/", text)
    return text

def sanitize_resp_headers(h):
    blocked = {"content-security-policy","x-content-security-policy","x-webkit-csp","x-frame-options","referrer-policy","content-encoding","transfer-encoding","strict-transport-security"}
    return {k:v for k,v in h.items() if k.lower() not in blocked}

def get_session():
    if "proxy_id" not in session:
        session["proxy_id"] = str(uuid.uuid4())
    sid = session["proxy_id"]
    if "sessions" not in app.config:
        app.config["sessions"] = {}
    if sid not in app.config["sessions"]:
        app.config["sessions"][sid] = requests.Session()
    return app.config["sessions"][sid]

def make_request(url):
    s = get_session()
    headers = {k:v for k,v in request.headers if k.lower() not in ("host","content-length","accept-encoding","cookie")}
    headers["Host"] = UP_NETLOC
    headers["Referer"] = BASE_URL
    method = request.method
    data = request.get_data()
    try:
        resp = s.request(method, url, data=data if method in ("POST","PUT","PATCH","DELETE") else None, headers=headers, allow_redirects=False, timeout=45)
    except Exception as e:
        return Response(f"upstream error: {e}", status=502)

    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        loc = resp.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        loc = rewrite_abs_urls(loc)
        r = redirect(loc, code=resp.status_code)
        return r

    ctype = resp.headers.get("content-type","").lower()
    body = resp.content

    if "text/html" in ctype:
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_urls(t)
        t = rewrite_html_attrs(t)
        body = t.encode("utf-8")
    elif any(x in ctype for x in ("javascript","json","css")):
        t = body.decode("utf-8", errors="replace")
        t = rewrite_abs_urls(t)
        body = t.encode("utf-8")

    r = Response(body, status=resp.status_code)
    for k,v in sanitize_resp_headers(resp.headers).items():
        r.headers[k] = v
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
