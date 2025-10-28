from flask import Flask, request, Response
import requests
import re
import os

app = Flask(__name__)

BASE_URL = "https://beaufortsc.powerschool.com"

def replace_urls(html):
    html = re.sub(r'(href|src|action)="(/[^"]*)"', r'\1="/proxy\2"', html)
    html = re.sub(r"(href|src|action)='(/[^']*)'", r"\1='/proxy\2'", html)
    return html

def proxy_request(url):
    headers = {k: v for k, v in request.headers if k.lower() not in ('host', 'content-length', 'cookie')}
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = BASE_URL
    cookies = request.cookies

    try:
        if request.method == 'POST':
            resp = requests.post(url, data=request.form, headers=headers, cookies=cookies, allow_redirects=True, timeout=20)
        else:
            resp = requests.get(url, headers=headers, cookies=cookies, allow_redirects=True, timeout=20)
    except Exception as e:
        return Response(f"Upstream request error: {e}", status=500)

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

@app.route('/', methods=['GET'])
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
    if path.endswith('.html') or '/' in path:
        return proxy_request(f"{BASE_URL}/{path}")
    return Response("Not Found", status=404)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Starting Flask on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
