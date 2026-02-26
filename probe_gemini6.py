"""深入分析 gemini-voyager.js 和页面内联脚本"""
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
    
    # 下载 gemini-voyager.js
    print("=== gemini-voyager.js ===")
    resp = await client.get(f"{base_url}/injectjs/gemini-voyager/gemini-voyager.js", headers=headers)
    print(f"Status: {resp.status_code}, len={len(resp.text)}")
    print(resp.text[:5000])
    print("\n...\n")
    if len(resp.text) > 5000:
        print(resp.text[-2000:])
    
    # 获取 HTML 中所有内联 script
    print("\n\n=== 内联 script 标签 ===")
    resp = await client.get(chat_url, headers=headers)
    html = resp.text
    
    # 找所有 data-sorux 相关的内容
    sorux_matches = re.findall(r'data-sorux[^>]*>([^<]{0,5000})', html)
    for i, m in enumerate(sorux_matches):
        print(f"\n--- sorux script {i} ---")
        print(m[:2000])
    
    # 找所有内联 script（非 src 的）
    inline_scripts = re.findall(r'<script[^>]*>([^<]{100,})</script>', html)
    for i, s in enumerate(inline_scripts):
        if any(kw in s.lower() for kw in ['sorux', 'token', 'auth', 'refresh', 'bearer', 'login', 'session']):
            print(f"\n--- inline script {i} (len={len(s)}) ---")
            print(s[:3000])
    
    # 搜索 watermark-remover
    print("\n\n=== watermark-remover-v2.js ===")
    resp = await client.get(f"{base_url}/sgw-assets/watermark-remover-v2.js?v=9", headers=headers)
    if 'soruxgpt' in resp.text.lower() or 'token' in resp.text.lower() or 'auth' in resp.text.lower():
        print(f"Status: {resp.status_code}, len={len(resp.text)}")
        print(resp.text[:3000])
    else:
        print("No relevant content")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
