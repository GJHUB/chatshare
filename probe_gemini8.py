"""探测 Gemini 节点的 token 获取方式 - 检查是否有 /api/auth/refresh 或类似端点"""
import asyncio
import re
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
    chat_url = enter['chat_url']
    cookies = enter['cookies']
    
    base_url = chat_url.rstrip('/').rsplit('/app', 1)[0]
    gfsessionid = cookies.get('gfsessionid', '')
    token = cookies.get('token', '')
    
    client = httpx.AsyncClient(timeout=10, verify=False, follow_redirects=False)
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    
    # 1. 检查 /v1/auth 相关路径
    print("=== /v1/ auth 路径 ===")
    v1_paths = [
        '/v1/auth/token',
        '/v1/auth/refresh',
        '/v1/auth/login',
        '/v1/auth/session',
        '/v1/token',
        '/v1/refresh',
        '/v1/session',
    ]
    for path in v1_paths:
        for method in ['GET', 'POST']:
            try:
                url = f"{base_url}{path}"
                headers = {'Cookie': cookie_str, 'Content-Type': 'application/json'}
                if method == 'GET':
                    resp = await client.get(url, headers=headers)
                else:
                    resp = await client.post(url, json={"token": token, "gfsessionid": gfsessionid}, headers=headers)
                ct = resp.headers.get('content-type', '')
                if resp.status_code != 404 or 'json' in ct:
                    is_html = 'html' in ct
                    preview = resp.text[:200] if not is_html else f'[HTML len={len(resp.text)}]'
                    print(f"  {method} {path} -> {resp.status_code} ({ct}): {preview}")
            except Exception as e:
                print(f"  {method} {path} -> ERROR: {e}")
    
    # 2. 检查 Gemini 原生 Google API 路径
    print("\n=== Google Gemini API 路径 ===")
    google_paths = [
        '/api/auth',
        '/api/auth/session',
        '/api/auth/token',
        '/api/auth/refresh',
        '/api/auth/signin',
        '/api/auth/callback',
        '/api/auth/csrf',
        '/api/auth/providers',
        '/_/BardChatUi/data/batchexecute',
        '/u/0/_/BardChatUi/data/batchexecute',
    ]
    for path in google_paths:
        try:
            url = f"{base_url}{path}"
            headers = {'Cookie': cookie_str, 'Content-Type': 'application/json'}
            resp = await client.get(url, headers=headers)
            ct = resp.headers.get('content-type', '')
            if resp.status_code != 404 or 'json' in ct:
                is_html = 'html' in ct
                preview = resp.text[:200] if not is_html else f'[HTML len={len(resp.text)}]'
                print(f"  GET {path} -> {resp.status_code} ({ct}): {preview}")
        except Exception as e:
            print(f"  GET {path} -> ERROR: {e}")
    
    # 3. 检查 sorux 特有路径
    print("\n=== Sorux 特有路径 ===")
    sorux_paths = [
        '/sorux/auth',
        '/sorux/token',
        '/sorux/refresh',
        '/sorux/session',
        '/sgw/auth',
        '/sgw/token',
        '/sgw/refresh',
        '/clear-account',
        '/api/sorux/auth',
        '/api/sorux/token',
    ]
    for path in sorux_paths:
        try:
            url = f"{base_url}{path}"
            headers = {'Cookie': cookie_str, 'Content-Type': 'application/json'}
            resp = await client.get(url, headers=headers)
            ct = resp.headers.get('content-type', '')
            if resp.status_code != 404 or 'json' in ct:
                is_html = 'html' in ct
                preview = resp.text[:200] if not is_html else f'[HTML len={len(resp.text)}]'
                print(f"  GET {path} -> {resp.status_code} ({ct}): {preview}")
                if resp.headers.get_list('set-cookie'):
                    print(f"    Set-Cookie: {resp.headers.get_list('set-cookie')}")
        except Exception as e:
            print(f"  GET {path} -> ERROR: {e}")
    
    # 4. 用浏览器方式访问 /app，看 redirect 链中是否有 set-cookie
    print("\n=== 跟踪 redirect 链 ===")
    client2 = httpx.AsyncClient(timeout=10, verify=False, follow_redirects=False)
    url = f"{base_url}/"
    headers = {'Cookie': cookie_str}
    for i in range(5):
        try:
            resp = await client2.get(url, headers=headers)
            print(f"  [{i}] {url} -> {resp.status_code}")
            if resp.headers.get_list('set-cookie'):
                print(f"    Set-Cookie: {resp.headers.get_list('set-cookie')}")
            if resp.status_code in (301, 302, 303, 307, 308):
                url = resp.headers.get('location', '')
                if not url.startswith('http'):
                    url = f"{base_url}{url}"
                print(f"    -> Redirect to: {url}")
            else:
                break
        except Exception as e:
            print(f"  [{i}] ERROR: {e}")
            break
    
    # 5. 看看 Gemini 的 WIZ_global_data 里有没有 token
    print("\n=== WIZ_global_data 中的 token ===")
    resp = await client.get(chat_url, headers={'Cookie': cookie_str}, follow_redirects=True)
    html = resp.text
    # 搜索 SNlM0e (Gemini 的 at token)
    at_match = re.search(r'"SNlM0e":"([^"]+)"', html)
    if at_match:
        print(f"  SNlM0e (at token): {at_match.group(1)[:50]}...")
    
    # 搜索其他 token 相关
    for pattern in [r'"FdrFJe":"([^"]+)"', r'"cfb2h":"([^"]+)"', r'"WpFsob":"([^"]+)"']:
        m = re.search(pattern, html)
        if m:
            print(f"  {pattern}: {m.group(1)[:80]}...")
    
    await client.aclose()
    await client2.aclose()
    await auth.close()

asyncio.run(main())
