"""探测 Gemini / Grok / Deepseek 的认证和接口"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.auth import ChatShareAuth
import httpx

async def probe_channel(auth: ChatShareAuth, channel: str):
    print(f"\n{'='*60}")
    print(f"  探测 channel: {channel}")
    print(f"{'='*60}")
    
    try:
        cars = await auth.get_car_page(channel)
    except Exception as e:
        print(f"  get_car_page 失败: {e}")
        return
    
    if not cars:
        print(f"  没有可用车辆")
        return
    
    print(f"  找到 {len(cars)} 辆车")
    for c in cars[:3]:
        print(f"    carid={c.get('carid')} count={c.get('count')} available={c.get('available')}")
    
    best_car = cars[0]
    try:
        enter = await auth.enter_car(channel, best_car['carid'])
    except Exception as e:
        print(f"  enter_car 失败: {e}")
        return
    
    chat_url = enter['chat_url'].rstrip('/')
    cookies = enter['cookies']
    
    print(f"  chat_url: {chat_url}")
    print(f"  cookies: {list(cookies.keys())}")
    for k, v in cookies.items():
        sv = str(v)
        print(f"    {k}: {sv[:80]}{'...' if len(sv) > 80 else ''}")
    
    # 去掉 /app 后缀得到 base_url
    if '/app' in chat_url:
        base_url = chat_url.rsplit('/app', 1)[0]
    else:
        base_url = chat_url
    
    print(f"  base_url: {base_url}")
    
    client = httpx.AsyncClient(timeout=15, verify=False)
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    
    # ---- 1. 试各种 token 作为 Bearer 调 /v1/chat/completions ----
    print(f"\n  --- 试 Bearer token 调 /v1/chat/completions ---")
    
    tokens_to_try = {
        'chatshare_token': auth.token,
        'gfsessionid': cookies.get('gfsessionid', ''),
        'token_cookie': cookies.get('token', ''),
    }
    for k, v in cookies.items():
        if k not in ('gfsessionid', 'token') and len(str(v)) > 10:
            tokens_to_try[f'cookie_{k}'] = v
    
    # 根据 channel 选模型
    model_map = {
        'gemini': 'gemini-2.0-flash',
        'grok': 'grok-3',
        'deepseek': 'deepseek-chat',
    }
    test_model = model_map.get(channel, 'auto')
    
    for name, token in tokens_to_try.items():
        if not token:
            continue
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        body = {
            'model': test_model,
            'messages': [{'role': 'user', 'content': 'say ok'}],
            'stream': False,
        }
        for url_base in [base_url, chat_url]:
            endpoint = f'{url_base}/v1/chat/completions'
            try:
                resp = await client.post(endpoint, json=body, headers=headers)
                ct = resp.headers.get('content-type', '')
                if 'json' in ct or 'text' in ct:
                    preview = resp.text[:300]
                else:
                    preview = f'[{ct} len={len(resp.text)}]'
                print(f"    {name} @ {endpoint}")
                print(f"      -> {resp.status_code} | {preview}")
            except Exception as e:
                print(f"    {name} @ {endpoint}")
                print(f"      -> ERROR: {e}")
    
    # ---- 2. 试 cookie 方式调 /v1/chat/completions ----
    print(f"\n  --- 试 Cookie 方式调 /v1/chat/completions ---")
    for url_base in [base_url, chat_url]:
        endpoint = f'{url_base}/v1/chat/completions'
        headers = {
            'Cookie': cookie_str,
            'Content-Type': 'application/json',
        }
        body = {
            'model': test_model,
            'messages': [{'role': 'user', 'content': 'say ok'}],
            'stream': False,
        }
        try:
            resp = await client.post(endpoint, json=body, headers=headers)
            ct = resp.headers.get('content-type', '')
            if 'json' in ct or 'text' in ct:
                preview = resp.text[:300]
            else:
                preview = f'[{ct} len={len(resp.text)}]'
            print(f"    cookie @ {endpoint}")
            print(f"      -> {resp.status_code} | {preview}")
        except Exception as e:
            print(f"    cookie @ {endpoint}")
            print(f"      -> ERROR: {e}")
    
    # ---- 3. 试 Cookie + Bearer 组合 ----
    print(f"\n  --- 试 Cookie + Bearer 组合 ---")
    for name, token in tokens_to_try.items():
        if not token:
            continue
        headers = {
            'Cookie': cookie_str,
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        body = {
            'model': test_model,
            'messages': [{'role': 'user', 'content': 'say ok'}],
            'stream': False,
        }
        endpoint = f'{base_url}/v1/chat/completions'
        try:
            resp = await client.post(endpoint, json=body, headers=headers)
            ct = resp.headers.get('content-type', '')
            if 'json' in ct or 'text' in ct:
                preview = resp.text[:300]
            else:
                preview = f'[{ct} len={len(resp.text)}]'
            print(f"    cookie+{name} @ {endpoint}")
            print(f"      -> {resp.status_code} | {preview}")
        except Exception as e:
            print(f"    cookie+{name} @ {endpoint}")
            print(f"      -> ERROR: {e}")
    
    # ---- 4. 试 backend-api/f/conversation (sass 格式) ----
    print(f"\n  --- 试 backend-api 格式 ---")
    import uuid
    sass_body = {
        "action": "next",
        "messages": [{
            "id": str(uuid.uuid4()),
            "author": {"role": "user"},
            "content": {"content_type": "text", "parts": ["say ok"]},
        }],
        "parent_message_id": "client-created-root",
        "model": test_model,
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_contextual_info": {"app_name": "chatgpt.com"},
        "system_hints": [],
    }
    for url_base in [base_url, chat_url]:
        for path in ['/backend-api/f/conversation', '/backend-api/conversation']:
            endpoint = f'{url_base}{path}'
            headers = {
                'Cookie': cookie_str,
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
            }
            try:
                resp = await client.post(endpoint, json=sass_body, headers=headers)
                ct = resp.headers.get('content-type', '')
                preview = resp.text[:400]
                print(f"    {endpoint}")
                print(f"      -> {resp.status_code} ({ct}) | {preview}")
            except Exception as e:
                print(f"    {endpoint}")
                print(f"      -> ERROR: {e}")
    
    await client.aclose()

async def main():
    auth = ChatShareAuth()
    await auth.login()
    print(f"ChatShare token: {auth.token[:30]}...")
    
    for channel in ['gemini', 'grok', 'deepseek']:
        await probe_channel(auth, channel)
    
    await auth.close()

asyncio.run(main())
