import os
import requests
from flask import Flask, request, Response, redirect
import json

app = Flask(__name__)
session = requests.Session()

@app.route('/gateway', methods=['GET', 'OPTIONS'])
@app.route('/gateway/', methods=['GET', 'OPTIONS'])
@app.route('/api/gateway', methods=['GET', 'OPTIONS'])
@app.route('/api/gateway/', methods=['GET', 'OPTIONS'])
def gateway():
    if request.method == 'OPTIONS':
        return Response('', status=200, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': '*',
            'Access-Control-Allow-Methods': '*'
        })
    
    qs = request.query_string.decode('utf-8')
    url = f'wss://gateway.discord.gg/?{qs}' if qs else 'wss://gateway.discord.gg/?v=9&encoding=json'
    
    return Response(json.dumps({'url': url}), status=200, headers={
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
    })

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def proxy(path=''):
    if path in ['gateway', 'gateway/'] or path.startswith('api/gateway'):
        return Response('Route conflict', status=500)
    
    if not path:
        return redirect('/login')
    
    if path.startswith('api/'):
        target = f'https://discord.com/api/{path[4:]}'
    elif path.startswith('cdn/'):
        target = f'https://cdn.discordapp.com/{path[4:]}'
    else:
        target = f'https://discord.com/{path}'
    
    if request.query_string:
        target += '?' + request.query_string.decode('utf-8')
    
    headers = {}
    for key, value in request.headers:
        if key.lower() not in ['host', 'content-length', 'connection']:
            headers[key] = value
    
    headers['Host'] = target.split('/')[2]
    headers['Origin'] = 'https://discord.com'
    headers['Referer'] = 'https://discord.com'
    
    try:
        resp = session.request(
            method=request.method,
            url=target,
            headers=headers,
            data=request.get_data(),
            allow_redirects=False,
            verify=True,
            timeout=30
        )
        
        content = resp.content
        content_type = resp.headers.get('Content-Type', '')
        
        if content and ('text/html' in content_type or 'javascript' in content_type):
            try:
                text = content.decode('utf-8')
                text = text.replace('https://discord.com', f'http://{request.host}')
                text = text.replace('https://cdn.discordapp.com', f'http://{request.host}/cdn')
                text = text.replace('"/api/', f'"http://{request.host}/api/')
                content = text.encode('utf-8')
            except:
                pass
        
        response_headers = {}
        for key, value in resp.headers.items():
            if key.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection']:
                response_headers[key] = value
        
        response_headers['Access-Control-Allow-Origin'] = '*'
        
        return Response(content, status=resp.status_code, headers=response_headers)
        
    except Exception as e:
        return Response(f"Error: {str(e)}", status=502)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8000)))
