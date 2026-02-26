"""分析 Gemini /app 页面的 JS 代码，找 soruxgpt_gemini_rt 的获取方式"""
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
    
    # 获取 /app 页面
    resp = await client.get(chat_url, headers=headers)
    html = resp.text
    
    # 搜索所有 JS 文件链接
    js_files = re.findall(r'src="([^"]*\.js[^"]*)"', html)
    print(f"Found {len(js_files)} JS files")
    for f in js_files[:10]:
        print(f"  {f}")
    
    # 搜索 HTML 中的关键词
    keywords = ['soruxgpt', 'gemini_rt', 'refresh', 'Bearer', '/v1/', 'authorization', 'localStorage', 'sessionStorage', 'cookie']
    for kw in keywords:
        positions = [m.start() for m in re.finditer(re.escape(kw), html, re.IGNORECASE)]
        if positions:
            print(f"\n'{kw}' found at {len(positions)} positions")
            for pos in positions[:3]:
                snippet = html[max(0,pos-80):pos+80]
                print(f"  ...{snippet}...")
    
    # 下载主要的 JS 文件，搜索 soruxgpt_gemini_rt
    print("\n\n=== 搜索 JS 文件中的 soruxgpt_gemini_rt ===")
    for js_url in js_files[:15]:
        if not js_url.startswith('http'):
            if js_url.startswith('/'):
                js_url = f"{base_url}{js_url}"
            else:
                js_url = f"{base_url}/app/{js_url}"
        try:
            resp = await client.get(js_url, headers=headers, timeout=10)
            js_text = resp.text
            if 'soruxgpt' in js_text.lower() or 'gemini_rt' in js_text.lower():
                print(f"\n[FOUND] {js_url} (len={len(js_text)})")
                # 找到相关代码片段
                for kw in ['soruxgpt_gemini_rt', 'soruxgpt', 'gemini_rt']:
                    for m in re.finditer(re.escape(kw), js_text, re.IGNORECASE):
                        pos = m.start()
                        snippet = js_text[max(0,pos-150):pos+150]
                        print(f"  [{kw}] ...{snippet}...")
            elif '/v1/chat' in js_text:
                print(f"\n[v1/chat found] {js_url}")
                for m in re.finditer(r'/v1/chat', js_text):
                    pos = m.start()
                    snippet = js_text[max(0,pos-100):pos+100]
                    print(f"  ...{snippet}...")
        except Exception as e:
            print(f"  Error fetching {js_url}: {e}")
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
