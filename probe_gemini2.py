"""测试 Gemini /v1/chat/completions 接口"""
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
    print(f"base_url: {base_url}")
    
    client = httpx.AsyncClient(timeout=30, verify=False)
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    headers = {
        'Cookie': cookie_str,
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
    }
    
    # 先试 /v1/models 看有哪些模型
    print("\n=== GET /v1/models ===")
    try:
        resp = await client.get(f"{base_url}/v1/models", headers=headers)
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.text[:500]}")
    except Exception as e:
        print(f"Error: {e}")
    
    # 试 POST /v1/chat/completions (stream)
    print("\n=== POST /v1/chat/completions (stream) ===")
    body = {
        "model": "auto",
        "messages": [{"role": "user", "content": "hi, just say hello"}],
        "stream": True,
    }
    
    try:
        async with client.stream("POST", f"{base_url}/v1/chat/completions", json=body, headers=headers, timeout=30) as resp:
            print(f"Status: {resp.status_code}")
            print(f"Content-Type: {resp.headers.get('content-type', 'N/A')}")
            line_count = 0
            async for line in resp.aiter_lines():
                line = line.strip()
                if line:
                    print(f"  [{line_count}] {line[:200]}")
                    line_count += 1
                    if line_count > 30:
                        print("  ... (truncated)")
                        break
    except Exception as e:
        print(f"Error: {e}")
    
    # 也试试不同的模型名
    print("\n=== POST /v1/chat/completions with specific model ===")
    for model_name in ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-pro", "gemini-flash"]:
        body = {
            "model": model_name,
            "messages": [{"role": "user", "content": "say ok"}],
            "stream": True,
        }
        try:
            resp = await client.post(f"{base_url}/v1/chat/completions", json=body, headers=headers, timeout=10)
            ct = resp.headers.get('content-type', '')
            is_html = 'html' in ct
            preview = resp.text[:200] if not is_html else f'[HTML, status={resp.status_code}]'
            print(f"  model={model_name} -> {resp.status_code}: {preview}")
        except Exception as e:
            print(f"  model={model_name} -> ERROR: {e}")
    
    # 试非 stream
    print("\n=== POST /v1/chat/completions (non-stream) ===")
    body = {
        "model": "auto",
        "messages": [{"role": "user", "content": "say ok"}],
        "stream": False,
    }
    try:
        resp = await client.post(f"{base_url}/v1/chat/completions", json=body, headers=headers, timeout=15)
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.text[:500]}")
    except Exception as e:
        print(f"Error: {e}")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
