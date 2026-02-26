"""探测 Gemini 节点的 cookie 和 refresh token"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.auth import ChatShareAuth
import httpx

async def main():
    auth = ChatShareAuth()
    await auth.login()
    
    cars = await auth.get_car_page('gemini')
    best_car = cars[0]
    enter = await auth.enter_car('gemini', best_car['carid'])
    chat_url = enter['chat_url']  # https://gemini-node2.chatshare.biz/app
    cookies = enter['cookies']
    
    base_url = chat_url.rstrip('/').rsplit('/app', 1)[0]
    
    print(f"chat_url: {chat_url}")
    print(f"enter cookies: {cookies}")
    
    # 用 httpx 的 cookie jar 来跟踪所有 set-cookie
    client = httpx.AsyncClient(timeout=15, verify=False, follow_redirects=True)
    
    # 先设置进车拿到的 cookies
    for k, v in cookies.items():
        client.cookies.set(k, v, domain="gemini-node2.chatshare.biz")
    
    # 访问 /app 看看会不会 set 新 cookie
    print("\n=== GET /app ===")
    resp = await client.get(chat_url)
    print(f"Status: {resp.status_code}")
    print(f"Set-Cookie headers: {resp.headers.get_list('set-cookie')}")
    print(f"All cookies after /app: {dict(client.cookies)}")
    
    # 看看 HTML 里有没有 token 相关的内容
    html = resp.text
    # 搜索 soruxgpt 相关
    for keyword in ['soruxgpt', 'gemini_rt', 'refresh_token', 'rt_token', 'Bearer', 'authorization']:
        idx = html.lower().find(keyword.lower())
        if idx >= 0:
            snippet = html[max(0, idx-50):idx+100]
            print(f"\nFound '{keyword}' in HTML at pos {idx}: ...{snippet}...")
    
    # 访问根路径看 redirect
    print("\n=== GET / (follow redirects) ===")
    resp = await client.get(f"{base_url}/")
    print(f"Status: {resp.status_code}")
    print(f"Final URL: {resp.url}")
    print(f"Set-Cookie: {resp.headers.get_list('set-cookie')}")
    print(f"All cookies: {dict(client.cookies)}")
    
    # 试试 /api/auth 或 /auth 路径
    print("\n=== Auth 路径探测 ===")
    auth_paths = [
        '/api/auth/session',
        '/api/auth/token',
        '/api/auth/refresh',
        '/auth/session',
        '/auth/token',
        '/api/session',
        '/api/token',
        '/api/refresh',
        '/api/user',
        '/api/me',
        '/api/auth',
        '/app/api/auth',
        '/app/api/session',
    ]
    
    for path in auth_paths:
        try:
            url = f"{base_url}{path}"
            resp = await client.get(url)
            ct = resp.headers.get('content-type', '')
            is_html = 'html' in ct
            if resp.status_code != 404 or not is_html:
                preview = resp.text[:200] if not is_html else f'[HTML, len={len(resp.text)}]'
                print(f"  GET {path} -> {resp.status_code} ({ct}): {preview}")
                if resp.headers.get_list('set-cookie'):
                    print(f"    Set-Cookie: {resp.headers.get_list('set-cookie')}")
        except Exception as e:
            print(f"  GET {path} -> ERROR: {e}")
    
    # 试 POST /api/auth/login 等
    print("\n=== POST Auth 路径 ===")
    post_auth_paths = [
        ('/api/auth/login', {"token": cookies.get('token', '')}),
        ('/api/auth/login', {"gfsessionid": cookies.get('gfsessionid', '')}),
        ('/api/auth/session', {"token": cookies.get('token', '')}),
        ('/api/login', {"token": cookies.get('token', '')}),
        ('/auth/login', {"token": cookies.get('token', '')}),
    ]
    
    for path, body in post_auth_paths:
        try:
            url = f"{base_url}{path}"
            resp = await client.post(url, json=body)
            ct = resp.headers.get('content-type', '')
            is_html = 'html' in ct
            if resp.status_code != 404 or not is_html:
                preview = resp.text[:200] if not is_html else f'[HTML, status={resp.status_code}]'
                print(f"  POST {path} -> {resp.status_code}: {preview}")
                if resp.headers.get_list('set-cookie'):
                    print(f"    Set-Cookie: {resp.headers.get_list('set-cookie')}")
        except Exception as e:
            print(f"  POST {path} -> ERROR: {e}")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
