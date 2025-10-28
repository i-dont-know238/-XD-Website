from flask import Flask, request, Response, redirect, session
import requests
import re, os, uuid
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
app.secret_key = os.urandom(32)
BASE_URL = "https://beaufortsc.powerschool.com"
UP = urlparse(BASE_URL).netloc
user_sessions = {}

def local_host():
    return request.host_url.rstrip('/')

def rewrite_urls(text):
    text = text.replace(f"https://{UP}", local_host())
    text = text.replace(f"http://{UP}", local_host())
    text = re.sub(r'(?i)(href|src|action)\s*=\s*"(/[^"]*)"', lambda m: f'{m.group(1)}="{local_host()}{m.group(2)}"', text)
    text = re.sub(r"(?i)(href|src|action)\s*=\s*'(/[^']*)'", lambda m: f"{m.group(1)}='{local_host()}{m.group(2)}'", text)
    return text

def clean_headers(h):
    blocked = {'content-security-policy','x-frame-options','content-encoding','transfer-encoding','strict-transport-security','referrer-policy'}
    return {k:v for k,v in h.items() if k.lower() not in blocked}

def get_client_session():
    sid = session.get("sid")
    if not sid or sid not in user_sessions:
        sid = str(uuid.uuid4())
        session["sid"] = sid
        user_sessions[sid] = requests.Session()
    return user_sessions[sid]

def forward(url):
    s = get_client_session()
    headers = {k:v for k,v in request.headers if k.lower() not in ('host','content-length','accept-encoding')}
    headers['Host'] = UP
    headers['Referer'] = BASE_URL
    data = request.get_data() if request.method in ('POST','PUT','PATCH') else None
    try:
        r = s.request(request.method, url, headers=headers, data=data, cookies=s.cookies, allow_redirects=False, timeout=30)
    except Exception as e:
        return Response(f"Proxy error: {e}", status=502)

    if 300 <= r.status_code < 400 and 'Location' in r.headers:
        loc = r.headers['Location']
        if not urlparse(loc).netloc:
            loc = urljoin(BASE_URL, loc)
        loc = rewrite_urls(loc)
        resp = redirect(loc)
        for c in r.cookies:
            resp.set_cookie(c.name, c.value, path='/')
        return resp

    ctype = r.headers.get('content-type','').lower()
    body = r.content

    if 'text/html' in ctype:
        t = body.decode('utf-8', errors='replace')
        t = rewrite_urls(t)
        t = re.sub(r"https?://"+re.escape(UP), local_host(), t)
        body = t.encode('utf-8')
    elif 'javascript' in ctype or 'json' in ctype or 'css' in ctype:
        t = body.decode('utf-8', errors='replace')
        t = rewrite_urls(t)
        body = t.encode('utf-8')

    resp = Response(body, status=r.status_code)
    h = clean_headers(r.headers)
    for k,v in h.items(): resp.headers[k] = v
    for c in r.cookies: resp.set_cookie(c.name, c.value, path='/')
    return resp

@app.route('/', defaults={'path': ''}, methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'])
@app.route('/<path:path>', methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'])
def route_all(path):
    url = urljoin(BASE_URL + '/', path)
    if request.query_string:
        url += ('&' if '?' in url else '?') + request.query_string.decode()
    return forward(url)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Proxy ready on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
