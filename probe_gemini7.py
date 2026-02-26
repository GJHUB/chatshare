"""搜索 gemini-voyager.js 中的 refresh token 和 auth 相关代码"""
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
    
    client = httpx.AsyncClient(timeout=15, verify=False, follow_redirects=True)
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    headers = {'Cookie': cookie_str}
    
    # 获取完整 HTML
    resp = await client.get(chat_url, headers=headers)
    html = resp.text
    
    # 搜索 soruxgpt_gemini_rt 在 HTML 中
    for kw in ['soruxgpt_gemini_rt', 'soruxgpt', '_rt', 'refresh_token', 'refreshToken']:
        positions = [m.start() for m in re.finditer(re.escape(kw), html)]
        if positions:
            print(f"'{kw}' found {len(positions)} times in HTML")
            for pos in positions[:3]:
                print(f"  ...{html[max(0,pos-100):pos+100]}...")
    
    # 下载 gemini-voyager.js 并搜索
    resp = await client.get(f"{base_url}/injectjs/gemini-voyager/gemini-voyager.js", headers=headers)
    js = resp.text
    
    for kw in ['soruxgpt_gemini_rt', 'gemini_rt', 'refresh_token', 'refreshToken', '/v1/', 'Bearer', 'authorization', 'Authorization']:
        positions = [m.start() for m in re.finditer(re.escape(kw), js)]
        if positions:
            print(f"\n'{kw}' found {len(positions)} times in gemini-voyager.js")
            for pos in positions[:5]:
                print(f"  ...{js[max(0,pos-120):pos+120]}...")
    
    # 也搜索 sgw-assets/watermark-remover-v2.js
    resp = await client.get(f"{base_url}/sgw-assets/watermark-remover-v2.js?v=9", headers=headers)
    js2 = resp.text
    for kw in ['soruxgpt', 'gemini_rt', 'refresh', 'token', 'auth', '/v1/']:
        if kw.lower() in js2.lower():
            positions = [m.start() for m in re.finditer(re.escape(kw), js2, re.IGNORECASE)]
            print(f"\n'{kw}' found {len(positions)} times in watermark-remover-v2.js")
            for pos in positions[:3]:
                print(f"  ...{js2[max(0,pos-100):pos+100]}...")
    
    # 试试直接用 gfsessionid 作为 cookie 名 soruxgpt_gemini_rt
    print("\n\n=== 试用 gfsessionid 作为 soruxgpt_gemini_rt ===")
    gfsessionid = cookies.get('gfsessionid', '')
    token = cookies.get('token', '')
    
    test_headers = {
        'Cookie': f'soruxgpt_gemini_rt={gfsessionid}; {cookie_str}',
        'Authorization': f'Bearer {gfsessionid}',
        'Content-Type': 'application/json',
    }
    body = {"model": "auto", "messages": [{"role": "user", "content": "say ok"}], "stream": False}
    resp = await client.post(f"{base_url}/v1/chat/completions", json=body, headers=test_headers, timeout=10)
    print(f"gfsessionid as Bearer: {resp.status_code}: {resp.text[:200]}")
    
    # 试 cookie 方式
    test_headers2 = {
        'Cookie': f'soruxgpt_gemini_rt={token}; {cookie_str}',
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    resp = await client.post(f"{base_url}/v1/chat/completions", json=body, headers=test_headers2, timeout=10)
    print(f"token as Bearer: {resp.status_code}: {resp.text[:200]}")
    
    # 试 cookie 里直接带 soruxgpt_gemini_rt
    for val in [gfsessionid, token, f"{gfsessionid}:{token}"]:
        test_headers3 = {
            'Cookie': f'soruxgpt_gemini_rt={val}',
            'Content-Type': 'application/json',
        }
        resp = await client.post(f"{base_url}/v1/chat/completions", json=body, headers=test_headers3, timeout=10)
        print(f"soruxgpt_gemini_rt cookie={val[:30]}...: {resp.status_code}: {resp.text[:200]}")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
