from flask import Flask, request, Response, redirect, session as flask_session
import requests
import re, os, uuid
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32))

BASE_URL = "https://beaufortsc.powerschool.com"
UP_NETLOC = urlparse(BASE_URL).netloc

def get_client_session():
    sid = flask_session.get("sid")
    if not sid:
        sid = str(uuid.uuid4())
        flask_session["sid"] = sid
    if "sessions" not in flask_session:
        flask_session["sessions"] = {}
    if sid not in flask_session["sessions"]:
        flask_session["sessions"][sid] = requests.Session()
    return flask_session["sessions"][sid]

def local_base():
    return request.host_url.rstrip('/')

def rewrite_urls(text):
    text = text.replace(f"https://{UP_NETLOC}", local_base())
    text = text.replace(f"http://{UP_NETLOC}", local_base())
    text = re.sub(r'(?i)(href|src|action)="(/[^"]*)"', lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', text)
    text = re.sub(r"(?i)(href|src|action)='(/[^']*)'", lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", text)
    return text

def make_request(url):
    s = get_client_session()
    headers = {k: v for k, v in request.headers if k.lower() not in ("host","content-length","accept-encoding")}
    headers["Host"] = UP_NETLOC
    headers["Referer"] = BASE_URL
    method = request.method

    try:
        r = s.request(method, url, data=request.get_data(), cookies=request.cookies,
                      headers=headers, allow_redirects=False, timeout=30)
    except Exception as e:
        return Response(f"Proxy error: {e}", status=502)

    if 300 <= r.status_code < 400 and "Location" in r.headers:
        loc = r.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        return redirect(loc.replace(BASE_URL, local_base()))

    content_type = r.headers.get("content-type","text/html").lower()
    body = r.content
    if "text/html" in content_type or "javascript" in content_type or "css" in content_type:
        text = body.decode("utf-8", errors="replace")
        text = rewrite_urls(text)
        body = text.encode("utf-8")

    resp = Response(body, status=r.status_code, content_type=content_type)
    for c in r.cookies:
        resp.set_cookie(c.name, c.value, path="/", httponly=True, samesite="Lax")
    return resp

@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE"])
@app.route("/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE"])
def proxy(path):
    target = urljoin(BASE_URL + "/", path)
    if request.query_string:
        target += "?" + request.query_string.decode()
    return make_request(target)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
