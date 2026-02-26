"""探测 Gemini、Grok、Deepseek 三个 channel 的 API 接口"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.auth import ChatShareAuth

async def probe_channel(channel: str):
    print(f"\n{'='*60}")
    print(f"探测 channel: {channel}")
    print(f"{'='*60}")
    
    auth = ChatShareAuth()
    await auth.login()
    print(f"[+] 登录成功, token={auth.token[:20]}...")
    
    # 获取车辆列表
    cars = await auth.get_car_page(channel)
    print(f"[+] {channel} 车辆数: {len(cars)}")
    if not cars:
        print(f"[-] {channel} 没有可用车辆，跳过")
        await auth.close()
        return
    
    for i, car in enumerate(cars[:3]):
        print(f"  车辆 {i}: carid={car.get('carid')}, count={car.get('count')}, available={car.get('available')}")
    
    # 进车
    best_car = cars[0]
    enter = await auth.enter_car(channel, best_car['carid'])
    chat_url = enter['chat_url'].rstrip('/')
    cookies = enter['cookies']
    print(f"[+] 进车成功, chat_url={chat_url}")
    print(f"[+] cookies keys: {list(cookies.keys())}")
    
    import httpx
    client = httpx.AsyncClient(timeout=8, verify=False)
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    headers = {
        'Cookie': cookie_str,
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
    }
    
    # 探测常见路径
    probe_paths = [
        # ChatGPT 风格
        '/backend-api/conversation',
        '/backend-api/f/conversation',
        '/backend-api/models',
        '/backend-api/me',
        # OpenAI API 风格
        '/v1/chat/completions',
        '/v1/models',
        '/api/chat/completions',
        '/api/models',
        # Gemini 风格
        '/api/generate',
        '/api/chat',
        '/api/stream',
        # Grok 风格
        '/rest/app-chat/conversations/new',
        '/rest/app-chat/conversations',
        '/api/rpc',
        # Deepseek 风格
        '/api/v0/chat/completions',
        '/api/v0/chat/completion',
        '/chat/completions',
        # 通用
        '/api/bootstrap',
        '/api/health',
        '/health',
        '/',
    ]
    
    print(f"\n[*] 探测 API 路径...")
    for path in probe_paths:
        try:
            url = f"{chat_url}{path}"
            resp = await client.get(url, headers=headers)
            status = resp.status_code
            body_preview = resp.text[:200] if resp.text else ""
            if status != 404:
                print(f"  GET {path} -> {status}: {body_preview}")
        except Exception as e:
            print(f"  GET {path} -> ERROR: {e}")
    
    # 也试 POST 一些关键路径
    print(f"\n[*] POST 探测...")
    post_paths_bodies = [
        ('/backend-api/conversation', {
            "action": "next",
            "messages": [{"id": "test", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hi"]}}],
            "model": "auto",
            "parent_message_id": "test-parent",
        }),
        ('/backend-api/f/conversation', {
            "action": "next",
            "messages": [{"id": "test", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hi"]}}],
            "model": "auto",
            "parent_message_id": "test-parent",
        }),
        ('/v1/chat/completions', {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }),
        ('/api/v0/chat/completions', {
            "model": "auto",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }),
        ('/rest/app-chat/conversations/new', {
            "message": "hi",
        }),
    ]
    
    for path, body in post_paths_bodies:
        try:
            url = f"{chat_url}{path}"
            resp = await client.post(url, json=body, headers=headers)
            status = resp.status_code
            body_preview = resp.text[:300] if resp.text else ""
            if status != 404:
                print(f"  POST {path} -> {status}: {body_preview}")
        except Exception as e:
            print(f"  POST {path} -> ERROR: {e}")
    
    await client.aclose()
    await auth.close()

async def main():
    for channel in ['gemini', 'grok', 'deepseek']:
        try:
            await probe_channel(channel)
        except Exception as e:
            print(f"\n[!] {channel} 探测失败: {e}")

asyncio.run(main())
