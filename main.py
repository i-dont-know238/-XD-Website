from flask import Flask, request, Response, redirect, make_response
import requests, re, os, secrets, threading, pickle
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
BASE_URL = "https://beaufortsc.powerschool.com"
UP = urlparse(BASE_URL)
UP_HOST = UP.netloc
SESSION_COOKIE = "PS_PROXY_ID"
SESSIONS_DIR = "/tmp/sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)
_lock = threading.Lock()

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"

def local_base(): return request.host_url.rstrip('/')

def load_session(sid):
    path = os.path.join(SESSIONS_DIR, sid)
    if os.path.exists(path):
        with open(path, "rb") as f: return pickle.load(f)
    return requests.Session()

def save_session(sid, sess):
    path = os.path.join(SESSIONS_DIR, sid)
    with open(path, "wb") as f: pickle.dump(sess, f)

def get_client_session():
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid: sid = secrets.token_urlsafe(18)
    with _lock:
        sess = load_session(sid)
    return sid, sess

def upstream_headers():
    h = {k: v for k, v in request.headers if k.lower() not in {"host","content-length","cookie"}}
    h["Host"] = UP_HOST
    h["User-Agent"] = MOBILE_UA
    h["Referer"] = BASE_URL
    h["Origin"] = BASE_URL
    return h

def rewrite_urls(text):
    text = re.sub(r"https?://" + re.escape(UP_HOST), local_base(), text)
    text = re.sub(r'(?i)(href|src|action)\s*=\s*"//'+re.escape(UP_HOST)+r'([^"]*)"', lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    return text

def proxy_request(url):
    sid, sess = get_client_session()
    data = request.get_data() if request.method in ("POST","PUT") else None
    headers = upstream_headers()
    try:
        resp = sess.request(request.method, url, headers=headers, data=data, allow_redirects=False, timeout=45)
    except Exception as e:
        return Response(f"Upstream error: {e}", 502)
    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        loc = resp.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        loc = loc.replace(BASE_URL, local_base())
        r = redirect(loc)
    else:
        body = resp.content
        if "text/html" in resp.headers.get("content-type","").lower():
            text = body.decode("utf-8", errors="replace")
            text = rewrite_urls(text)
            body = text.encode("utf-8")
        r = Response(body, status=resp.status_code)
    for c in resp.cookies:
        domain = request.host.split(":")[0]
        r.set_cookie(c.name, c.value, domain=domain, path="/", samesite="Lax", httponly=True, secure=True)
    save_session(sid, sess)
    r.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="Lax", secure=True, path="/")
    return r

@app.route("/", defaults={"path": ""}, methods=["GET","POST"])
@app.route("/<path:path>", methods=["GET","POST"])
def all_paths(path):
    url = urljoin(BASE_URL + "/", path)
    if request.query_string:
        url += "?" + request.query_string.decode()
    return proxy_request(url)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
