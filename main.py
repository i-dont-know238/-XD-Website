from flask import Flask, request, Response, make_response, redirect
import requests
import re
import os
import urllib.parse

app = Flask(__name__)

BASE_URL = "https://beaufortsc.powerschool.com"
PROXY_PREFIX = "/proxy"

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; Proxy/1.0)"})

def build_proxy_url(path):
    return f"{PROXY_PREFIX}/{path}"

def replace_urls(html, base_host):
    html = re.sub(
        r'(href|src|action)=["\'](/[^"\']*)["\']',
        lambda m: f'{m.group(1)}="{build_proxy_url(m.group(2)[1:])}"',
        html,
        flags=re.IGNORECASE
    )
    html = re.sub(
        rf'(href|src|action)=["\']({re.escape(BASE_URL)}/?)([^"\']*)["\']',
        lambda m: f'{m.group(1)}="{build_proxy_url(m.group(3))}"',
        html,
        flags=re.IGNORECASE
    )
    return html

def proxy_request(target_url):
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ('host', 'content-length', 'cookie', 'connection')
    }
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = BASE_URL
    headers['Origin'] = BASE_URL

    cookies = {k: v for k, v in request.cookies.items()}

    try:
        if request.method == 'POST':
            resp = session.post(
                target_url,
                data=request.form,
                headers=headers,
                cookies=cookies,
                allow_redirects=False,
                timeout=30
            )
        else:
            resp = session.get(
                target_url,
                headers=headers,
                cookies=cookies,
                params=request.args,
                allow_redirects=False,
                timeout=30
            )
    except Exception as e:
        return Response(f"Proxy error: {str(e)}", status=502)

    excluded_headers = ['content-length', 'transfer-encoding', 'content-encoding']
    response_headers = [
        (name, value) for name, value in resp.headers.items()
        if name.lower() not in excluded_headers
    ]

    content_type = resp.headers.get('Content-Type', '').lower()
    content = resp.raw.read()

    if resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get('Location', '')
        if location.startswith(BASE_URL):
            new_location = build_proxy_url(location[len(BASE_URL):].lstrip('/'))
        elif location.startswith('/'):
            new_location = build_proxy_url(location.lstrip('/'))
        else:
            new_location = location
        return redirect(new_location, code=resp.status_code)

    if 'text/html' in content_type:
        try:
            html = content.decode('utf-8', errors='replace')
            html = replace_urls(html, BASE_URL)
            content = html.encode('utf-8')
            content_type = 'text/html; charset=utf-8'
        except:
            pass
    elif 'javascript' in content_type or 'css' in content_type:
        try:
            text = content.decode('utf-8', errors='replace')
            text = text.replace(BASE_URL, request.host_url.rstrip('/') + PROXY_PREFIX)
            text = re.sub(
                r'url\((["\']?)/',
                lambda m: f'url({m.group(1)}{build_proxy_url("")}'.lstrip('/'),
                text
            )
            content = text.encode('utf-8')
        except:
            pass

    response = make_response(Response(content, status=resp.status_code))
    response.headers = dict(response_headers)
    response.headers['Content-Type'] = content_type

    for name, value in resp.cookies.items():
        response.set_cookie(
            name, value,
            domain=request.host,
            path='/',
            secure=resp.cookies.get(name).get('secure', False),
            httponly=True,
            samesite='Lax'
        )

    return response

@app.route('/', methods=['GET'])
def root():
    return proxy_request(f"{BASE_URL}/public/home.html")

@app.route(f'{PROXY_PREFIX}/', methods=['GET', 'POST'])
@app.route(f'{PROXY_PREFIX}/<path:subpath>', methods=['GET', 'POST'])
def proxy(subpath=''):
    path = subpath or ''
    url = f"{BASE_URL}/{path.lstrip('/')}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"
    return proxy_request(url)

@app.route('/<path:catchall>', methods=['GET', 'POST'])
def fallback(catchall):
    if catchall.endswith(('.html', '.js', '.css', '.json')) or '/' in catchall:
        return proxy_request(f"{BASE_URL}/{catchall}")
    return Response("Not Found", status=404)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)