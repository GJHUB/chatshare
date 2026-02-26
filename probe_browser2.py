"""用 sync playwright 获取 soruxgpt_gemini_rt"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

# 先用 async 获取 cookies
import asyncio
from src.auth import ChatShareAuth

async def get_enter_data():
    auth = ChatShareAuth()
    await auth.login()
    cars = await auth.get_car_page('gemini')
    enter = await auth.enter_car('gemini', cars[0]['carid'])
    token = auth.token
    await auth.close()
    return enter, token

enter, chatshare_token = asyncio.run(get_enter_data())
chat_url = enter['chat_url'].rstrip('/')
cookies = enter['cookies']
base_url = chat_url.rsplit('/app', 1)[0] if '/app' in chat_url else chat_url

print(f"chat_url: {chat_url}")
print(f"cookies: {list(cookies.keys())}")

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(ignore_https_errors=True)
    
    cookie_list = []
    for k, v in cookies.items():
        cookie_list.append({
            'name': k,
            'value': str(v),
            'domain': 'gemini-node2.chatshare.biz',
            'path': '/',
        })
    context.add_cookies(cookie_list)
    
    page = context.new_page()
    
    # 捕获网络请求
    captured = []
    def on_req(req):
        url = req.url
        hdrs = req.headers
        if 'authorization' in hdrs:
            captured.append({'url': url, 'method': req.method, 'auth': hdrs.get('authorization', '')[:200]})
    page.on('request', on_req)
    
    print(f"\nNavigating to {chat_url}...")
    try:
        page.goto(chat_url, wait_until='domcontentloaded', timeout=20000)
        page.wait_for_timeout(5000)  # 等 5 秒让 JS 执行
    except Exception as e:
        print(f"Navigation: {e}")
    
    # 获取 cookies
    all_cookies = context.cookies()
    print(f"\n=== Browser Cookies ({len(all_cookies)}) ===")
    for c in all_cookies:
        val = str(c['value'])
        print(f"  {c['name']}: {val[:120]}{'...' if len(val)>120 else ''}")
    
    # 获取 localStorage
    print(f"\n=== localStorage ===")
    try:
        ls = page.evaluate("""() => {
            const items = {};
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                items[key] = localStorage.getItem(key);
            }
            return items;
        }""")
        for k, v in ls.items():
            print(f"  {k}: {str(v)[:200]}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 获取 sessionStorage
    print(f"\n=== sessionStorage ===")
    try:
        ss = page.evaluate("""() => {
            const items = {};
            for (let i = 0; i < sessionStorage.length; i++) {
                const key = sessionStorage.key(i);
                items[key] = sessionStorage.getItem(key);
            }
            return items;
        }""")
        for k, v in ss.items():
            print(f"  {k}: {str(v)[:200]}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 捕获的带 auth 的请求
    print(f"\n=== 带 Authorization 的请求 ({len(captured)}) ===")
    for r in captured:
        print(f"  {r['method']} {r['url']}")
        print(f"    Auth: {r['auth']}")
    
    browser.close()
