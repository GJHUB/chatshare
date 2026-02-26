"""在 Gemini 页面发送消息，捕获 API 调用中的 token"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
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

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(ignore_https_errors=True)
    
    cookie_list = []
    for k, v in cookies.items():
        cookie_list.append({
            'name': k, 'value': str(v),
            'domain': 'gemini-node2.chatshare.biz', 'path': '/',
        })
    context.add_cookies(cookie_list)
    
    page = context.new_page()
    
    # 捕获所有请求
    all_requests = []
    def on_req(req):
        entry = {
            'url': req.url,
            'method': req.method,
            'headers': dict(req.headers),
        }
        try:
            entry['post_data'] = req.post_data[:500] if req.post_data else None
        except:
            entry['post_data'] = None
        all_requests.append(entry)
    page.on('request', on_req)
    
    all_responses = []
    def on_resp(resp):
        entry = {
            'url': resp.url,
            'status': resp.status,
            'headers': dict(resp.headers),
        }
        all_responses.append(entry)
    page.on('response', on_resp)
    
    print(f"Navigating to {chat_url}...")
    page.goto(chat_url, wait_until='domcontentloaded', timeout=20000)
    page.wait_for_timeout(3000)
    
    # 截图看看页面状态
    page.screenshot(path='/tmp/gemini_page.png')
    print("Screenshot saved to /tmp/gemini_page.png")
    
    # 尝试找到输入框并发送消息
    print("\n=== 尝试发送消息 ===")
    
    # 先看看页面上有什么输入元素
    inputs = page.evaluate("""() => {
        const els = [];
        // textarea
        document.querySelectorAll('textarea').forEach(el => {
            els.push({tag: 'textarea', placeholder: el.placeholder, class: el.className, id: el.id});
        });
        // contenteditable
        document.querySelectorAll('[contenteditable]').forEach(el => {
            els.push({tag: el.tagName, contenteditable: true, class: el.className, id: el.id});
        });
        // input[type=text]
        document.querySelectorAll('input[type=text], input:not([type])').forEach(el => {
            els.push({tag: 'input', placeholder: el.placeholder, class: el.className, id: el.id});
        });
        // rich-textarea
        document.querySelectorAll('rich-textarea, .ql-editor, [role="textbox"]').forEach(el => {
            els.push({tag: el.tagName, role: el.getAttribute('role'), class: el.className, id: el.id});
        });
        return els;
    }""")
    print(f"Found input elements: {json.dumps(inputs, indent=2)}")
    
    # 尝试在 contenteditable 或 textarea 中输入
    typed = False
    for selector in ['[contenteditable="true"]', 'textarea', 'rich-textarea .ql-editor', '[role="textbox"]', '.ql-editor']:
        try:
            el = page.query_selector(selector)
            if el:
                print(f"Found: {selector}")
                el.click()
                page.wait_for_timeout(500)
                page.keyboard.type("say ok", delay=50)
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                typed = True
                print("Message sent!")
                break
        except Exception as e:
            print(f"  {selector}: {e}")
    
    if typed:
        # 等待响应
        print("Waiting for API response...")
        page.wait_for_timeout(8000)
    
    # 检查 cookies 变化
    all_cookies = context.cookies()
    print(f"\n=== Cookies after interaction ({len(all_cookies)}) ===")
    for c in all_cookies:
        val = str(c['value'])
        print(f"  {c['name']}: {val[:120]}{'...' if len(val)>120 else ''}")
    
    # localStorage 变化
    ls = page.evaluate("""() => {
        const items = {};
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            items[key] = localStorage.getItem(key);
        }
        return items;
    }""")
    print(f"\n=== localStorage after interaction ===")
    for k, v in ls.items():
        print(f"  {k}: {str(v)[:200]}")
    
    # 打印所有 API 请求（非静态资源）
    print(f"\n=== API 请求 ===")
    for r in all_requests:
        url = r['url']
        if any(ext in url for ext in ['.js', '.css', '.png', '.jpg', '.svg', '.woff', '.ico', '.gif']):
            continue
        if 'google' in url and 'analytics' in url:
            continue
        print(f"  {r['method']} {url}")
        if r['headers'].get('authorization'):
            print(f"    Authorization: {r['headers']['authorization'][:200]}")
        if r['headers'].get('cookie'):
            cookie_val = r['headers']['cookie']
            if 'soruxgpt' in cookie_val.lower():
                print(f"    Cookie contains soruxgpt!")
        if r['post_data']:
            print(f"    Body: {r['post_data'][:200]}")
    
    browser.close()
