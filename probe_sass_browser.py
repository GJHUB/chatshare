"""Capture sass-node2 Bearer JWT via browser.
Enter through a channel that routes to sass-node2, capture the RS256 JWT."""
import asyncio, sys, os, json, re, base64
sys.path.insert(0, os.path.dirname(__file__))
from src.auth import ChatShareAuth

async def get_enter_data():
    auth = ChatShareAuth()
    await auth.login()
    # Try all channels with cars
    for ch in ["gemini", "claude", "xy"]:
        cars = await auth.get_car_page(ch)
        avail = [c for c in cars if c.get("available", True)]
        if avail:
            enter = await auth.enter_car(ch, avail[0]["carid"])
            print(f"Channel {ch}: URL={enter['chat_url']}")
    token = auth.token
    await auth.close()
    return token

chatshare_token = asyncio.run(get_enter_data())

from playwright.sync_api import sync_playwright

# We need to visit sass-node2 through the ChatShare frontend
# The frontend at node2.chatshare.biz loads sass-node2 models
# Let's login to the ChatShare web UI and navigate to a sass model

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(ignore_https_errors=True)
    
    # Set the ChatShare token cookie
    context.add_cookies([{
        "name": "token",
        "value": chatshare_token,
        "domain": "node2.chatshare.biz",
        "path": "/",
    }])
    
    page = context.new_page()
    
    # Capture all requests to sass-node2
    sass_requests = []
    def on_req(req):
        if "sass-node2" in req.url or "backend-api" in req.url:
            entry = {
                "url": req.url,
                "method": req.method,
                "headers": dict(req.headers),
            }
            sass_requests.append(entry)
            auth_header = req.headers.get("authorization", "")
            if auth_header:
                print(f"[REQ] {req.method} {req.url}")
                print(f"  Authorization: {auth_header[:120]}...")
    
    page.on("request", on_req)
    
    # Navigate to ChatShare main page
    print("Navigating to ChatShare...")
    page.goto("https://node2.chatshare.biz/share-login", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(2000)
    
    # Check if we're logged in
    cookies_now = context.cookies()
    print(f"Cookies: {[c['name'] for c in cookies_now]}")
    
    # Try navigating to the home page (where model selection happens)
    page.goto("https://node2.chatshare.biz/share-login/home", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(2000)
    
    page.screenshot(path="/tmp/chatshare_home.png")
    print("Screenshot: /tmp/chatshare_home.png")
    
    # Check page content
    title = page.title()
    print(f"Page title: {title}")
    
    # Look for any sass-node2 related elements or links
    links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a')).map(a => ({
            href: a.href, text: a.textContent.trim().substring(0, 50)
        })).filter(a => a.href.includes('sass') || a.text.includes('Deepseek') || a.text.includes('Grok') || a.text.includes('Codex'));
    }""")
    print(f"Sass-related links: {json.dumps(links, indent=2)}")
    
    # Check localStorage for any tokens
    ls = page.evaluate("""() => {
        const items = {};
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            const val = localStorage.getItem(key);
            if (val && val.length > 20) items[key] = val.substring(0, 200);
        }
        return items;
    }""")
    print(f"localStorage: {json.dumps(ls, indent=2)}")
    
    # Now try to directly visit sass-node2 with the token cookie
    context.add_cookies([{
        "name": "token",
        "value": chatshare_token,
        "domain": "sass-node2.chatshare.biz",
        "path": "/",
    }])
    
    print("\nNavigating to sass-node2...")
    page.goto("https://sass-node2.chatshare.biz", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)
    
    page.screenshot(path="/tmp/sass_node2.png")
    
    # Check all cookies now
    all_cookies = context.cookies()
    print(f"\nAll cookies after sass-node2 visit:")
    for c in all_cookies:
        val = str(c["value"])
        if len(val) > 50:
            # Check if it's a JWT
            if val.startswith("eyJ"):
                try:
                    header = val.split(".")[0]
                    header += "=" * (4 - len(header) % 4)
                    h = json.loads(base64.urlsafe_b64decode(header))
                    print(f"  {c['name']} ({c['domain']}): JWT alg={h.get('alg')} → {val[:80]}...")
                except:
                    print(f"  {c['name']} ({c['domain']}): {val[:80]}...")
            else:
                print(f"  {c['name']} ({c['domain']}): {val[:80]}...")
    
    # Check localStorage on sass-node2
    ls2 = page.evaluate("""() => {
        const items = {};
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            const val = localStorage.getItem(key);
            items[key] = val ? val.substring(0, 300) : null;
        }
        return items;
    }""")
    print(f"\nsass-node2 localStorage:")
    for k, v in ls2.items():
        print(f"  {k}: {v}")
    
    # Print all captured sass requests
    print(f"\nCaptured {len(sass_requests)} sass/backend-api requests:")
    for r in sass_requests:
        print(f"  {r['method']} {r['url']}")
        if r["headers"].get("authorization"):
            print(f"    Auth: {r['headers']['authorization'][:150]}")
    
    browser.close()
