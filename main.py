from flask import Flask, request, Response, redirect, session
import requests
import re, os
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretproxy")
BASE_URL = "https://beaufortsc.powerschool.com"
UP = urlparse(BASE_URL)
UP_NETLOC = UP.netloc

user_sessions = {}

def get_client_session():
    ip = request.remote_addr
    if ip not in user_sessions:
        user_sessions[ip] = requests.Session()
    return user_sessions[ip]

def local_base():
    return request.host_url.rstrip('/')

def rewrite_html(html):
    html = re.sub(r'(?i)(href|src|action)\s*=\s*"(/[^"]*)"', lambda m: f'{m.group(1)}="{local_base()}{m.group(2)}"', html)
    html = re.sub(r"(?i)(href|src|action)\s*=\s*'(/[^']*)'", lambda m: f"{m.group(1)}='{local_base()}{m.group(2)}'", html)
    html = html.replace(BASE_URL, local_base())
    return html

def sanitize_headers(h):
    bad = {"content-encoding","transfer-encoding","content-length","connection",
           "content-security-policy","x-frame-options","strict-transport-security"}
    return {k:v for k,v in h.items() if k.lower() not in bad}

def make_request(url):
    s = get_client_session()
    headers = {k:v for k,v in request.headers if k.lower() not in ("host","content-length")}
    headers["Host"] = UP_NETLOC
    headers["Referer"] = BASE_URL

    try:
        resp = s.request(request.method, url, data=request.get_data(), headers=headers,
                         cookies=s.cookies, allow_redirects=False, timeout=40)
    except Exception as e:
        return Response(f"Error contacting {BASE_URL}: {e}", status=500)

    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        loc = resp.headers["Location"]
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        loc = loc.replace(BASE_URL, local_base())
        return redirect(loc, code=resp.status_code)

    content_type = resp.headers.get("content-type","").lower()
    body = resp.content

    if "text/html" in content_type:
        html = body.decode("utf-8", errors="replace")
        html = rewrite_html(html)
        body = html.encode("utf-8")
    elif any(t in content_type for t in ["javascript","json","css","plain"]):
        body = resp.text.replace(BASE_URL, local_base()).encode("utf-8")

    r = Response(body, status=resp.status_code)
    for k,v in sanitize_headers(resp.headers).items():
        r.headers[k] = v
    for c in resp.cookies:
        r.set_cookie(c.name, c.value, path="/")
    r.headers["Cache-Control"] = "no-store"
    return r

@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
@app.route("/<path:path>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def all_routes(path):
    ip = request.remote_addr
    if ip not in user_sessions:
        user_sessions[ip] = requests.Session()
    url = urljoin(BASE_URL + "/", path)
    if request.query_string:
        url += "?" + request.query_string.decode()
    return make_request(url)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Running PowerSchool Proxy on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
