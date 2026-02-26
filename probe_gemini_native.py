"""探测 Gemini 原生 Bard API - StreamGenerate"""
import asyncio, sys, os, json, re, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
from src.auth import ChatShareAuth
from playwright.sync_api import sync_playwright

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
    
    # 捕获 StreamGenerate 请求和响应
    stream_req = {}
    stream_resp = {}
    
    def on_req(req):
        if 'StreamGenerate' in req.url:
            stream_req['url'] = req.url
            stream_req['method'] = req.method
            stream_req['headers'] = dict(req.headers)
            stream_req['post_data'] = req.post_data
    
    def on_resp(resp):
        if 'StreamGenerate' in resp.url:
            stream_resp['url'] = resp.url
            stream_resp['status'] = resp.status
            try:
                stream_resp['body'] = resp.text()[:2000]
            except:
                stream_resp['body'] = '(could not read)'
    
    page.on('request', on_req)
    page.on('response', on_resp)
    
    page.goto(chat_url, wait_until='domcontentloaded', timeout=20000)
    page.wait_for_timeout(3000)
    
    # 提取 at token 和 bl 参数
    html = page.content()
    at_match = re.search(r'"SNlM0e":"([^"]+)"', html)
    bl_match = re.search(r'"cfb2h":"([^"]+)"', html)
    fsid_match = re.search(r'"FdrFJe":"([^"]+)"', html)
    
    at_token = at_match.group(1) if at_match else ''
    bl_param = bl_match.group(1) if bl_match else ''
    fsid = fsid_match.group(1) if fsid_match else ''
    
    print(f"\nat_token (SNlM0e): {at_token[:50]}...")
    print(f"bl (cfb2h): {bl_param}")
    print(f"f.sid (FdrFJe): {fsid}")
    
    # 发送消息并等待
    textarea = page.query_selector('textarea')
    if textarea:
        textarea.click()
        page.wait_for_timeout(300)
        page.keyboard.type("say ok", delay=30)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        print("\nMessage sent, waiting for StreamGenerate...")
        page.wait_for_timeout(10000)
    
    print(f"\n=== StreamGenerate 请求 ===")
    if stream_req:
        print(f"URL: {stream_req.get('url', 'N/A')}")
        print(f"Method: {stream_req.get('method', 'N/A')}")
        # 解码 post_data
        pd = stream_req.get('post_data', '')
        if pd:
            decoded = urllib.parse.unquote(pd)
            print(f"Post data (decoded, first 1000): {decoded[:1000]}")
    else:
        print("No StreamGenerate request captured!")
    
    print(f"\n=== StreamGenerate 响应 ===")
    if stream_resp:
        print(f"Status: {stream_resp.get('status', 'N/A')}")
        body = stream_resp.get('body', '')
        print(f"Body (first 1000): {body[:1000]}")
    else:
        print("No StreamGenerate response captured!")
    
    browser.close()
