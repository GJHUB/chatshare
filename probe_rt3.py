"""尝试通过浏览器方式获取 soruxgpt_gemini_rt
思路：SoruxGPT 的 /v1/chat/completions 需要 soruxgpt_gemini_rt 作为 Bearer token
这个 token 可能是通过某个 API 调用获取的，或者在 cookie 中以其他名字存在
让我们更仔细地检查进车后的所有响应"""
import asyncio, sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from src.auth import ChatShareAuth
import httpx

async def main():
    auth = ChatShareAuth()
    await auth.login()
    
    # 重新进车，这次仔细看所有 response headers
    cars = await auth.get_car_page('gemini')
    best = cars[0]
    
    # 手动调用 enter_car API 看完整响应
    await auth.ensure_token()
    import time, hashlib
    car_id = best['carid']
    timestamp = str(int(time.time()))
    raw = f"{car_id}{timestamp}"
    sign = hashlib.md5(raw.encode()).hexdigest()
    payload = {
        "channel": "gemini",
        "car_id": car_id,
        "timestamp": timestamp,
        "sign": sign,
    }
    
    resp = await auth._client.post(
        f"{auth.base_url}/share-login/v1/user/home/enter",
        json=payload,
        headers=auth.get_headers()
    )
    
    print("=== enter_car 完整响应 ===")
    print(f"Status: {resp.status_code}")
    print(f"Headers:")
    for k, v in resp.headers.multi_items():
        print(f"  {k}: {v[:200]}")
    print(f"\nBody: {resp.text[:500]}")
    print(f"\nCookies from response:")
    for k, v in resp.cookies.items():
        print(f"  {k}: {v[:100]}")
    
    # 现在用拿到的 cookies 访问 gemini 节点
    chat_url = resp.json().get('respData', resp.json().get('data', ''))
    if isinstance(chat_url, dict):
        chat_url = chat_url.get('url', '')
    chat_url = chat_url.rstrip('/')
    base_url = chat_url.rsplit('/app', 1)[0] if '/app' in chat_url else chat_url
    
    all_cookies = dict(resp.cookies)
    all_cookies['token'] = auth.token
    cookie_str = '; '.join(f'{k}={v}' for k, v in all_cookies.items())
    
    print(f"\nchat_url: {chat_url}")
    print(f"base_url: {base_url}")
    
    # 访问 base_url 根路径，看是否有 set-cookie
    client = httpx.AsyncClient(timeout=15, verify=False, follow_redirects=False)
    
    print("\n=== 访问节点根路径 ===")
    for path in ['/', '/app', '/app/']:
        url = f"{base_url}{path}"
        try:
            resp2 = await client.get(url, headers={'Cookie': cookie_str})
            print(f"\nGET {path} -> {resp2.status_code}")
            for h in resp2.headers.multi_items():
                if h[0].lower() == 'set-cookie':
                    print(f"  Set-Cookie: {h[1][:300]}")
            if resp2.status_code in (301, 302, 303, 307, 308):
                print(f"  Location: {resp2.headers.get('location', '')}")
        except Exception as e:
            print(f"GET {path} -> ERROR: {e}")
    
    # 跟踪完整 redirect 链
    print("\n=== 完整 redirect 链 ===")
    url = f"{base_url}/app"
    collected_cookies = dict(all_cookies)
    for i in range(10):
        try:
            cs = '; '.join(f'{k}={v}' for k, v in collected_cookies.items())
            resp2 = await client.get(url, headers={'Cookie': cs})
            print(f"\n[{i}] GET {url} -> {resp2.status_code}")
            for h in resp2.headers.multi_items():
                if h[0].lower() == 'set-cookie':
                    print(f"  Set-Cookie: {h[1][:300]}")
                    # 解析 cookie
                    parts = h[1].split(';')[0]
                    if '=' in parts:
                        ck, cv = parts.split('=', 1)
                        collected_cookies[ck.strip()] = cv.strip()
            if resp2.status_code in (301, 302, 303, 307, 308):
                loc = resp2.headers.get('location', '')
                if not loc.startswith('http'):
                    loc = f"{base_url}{loc}"
                url = loc
            else:
                break
        except Exception as e:
            print(f"[{i}] ERROR: {e}")
            break
    
    print(f"\n\n=== 收集到的所有 cookies ===")
    for k, v in collected_cookies.items():
        sv = str(v)
        print(f"  {k}: {sv[:100]}{'...' if len(sv)>100 else ''}")
    
    # 用收集到的所有 cookies 再试一次
    print("\n=== 用所有收集到的 cookies 试 /v1/chat/completions ===")
    for name, token in collected_cookies.items():
        if len(str(token)) < 10:
            continue
        headers = {
            'Cookie': '; '.join(f'{k}={v}' for k, v in collected_cookies.items()),
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        body = {
            'model': 'gemini-2.0-flash',
            'messages': [{'role': 'user', 'content': 'say ok'}],
            'stream': False,
        }
        try:
            resp3 = await client.post(f'{base_url}/v1/chat/completions', json=body, headers=headers)
            preview = resp3.text[:200]
            print(f"  Bearer={name} -> {resp3.status_code}: {preview}")
            if resp3.status_code == 200:
                print(f"  *** SUCCESS! Token name: {name} ***")
                break
        except Exception as e:
            print(f"  Bearer={name} -> ERROR: {e}")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
