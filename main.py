from flask import Flask, request, Response, redirect, url_for
import requests, re

app = Flask(__name__)
BASE_URL = "https://beaufortsc.powerschool.com"
session = requests.Session()

def replace_urls(html):
    html = html.replace(BASE_URL, f"{request.host_url.rstrip('/')}/proxy")
    html = re.sub(r'(href|src|action)="(/[^"]*)"', lambda m: f'{m.group(1)}="/proxy{m.group(2)}"', html)
    html = re.sub(r"(href|src|action)='(/[^']*)'", lambda m: f"{m.group(1)}='/proxy{m.group(2)}'", html)
    return html

def sync_cookies_from_browser():
    session.cookies.clear()
    for k, v in request.cookies.items():
        session.cookies.set(k, v)

def apply_cookies_to_response(r, resp):
    for c in r.cookies:
        resp.set_cookie(c.name, c.value, expires=c.expires, path='/', secure=False, samesite='Lax')

@app.route('/', methods=['GET', 'POST'])
def home():
    sync_cookies_from_browser()
    r = session.get(f"{BASE_URL}/public/home.html", allow_redirects=True)
    html = replace_urls(r.text)
    resp = Response(html, content_type='text/html')
    apply_cookies_to_response(r, resp)
    return resp

@app.route('/proxy/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    sync_cookies_from_browser()
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url += f"?{request.query_string.decode('utf-8', 'ignore')}"

    headers = {k: v for k, v in request.headers.items()}
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = BASE_URL
    headers.pop('Content-Length', None)
    headers.pop('Cookie', None)

    if request.method == 'POST':
        if request.files:
            r = session.post(url, data=request.form or None, files=request.files or None, headers=headers)
        else:
            r = session.post(url, data=request.get_data(), headers=headers)
    else:
        r = session.get(url, headers=headers, allow_redirects=True)

    data = r.content
    ct = r.headers.get('content-type', '').lower()

    if 'text/html' in ct:
        data = replace_urls(data.decode('utf-8', 'replace')).encode()
    elif 'javascript' in ct:
        data = data.decode('utf-8', 'replace').replace(BASE_URL, f"{request.host_url.rstrip('/')}/proxy").encode()

    resp = Response(data, content_type=r.headers.get('content-type', 'text/plain'))
    apply_cookies_to_response(r, resp)

    if 'location' in r.headers:
        loc = r.headers['location']
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
        if loc.startswith('/'):
            resp.headers['location'] = f"/proxy{loc}"

    return resp

@app.route('/<path:path>', methods=['GET', 'POST'])
def catch_all(path):
    return redirect(f"/proxy/{path}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True, threaded=True)
