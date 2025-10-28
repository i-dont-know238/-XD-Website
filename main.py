from flask import Flask, request, Response, redirect
import requests
import re
import os
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
BASE_URL = "https://beaufortsc.powerschool.com"
session = requests.Session()

def clean_html(content):
    content = re.sub(r'(href|src|action)="(/[^"]*)"', lambda m: f'{m.group(1)}="{urljoin("/", m.group(2))}"', content)
    content = re.sub(r"(href|src|action)='(/[^']*)'", lambda m: f'{m.group(1)}=\'{urljoin("/", m.group(2))}\'', content)
    return content

def make_request(url):
    headers = {k: v for k, v in request.headers if k.lower() not in ('host', 'content-length')}
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = BASE_URL
    cookies = request.cookies
    method = request.method

    try:
        if method == 'POST':
            resp = session.post(url, data=request.form, headers=headers, cookies=cookies, allow_redirects=False, timeout=30)
        else:
            resp = session.get(url, headers=headers, cookies=cookies, allow_redirects=False, timeout=30)
    except Exception as e:
        return Response(f"Error contacting {BASE_URL}: {e}", status=500)

    if 300 <= resp.status_code < 400 and 'Location' in resp.headers:
        new_url = resp.headers['Location']
        if not urlparse(new_url).netloc:
            new_url = urljoin(BASE_URL, new_url)
        response = redirect(new_url.replace(BASE_URL, request.host_url.rstrip('/')))
        for c in resp.cookies:
            response.set_cookie(c.name, c.value, path='/')
        return response

    content_type = resp.headers.get('content-type', '').lower()
    body = resp.content

    if 'text/html' in content_type:
        html = body.decode('utf-8', errors='replace')
        html = html.replace(BASE_URL, request.host_url.rstrip('/'))
        html = clean_html(html)
        body = html.encode('utf-8')
    elif 'javascript' in content_type:
        js = body.decode('utf-8', errors='replace')
        js = js.replace(BASE_URL, request.host_url.rstrip('/'))
        body = js.encode('utf-8')

    response = Response(body, content_type=resp.headers.get('content-type', 'text/html'))
    for c in resp.cookies:
        response.set_cookie(c.name, c.value, path='/')
    return response

@app.route('/', methods=['GET', 'POST'])
def root():
    return make_request(f"{BASE_URL}/public/home.html")

@app.route('/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    url = urljoin(BASE_URL + '/', path)
    if request.query_string:
        url += f"?{request.query_string.decode()}"
    return make_request(url)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Proxy running on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
