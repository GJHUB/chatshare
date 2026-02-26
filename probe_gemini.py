"""深入探测 Gemini 节点 API"""
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
    
    print(f"chat_url: {chat_url}")
    print(f"cookies: {list(cookies.keys())}")
    
    # chat_url 是 .../app，base 应该是去掉 /app
    base_url = chat_url.rstrip('/').rsplit('/app', 1)[0]
    print(f"base_url (without /app): {base_url}")
    
    client = httpx.AsyncClient(timeout=10, verify=False)
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    headers = {
        'Cookie': cookie_str,
        'Content-Type': 'application/json',
        'Accept': '*/*',
    }
    
    # 先看根路径和 /app 路径的区别
    print("\n=== 基础探测 ===")
    for url in [base_url, f"{base_url}/", f"{base_url}/app", f"{base_url}/app/"]:
        try:
            resp = await client.get(url, headers=headers)
            print(f"GET {url} -> {resp.status_code}, content-type: {resp.headers.get('content-type', 'N/A')}, len={len(resp.text)}")
        except Exception as e:
            print(f"GET {url} -> ERROR: {e}")
    
    # 在 base_url 下探测 API
    print("\n=== base_url 下探测 ===")
    api_paths = [
        '/backend-api/conversation',
        '/backend-api/f/conversation',
        '/backend-api/models',
        '/backend-api/me',
        '/backend-api/f/conversation/prepare',
        '/backend-api/sentinel/chat-requirements/finalize',
        '/v1/chat/completions',
        '/v1/models',
        '/api/generate',
        '/api/chat',
        '/api/models',
        '/api/bootstrap',
        '/api/health',
        '/health',
        '/api/v0/chat/completions',
    ]
    
    for path in api_paths:
        try:
            url = f"{base_url}{path}"
            resp = await client.get(url, headers=headers)
            ct = resp.headers.get('content-type', '')
            is_html = 'html' in ct
            preview = resp.text[:150] if not is_html else '[HTML page]'
            if resp.status_code != 404:
                print(f"  GET {path} -> {resp.status_code} ({ct}): {preview}")
        except Exception as e:
            print(f"  GET {path} -> ERROR: {e}")
    
    # 在 chat_url (/app) 下也探测
    print("\n=== chat_url (/app) 下探测 ===")
    app_url = chat_url.rstrip('/')
    for path in api_paths:
        try:
            url = f"{app_url}{path}"
            resp = await client.get(url, headers=headers)
            ct = resp.headers.get('content-type', '')
            is_html = 'html' in ct
            preview = resp.text[:150] if not is_html else '[HTML page]'
            if resp.status_code != 404:
                print(f"  GET {path} -> {resp.status_code} ({ct}): {preview}")
        except Exception as e:
            print(f"  GET {path} -> ERROR: {e}")
    
    # POST 测试 - 在 base_url 下
    print("\n=== POST 探测 (base_url) ===")
    sass_body = {
        "action": "next",
        "messages": [{"id": "test-id", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hi"]}}],
        "model": "auto",
        "parent_message_id": "client-created-root",
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "supports_buffering": True,
        "supported_encodings": ["v1"],
    }
    
    for path in ['/backend-api/conversation', '/backend-api/f/conversation']:
        try:
            url = f"{base_url}{path}"
            resp = await client.post(url, json=sass_body, headers=headers)
            ct = resp.headers.get('content-type', '')
            is_html = 'html' in ct
            preview = resp.text[:300] if not is_html else f'[HTML page, status={resp.status_code}]'
            print(f"  POST {path} -> {resp.status_code} ({ct}): {preview}")
        except Exception as e:
            print(f"  POST {path} -> ERROR: {e}")
    
    # 试试 gpt 格式
    gpt_body = {
        "action": "next",
        "messages": [{"id": "test-id", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hi"]}}],
        "model": "auto",
        "parent_message_id": "test-parent",
        "stream": True,
    }
    
    for path in ['/backend-api/conversation', '/backend-api/f/conversation']:
        try:
            url = f"{base_url}{path}"
            resp = await client.post(url, json=gpt_body, headers=headers)
            ct = resp.headers.get('content-type', '')
            is_html = 'html' in ct
            preview = resp.text[:300] if not is_html else f'[HTML page, status={resp.status_code}]'
            print(f"  POST(gpt) {path} -> {resp.status_code} ({ct}): {preview}")
        except Exception as e:
            print(f"  POST(gpt) {path} -> ERROR: {e}")
    
    # 看看 gfsessionid cookie 的值
    print(f"\n=== Cookie 详情 ===")
    for k, v in cookies.items():
        print(f"  {k} = {v[:50]}..." if len(str(v)) > 50 else f"  {k} = {v}")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
