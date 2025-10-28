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
    html_content = html_content.replace(BASE_URL, f"/proxy")
    return html_content

def copy_cookies_to_response(resp, r):
    for cookie in r.cookies:
        resp.set_cookie(
            cookie.name,
            cookie.value,
            expires=cookie.expires,
            path='/',
            secure=False,
            samesite='Lax'
        )

def sync_browser_cookies():
    session.cookies.clear()
    for k, v in request.cookies.items():
        session.cookies.set(k, v)

def make_upstream_request(method, url, **kwargs):
    sync_browser_cookies()
    response = session.request(method, url, allow_redirects=False, **kwargs)

    # follow upstream redirects and rewrite location
    while response.is_redirect or response.is_permanent_redirect:
        location = response.headers.get('Location', '')
        if location.startswith(BASE_URL):
            next_path = location[len(BASE_URL):]
        else:
            next_path = location
        if next_path.startswith('/'):
            url = f"{BASE_URL}{next_path}"
        else:
            break
        response = session.request('GET', url, allow_redirects=False)
    return response

@app.route('/proxy/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    url = f"{BASE_URL}/{path}"
    if request.query_string:
        url += f"?{request.query_string.decode('utf-8', errors='ignore')}"

    headers = {k: v for k, v in request.headers.items()}
    headers['Host'] = 'beaufortsc.powerschool.com'
    headers['Referer'] = f"{BASE_URL}/{path}"
    headers.pop('Content-Length', None)
    headers.pop('Cookie', None)

    if request.method == 'POST':
        response = make_upstream_request('POST', url, data=request.form or request.get_data(), files=request.files or None, headers=headers)
    else:
        response = make_upstream_request('GET', url, headers=headers)

    content = response.content
    content_type = response.headers.get('content-type', '').lower()

    if 'text/html' in content_type:
        html_content = replace_urls(content.decode('utf-8', errors='replace'))
        content = html_content.encode('utf-8')
    elif 'javascript' in content_type:
        js_content = content.decode('utf-8', errors='replace').replace(BASE_URL, f"/proxy")
        content = js_content.encode('utf-8')

    resp = Response(content, content_type=response.headers.get('content-type', 'text/plain'))
    copy_cookies_to_response(resp, response)

    # rewrite location headers if needed
    if 'location' in response.headers:
        loc = response.headers['location']
        if loc.startswith(BASE_URL):
            loc = loc[len(BASE_URL):]
        if loc.startswith('/'):
            resp.headers['location'] = f'/proxy{loc}'

    return resp

@app.route('/', methods=['GET'])
def home():
    response = make_upstream_request('GET', f"{BASE_URL}/public/home.html")
    html_content = replace_urls(response.text)
    resp = Response(html_content, content_type='text/html')
    copy_cookies_to_response(resp, response)
    return resp

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
