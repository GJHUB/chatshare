"""用 playwright 浏览器访问 Gemini 页面，获取 soruxgpt_gemini_rt cookie"""
import asyncio, sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from src.auth import ChatShareAuth

async def main():
    auth = ChatShareAuth()
    await auth.login()
    cars = await auth.get_car_page('gemini')
    enter = await auth.enter_car('gemini', cars[0]['carid'])
    chat_url = enter['chat_url'].rstrip('/')
    cookies = enter['cookies']
    base_url = chat_url.rsplit('/app', 1)[0] if '/app' in chat_url else chat_url
    
    print(f"chat_url: {chat_url}")
    print(f"cookies: {cookies}")
    
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Installing playwright...")
        os.system("pip3 install playwright && playwright install chromium")
        from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        
        # 设置 cookies
        cookie_list = []
        for k, v in cookies.items():
            cookie_list.append({
                'name': k,
                'value': str(v),
                'domain': 'gemini-node2.chatshare.biz',
                'path': '/',
            })
        await context.add_cookies(cookie_list)
        
        page = await context.new_page()
        
        # 监听所有网络请求
        requests_log = []
        def on_request(req):
            if '/v1/' in req.url or 'soruxgpt' in req.url.lower() or 'token' in req.url.lower() or 'auth' in req.url.lower():
                requests_log.append({
                    'url': req.url,
                    'method': req.method,
                    'headers': dict(req.headers),
                })
        
        responses_log = []
        def on_response(resp):
            if '/v1/' in resp.url or 'soruxgpt' in resp.url.lower() or 'token' in resp.url.lower() or 'auth' in resp.url.lower():
                responses_log.append({
                    'url': resp.url,
                    'status': resp.status,
                    'headers': dict(resp.headers),
                })
        
        page.on('request', on_request)
        page.on('response', on_response)
        
        print(f"\nNavigating to {chat_url}...")
        await page.goto(chat_url, wait_until='networkidle', timeout=30000)
        
        # 等待页面加载
        await asyncio.sleep(3)
        
        # 获取所有 cookies
        all_cookies = await context.cookies()
        print(f"\n=== Browser Cookies ({len(all_cookies)}) ===")
        for c in all_cookies:
            print(f"  {c['name']}: {str(c['value'])[:100]}{'...' if len(str(c['value']))>100 else ''}")
            if 'soruxgpt' in c['name'].lower() or 'rt' in c['name'].lower() or 'refresh' in c['name'].lower():
                print(f"    *** FOUND: {c['name']} = {c['value']} ***")
        
        # 获取 localStorage
        print(f"\n=== localStorage ===")
        ls_data = await page.evaluate("""() => {
            const items = {};
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                items[key] = localStorage.getItem(key);
            }
            return items;
        }""")
        for k, v in ls_data.items():
            sv = str(v)[:150]
            print(f"  {k}: {sv}")
            if 'soruxgpt' in k.lower() or 'rt' in k.lower() or 'refresh' in k.lower() or 'token' in k.lower():
                print(f"    *** FOUND: {k} = {v} ***")
        
        # 获取 sessionStorage
        print(f"\n=== sessionStorage ===")
        ss_data = await page.evaluate("""() => {
            const items = {};
            for (let i = 0; i < sessionStorage.length; i++) {
                const key = sessionStorage.key(i);
                items[key] = sessionStorage.getItem(key);
            }
            return items;
        }""")
        for k, v in ss_data.items():
            sv = str(v)[:150]
            print(f"  {k}: {sv}")
        
        # 打印捕获的请求
        print(f"\n=== 捕获的相关请求 ({len(requests_log)}) ===")
        for r in requests_log:
            print(f"  {r['method']} {r['url']}")
            if 'authorization' in r['headers']:
                print(f"    Authorization: {r['headers']['authorization'][:100]}")
        
        print(f"\n=== 捕获的相关响应 ({len(responses_log)}) ===")
        for r in responses_log:
            print(f"  {r['status']} {r['url']}")
        
        await browser.close()
    
    await auth.close()

asyncio.run(main())
