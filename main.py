from flask import Flask, request, Response
import requests
import re

app = Flask(__name__)

BASE_URL = "https://beaufortsc.powerschool.com"

def replace_urls(html):
    html = re.sub(r'(href|src|action)="(/[^"]*)"', r'\1="/proxy\2"', html)
    html = re.sub(r"(href|src|action)='(/[^']*)'", r"\1='/proxy\2'", html)
    return html

def proxy_request(url):
    headers = {k: v for k, v in request.headers if k.lower() != 'host'}
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = BASE_URL
    headers.pop('Content-Length', None)
    cookies = request.cookies

    if request.method == 'POST':
        resp = requests.post(url, data=request.form, headers=headers, cookies=cookies, allow_redirects=True)
    else:
        resp = requests.get(url, headers=headers, cookies=cookies, allow_redirects=True)

    content_type = resp.headers.get('content-type', '').lower()
    content = resp.content

    if 'text/html' in content_type:
        html = content.decode('utf-8', errors='replace')
        html = replace_urls(html)
        content = html.encode('utf-8')
    elif 'javascript' in content_type:
        js = content.decode('utf-8', errors='replace')
        js = js.replace(BASE_URL, f"{request.host_url}proxy")
        content = js.encode('utf-8')

    response = Response(content, content_type=resp.headers.get('content-type', 'text/html'))
    for cookie_name, cookie_value in resp.cookies.items():
        response.set_cookie(cookie_name, cookie_value, path='/')
    return response

@app.route('/')
def index():
    url = f"{BASE_URL}/public/home.html"
    return proxy_request(url)

@app.route('/proxy/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"
    return proxy_request(url)

@app.route('/<path:path>', methods=['GET', 'POST'])
def passthrough(path):
    if path.endswith('.html'):
        return proxy_request(f"{BASE_URL}/{path}")
    return Response("Not Found", status=404)

# no app.run() for vercel
