"""用更广泛的搜索找 soruxgpt_gemini_rt 的来源"""
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
    
    # 1. 下载 /app 页面，搜索所有 inline script 中的关键词
    resp = await client.get(chat_url, headers=headers)
    html = resp.text
    
    # 搜索所有 script 标签内容
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    print(f"Found {len(scripts)} inline scripts")
    
    for i, script in enumerate(scripts):
        if len(script) < 10:
            continue
        # 搜索 cookie 设置、localStorage、token 相关
        for kw in ['soruxgpt', 'gemini_rt', 'setCookie', 'document.cookie', 'localStorage', 
                    'refresh_token', 'rt_token', '/v1/chat', 'Bearer', 'authorization']:
            if kw.lower() in script.lower():
                positions = [m.start() for m in re.finditer(re.escape(kw), script, re.IGNORECASE)]
                print(f"\n  Script #{i} (len={len(script)}): '{kw}' x{len(positions)}")
                for pos in positions[:3]:
                    snippet = script[max(0,pos-200):pos+200].replace('\n', ' ')
                    print(f"    ...{snippet}...")
    
    # 2. 下载所有 JS 文件（包括 chunk 文件）
    print("\n\n=== 搜索所有 JS 文件 ===")
    # 找所有 JS URL（包括动态加载的）
    js_urls = set()
    for m in re.finditer(r'["\']([^"\']*\.js(?:\?[^"\']*)?)["\']', html):
        js_urls.add(m.group(1))
    for m in re.finditer(r'src="([^"]*)"', html):
        if '.js' in m.group(1):
            js_urls.add(m.group(1))
    
    print(f"Found {len(js_urls)} JS URLs")
    
    for js_url in sorted(js_urls):
        if not js_url.startswith('http'):
            full_url = f"{base_url}{js_url}" if js_url.startswith('/') else f"{base_url}/{js_url}"
        else:
            full_url = js_url
        try:
            resp = await client.get(full_url, headers=headers)
            js = resp.text
            if len(js) < 50:
                continue
            for kw in ['soruxgpt_gemini_rt', 'gemini_rt', 'soruxgpt']:
                if kw.lower() in js.lower():
                    positions = [m.start() for m in re.finditer(re.escape(kw), js, re.IGNORECASE)]
                    print(f"\n  {js_url} (len={len(js)}): '{kw}' x{len(positions)}")
                    for pos in positions[:5]:
                        snippet = js[max(0,pos-200):pos+200].replace('\n', ' ')
                        print(f"    ...{snippet}...")
        except Exception as e:
            pass
    
    # 3. 检查 sgw-assets 目录下的 JS
    print("\n\n=== sgw-assets JS ===")
    sgw_paths = [
        '/sgw-assets/watermark-remover-v2.js?v=9',
        '/sgw-assets/watermark-remover.js',
        '/injectjs/gemini-voyager/gemini-voyager.js',
        '/injectjs/gemini-voyager/gemini-voyager.min.js',
    ]
    for path in sgw_paths:
        url = f"{base_url}{path}"
        try:
            resp = await client.get(url, headers=headers)
            js = resp.text
            if len(js) < 50:
                continue
            for kw in ['soruxgpt', 'gemini_rt', 'refresh', 'cookie', '/v1/', 'Bearer', 'authorization', 'token']:
                positions = [m.start() for m in re.finditer(re.escape(kw), js, re.IGNORECASE)]
                if positions:
                    print(f"\n  {path} (len={len(js)}): '{kw}' x{len(positions)}")
                    for pos in positions[:3]:
                        snippet = js[max(0,pos-200):pos+200].replace('\n', ' ')
                        print(f"    ...{snippet}...")
        except:
            pass
    
    await client.aclose()
    await auth.close()

asyncio.run(main())
