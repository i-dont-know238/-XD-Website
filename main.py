from flask import Flask, request, Response, redirect
import requests
import os
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
BASE_URL = "https://beaufortsc.powerschool.com"
session = requests.Session()

def full_url(path):
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(BASE_URL + "/", path)

def transform_content(content, content_type):
    if "text/html" in content_type:
        text = content.decode("utf-8", errors="replace")
        text = text.replace(BASE_URL, request.host_url.rstrip("/"))
        text = text.replace('href="/', f'href="{request.host_url}')
        text = text.replace("src=\"/", f'src="{request.host_url}')
        text = text.replace("action=\"/", f'action="{request.host_url}')
        return text.encode("utf-8")
    elif "javascript" in content_type or "css" in content_type:
        text = content.decode("utf-8", errors="replace")
        text = text.replace(BASE_URL, request.host_url.rstrip("/"))
        return text.encode("utf-8")
    return content

def forward_request(url):
    headers = {k: v for k, v in request.headers if k.lower() not in ("host", "content-length")}
    headers["Host"] = "beaufortsc.powerschool.com"
    headers["Referer"] = BASE_URL
    cookies = request.cookies

    method = request.method
    data = request.form if method == "POST" else None
    try:
        resp = session.request(method, url, headers=headers, cookies=cookies, data=data, allow_redirects=False, timeout=30)
    except Exception as e:
        return Response(f"Error contacting {BASE_URL}: {e}", status=500)

    if 300 <= resp.status_code < 400 and "Location" in resp.headers:
        new_loc = resp.headers["Location"]
        if not urlparse(new_loc).netloc:
            new_loc = urljoin(BASE_URL, new_loc)
        new_loc = new_loc.replace(BASE_URL, request.host_url.rstrip("/"))
        r = redirect(new_loc, code=resp.status_code)
        for c in resp.cookies:
            r.set_cookie(c.name, c.value, path="/")
        return r

    content_type = resp.headers.get("content-type", "text/html")
    body = transform_content(resp.content, content_type)
    r = Response(body, status=resp.status_code, content_type=content_type)
    for c in resp.cookies:
        r.set_cookie(c.name, c.value, path="/")
    return r

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch_all(path):
    url = full_url(path)
    if request.query_string:
        url += f"?{request.query_string.decode()}"
    return forward_request(url)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Flask reverse proxy running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
