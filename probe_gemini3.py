"""测试 Gemini /v1/chat/completions 带 Authorization"""
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
    chat_url = enter['chat_url']
    cookies = enter['cookies']
    
    base_url = chat_url.rstrip('/').rsplit('/app', 1)[0]
    token = cookies.get('token', auth.token)
    gfsessionid = cookies.get('gfsessionid', '')
    
    print(f"base_url: {base_url}")
    print(f"token: {token[:30]}...")
    print(f"gfsessionid: {gfsessionid}")
    
    client = httpx.AsyncClient(timeout=30, verify=False)
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    
    # 试不同的 Authorization 方式
    auth_variants = [
        ("Bearer token", {"Authorization": f"Bearer {token}", "Cookie": cookie_str, "Content-Type": "application/json"}),
        ("Bearer gfsessionid", {"Authorization": f"Bearer {gfsessionid}", "Cookie": cookie_str, "Content-Type": "application/json"}),
        ("token直接", {"Authorization": token, "Cookie": cookie_str, "Content-Type": "application/json"}),
        ("gfsessionid直接", {"Authorization": gfsessionid, "Cookie": cookie_str, "Content-Type": "application/json"}),
        ("x-api-key token", {"x-api-key": token, "Cookie": cookie_str, "Content-Type": "application/json"}),
        ("x-api-key gfsessionid", {"x-api-key": gfsessionid, "Cookie": cookie_str, "Content-Type": "application/json"}),
    ]
    
    body = {
        "model": "auto",
        "messages": [{"role": "user", "content": "say ok"}],
        "stream": False,
    }
    
    for name, headers in auth_variants:
        try:
            resp = await client.post(f"{base_url}/v1/chat/completions", json=body, headers=headers, timeout=10)
            preview = resp.text[:200]
            print(f"\n[{name}] -> {resp.status_code}: {preview}")
        except Exception as e:
            print(f"\n[{name}] -> ERROR: {e}")
    
    # 也试试 stream 版本用 Bearer token
    print("\n\n=== Stream with Bearer token ===")
    headers = {
        "Authorization": f"Bearer {token}",
        "Cookie": cookie_str,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body_stream = {
        "model": "auto",
        "messages": [{"role": "user", "content": "say hello"}],
        "stream": True,
    }
    try:
        async with client.stream("POST", f"{base_url}/v1/chat/completions", json=body_stream, headers=headers, timeout=30) as resp:
            print(f"Status: {resp.status_code}")
            print(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")
            count = 0
            async for line in resp.aiter_lines():
                line = line.strip()
                if line:
                    print(f"  [{count}] {line[:200]}")
                    count += 1
                    if count > 20:
                        break
    except Exception as e:
        print(f"Error: {e}")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
