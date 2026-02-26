"""找 soruxgpt_gemini_rt - 检查 HTML、JS、cookie set 等"""
import asyncio, re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from src.auth import ChatShareAuth
import httpx

async def main():
    auth = ChatShareAuth()
    await auth.login()
    cars = await auth.get_car_page('gemini')
    enter = await auth.enter_car('gemini', cars[0]['carid'])
    chat_url = enter['chat_url'].rstrip('/')
    cookies = enter['cookies']
    base_url = chat_url.rsplit('/app', 1)[0]
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    
    client = httpx.AsyncClient(timeout=15, verify=False, follow_redirects=True)
    headers = {'Cookie': cookie_str}
    
    # 1. 获取 /app 页面 HTML，搜索 soruxgpt_gemini_rt
    print("=== 1. 搜索 /app HTML ===")
    resp = await client.get(chat_url, headers=headers)
    html = resp.text
    print(f"  HTML length: {len(html)}")
    
    # 检查 set-cookie
    for h in resp.headers.multi_items():
        if h[0].lower() == 'set-cookie':
            print(f"  Set-Cookie: {h[1][:200]}")
    
    # 搜索关键词
    for kw in ['soruxgpt_gemini_rt', 'gemini_rt', 'refresh_token', 'refreshToken', 'rt_token']:
        positions = [m.start() for m in re.finditer(kw, html, re.IGNORECASE)]
        if positions:
            print(f"  '{kw}' found {len(positions)} times")
            for pos in positions[:5]:
                snippet = html[max(0,pos-80):pos+120]
                print(f"    ...{snippet}...")
    
    # 2. 获取所有 JS 文件链接
    print("\n=== 2. JS 文件中搜索 ===")
    js_urls = re.findall(r'src="([^"]*\.js[^"]*)"', html)
    js_urls += re.findall(r"src='([^']*\.js[^']*)'", html)
    print(f"  Found {len(js_urls)} JS files")
    
    for js_url in js_urls:
        if not js_url.startswith('http'):
            js_url = f"{base_url}{js_url}" if js_url.startswith('/') else f"{base_url}/{js_url}"
        try:
            resp = await client.get(js_url, headers=headers)
            js = resp.text
            for kw in ['soruxgpt_gemini_rt', 'gemini_rt', '/v1/chat/completions']:
                if kw.lower() in js.lower():
                    positions = [m.start() for m in re.finditer(re.escape(kw), js, re.IGNORECASE)]
                    print(f"\n  {js_url}")
                    print(f"    '{kw}' found {len(positions)} times")
                    for pos in positions[:3]:
                        snippet = js[max(0,pos-150):pos+150]
                        print(f"    ...{snippet}...")
        except:
            pass
    
    # 3. 试 /app/api/auth/session 或类似端点获取 rt
    print("\n=== 3. 试获取 rt token 的端点 ===")
    endpoints = [
        '/api/auth/session',
        '/api/auth/token', 
        '/api/session',
        '/api/token',
        '/auth/session',
        '/auth/token',
        '/api/auth/refresh',
        '/api/refresh',
        '/app/api/auth/session',
        '/app/api/session',
    ]
    for ep in endpoints:
        url = f"{base_url}{ep}"
        try:
            resp = await client.get(url, headers=headers)
            ct = resp.headers.get('content-type', '')
            if resp.status_code != 404:
                is_html = 'html' in ct
                preview = f'[HTML len={len(resp.text)}]' if is_html else resp.text[:300]
                print(f"  GET {ep} -> {resp.status_code} ({ct})")
                print(f"    {preview}")
                for h in resp.headers.multi_items():
                    if h[0].lower() == 'set-cookie':
                        print(f"    Set-Cookie: {h[1][:200]}")
        except Exception as e:
            print(f"  GET {ep} -> ERROR: {e}")
    
    # 4. 试 POST /api/auth/session
    print("\n=== 4. POST 方式 ===")
    for ep in ['/api/auth/session', '/api/auth/token', '/api/auth/refresh']:
        url = f"{base_url}{ep}"
        try:
            resp = await client.post(url, json={"gfsessionid": cookies.get('gfsessionid','')}, headers={**headers, 'Content-Type': 'application/json'})
            ct = resp.headers.get('content-type', '')
            if resp.status_code != 404:
                is_html = 'html' in ct
                preview = f'[HTML len={len(resp.text)}]' if is_html else resp.text[:300]
                print(f"  POST {ep} -> {resp.status_code}: {preview}")
        except Exception as e:
            print(f"  POST {ep} -> ERROR: {e}")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
