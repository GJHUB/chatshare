"""Try entering cars through ChatShare web UI to capture sass-node2 auth flow.
The ChatShare frontend likely does: enter_car → redirect URL with auth → sass-node2 sets JWT."""
import asyncio, sys, os, json, base64, re
sys.path.insert(0, os.path.dirname(__file__))
from src.auth import ChatShareAuth
from playwright.sync_api import sync_playwright

async def login_and_get_token():
    auth = ChatShareAuth()
    await auth.login()
    token = auth.token
    await auth.close()
    return token

chatshare_token = asyncio.run(login_and_get_token())

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(ignore_https_errors=True)
    
    # Set token for all ChatShare domains
    for domain in ["node2.chatshare.biz", "sass-node2.chatshare.biz", "gpt-node2.chatshare.biz"]:
        context.add_cookies([{
            "name": "token", "value": chatshare_token,
            "domain": domain, "path": "/",
        }])
    
    page = context.new_page()
    
    # Capture ALL network requests
    all_reqs = []
    def on_req(req):
        entry = {"url": req.url, "method": req.method, "headers": dict(req.headers)}
        all_reqs.append(entry)
    
    all_resps = []
    def on_resp(resp):
        entry = {"url": resp.url, "status": resp.status, "headers": dict(resp.headers)}
        all_resps.append(entry)
    
    page.on("request", on_req)
    page.on("response", on_resp)
    
    # Go to ChatShare home
    print("=== Loading ChatShare home ===")
    page.goto("https://node2.chatshare.biz/share-login/home", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    
    # Look for channel/car selection UI
    page_text = page.evaluate("() => document.body.innerText.substring(0, 3000)")
    print(f"Page text preview:\n{page_text[:500]}")
    
    # Find buttons/links for different channels
    buttons = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('button, a, [role="button"], .channel-item, .car-item, [class*="channel"], [class*="car"]'))
            .map(el => ({
                tag: el.tagName,
                text: el.textContent.trim().substring(0, 80),
                href: el.href || '',
                class: el.className.substring(0, 100),
                onclick: el.getAttribute('onclick') || '',
            }))
            .filter(el => el.text.length > 0 && el.text.length < 100);
    }""")
    print(f"\nButtons/links ({len(buttons)}):")
    for b in buttons[:30]:
        if any(kw in b["text"].lower() for kw in ["claude", "gemini", "grok", "deep", "codex", "sass", "gpt", "进入", "channel"]):
            print(f"  [{b['tag']}] {b['text']} class={b['class'][:50]}")
    
    # Take screenshot
    page.screenshot(path="/tmp/chatshare_home2.png", full_page=True)
    print("\nScreenshot: /tmp/chatshare_home2.png")
    
    # Try clicking on a sass-related channel if visible
    # First, let's see the page structure
    html_snippet = page.evaluate("() => document.body.innerHTML.substring(0, 5000)")
    
    # Look for channel tabs or navigation
    channels_found = re.findall(r'channel["\s:=]+["\']?(\w+)', html_snippet, re.IGNORECASE)
    print(f"\nChannels in HTML: {channels_found[:10]}")
    
    # Check if there's an iframe
    iframes = page.evaluate("() => Array.from(document.querySelectorAll('iframe')).map(f => ({src: f.src, name: f.name}))")
    print(f"Iframes: {iframes}")
    
    # Now let's try the direct approach: use the ChatShare API to enter a car
    # and follow the redirect in the browser
    print("\n=== Trying to enter sass-node2 via API in browser ===")
    
    # Use page.evaluate to call the enter API
    result = page.evaluate("""async (token) => {
        // First get car list for different channels
        const channels = ['gemini', 'claude', 'xy'];
        const results = {};
        for (const ch of channels) {
            try {
                const resp = await fetch('/share-login/v1/user/home/carpage?channel=' + ch + '&page=1&size=5', {
                    headers: {'Cookie': 'token=' + token}
                });
                const data = await resp.json();
                const cars = (data.respData || data.data || {}).list || [];
                results[ch] = cars.length;
            } catch(e) {
                results[ch] = 'error: ' + e.message;
            }
        }
        return results;
    }""", chatshare_token)
    print(f"Cars per channel: {result}")
    
    # Now enter a gemini car and navigate to it
    print("\n=== Entering gemini car via browser ===")
    enter_result = page.evaluate("""async (token) => {
        const resp = await fetch('/share-login/v1/user/home/carpage?channel=gemini&page=1&size=5', {
            headers: {'Cookie': 'token=' + token}
        });
        const data = await resp.json();
        const cars = (data.respData || data.data || {}).list || [];
        if (!cars.length) return {error: 'no cars'};
        
        const car = cars[0];
        const ts = Math.floor(Date.now()/1000).toString();
        
        // MD5 for sign - use SubtleCrypto
        const raw = car.carid + ts;
        const encoder = new TextEncoder();
        const hashBuffer = await crypto.subtle.digest('MD5', encoder.encode(raw)).catch(() => null);
        
        // Fallback: just send without sign for now
        const enterResp = await fetch('/share-login/v1/user/home/enter', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Cookie': 'token=' + token},
            body: JSON.stringify({channel: 'gemini', car_id: car.carid, timestamp: ts, sign: ''})
        });
        const enterData = await enterResp.json();
        return {
            car: car.carid,
            respData: enterData.respData || enterData.data,
            cookies: document.cookie,
        };
    }""", chatshare_token)
    print(f"Enter result: {json.dumps(enter_result, indent=2)[:500]}")
    
    # If we got a URL, navigate to it
    url = enter_result.get("respData", "")
    if isinstance(url, str) and url.startswith("http"):
        print(f"\nNavigating to: {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        
        # Check cookies and localStorage
        all_cookies = context.cookies()
        print(f"\nCookies after navigation:")
        for c in all_cookies:
            val = str(c["value"])
            if len(val) > 30:
                if val.startswith("eyJ"):
                    try:
                        h = json.loads(base64.urlsafe_b64decode(val.split(".")[0] + "=="))
                        print(f"  {c['name']} ({c['domain']}): JWT alg={h.get('alg')} client_id={h.get('client_id','')} → {val[:80]}...")
                    except:
                        print(f"  {c['name']} ({c['domain']}): {val[:80]}...")
                else:
                    print(f"  {c['name']} ({c['domain']}): {val[:80]}...")
        
        ls = page.evaluate("""() => {
            const items = {};
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                items[key] = (localStorage.getItem(key) || '').substring(0, 300);
            }
            return items;
        }""")
        if ls:
            print(f"\nlocalStorage:")
            for k, v in ls.items():
                print(f"  {k}: {v}")
    
    # Print interesting requests
    print(f"\n=== Interesting requests ===")
    for r in all_reqs:
        url = r["url"]
        if any(x in url for x in [".js", ".css", ".png", ".jpg", ".svg", ".woff", ".ico"]):
            continue
        auth_h = r["headers"].get("authorization", "")
        if auth_h or "sass" in url or "backend-api" in url or "token" in url.lower():
            print(f"  {r['method']} {url}")
            if auth_h:
                print(f"    Authorization: {auth_h[:150]}")
    
    browser.close()
