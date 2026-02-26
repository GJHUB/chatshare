"""Test gemini-node2 conversation API format"""
import asyncio, sys, os, json, uuid
sys.path.insert(0, os.path.dirname(__file__))
from src.auth import ChatShareAuth
import httpx

async def test():
    auth = ChatShareAuth()
    await auth.login()
    
    cars = await auth.get_car_page("gemini")
    avail = [c for c in cars if c.get("available", True)]
    result = await auth.enter_car("gemini", avail[0]["carid"])
    chat_url = result["chat_url"].rstrip("/")
    cookies = result["cookies"]
    base_url = chat_url.rsplit("/app", 1)[0] if "/app" in chat_url else chat_url
    
    print(f"base_url: {base_url}")
    print(f"cookies: {list(cookies.keys())}")
    
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers_base = {
        "Cookie": cookie_str,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    
    # Also try with Bearer token
    headers_bearer = dict(headers_base)
    headers_bearer["Authorization"] = f"Bearer {auth.token}"
    headers_bearer["oai-device-id"] = cookies.get("gfsessionid", str(uuid.uuid4()))
    headers_bearer["oai-language"] = "zh-CN"
    
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        # Try different API paths
        paths_to_try = [
            "/backend-api/conversation",
            "/backend-api/f/conversation",
        ]
        
        msg_body_gpt = {
            "action": "next",
            "messages": [{"id": str(uuid.uuid4()), "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["say ok"]}}],
            "model": "gemini-2.0-flash",
            "parent_message_id": str(uuid.uuid4()),
            "stream": True,
        }
        
        msg_body_sass = {
            "action": "next",
            "messages": [{"id": str(uuid.uuid4()), "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["say ok"]}}],
            "parent_message_id": "client-created-root",
            "model": "Gemini-3.1-Flash",
            "timezone_offset_min": -480,
            "timezone": "Asia/Shanghai",
            "conversation_mode": {"kind": "primary_assistant"},
            "supports_buffering": True,
            "supported_encodings": ["v1"],
        }
        
        for path in paths_to_try:
            for body_name, body in [("gpt-format", msg_body_gpt), ("sass-format", msg_body_sass)]:
                for hdr_name, hdrs in [("cookie-only", headers_base), ("bearer", headers_bearer)]:
                    url = f"{base_url}{path}"
                    try:
                        # Also try with sentinel header
                        h = dict(hdrs)
                        if "f/conversation" in path:
                            h["openai-sentinel-chat-requirements-token"] = "Fuck_You"
                        
                        async with client.stream("POST", url, json=body, headers=h, timeout=15) as resp:
                            print(f"\n{path} | {body_name} | {hdr_name} → {resp.status_code}")
                            if resp.status_code == 200:
                                text = ""
                                count = 0
                                async for line in resp.aiter_lines():
                                    line = line.strip()
                                    if not line:
                                        continue
                                    count += 1
                                    if count <= 3:
                                        print(f"  {line[:200]}")
                                    if line.startswith("data: ") and line[6:] != "[DONE]":
                                        try:
                                            obj = json.loads(line[6:])
                                            v = obj.get("v")
                                            if isinstance(v, dict):
                                                msg = v.get("message", {})
                                                parts = msg.get("content", {}).get("parts", [])
                                                if parts and isinstance(parts[0], str):
                                                    text = parts[0]
                                            elif isinstance(v, list):
                                                for pp in v:
                                                    if isinstance(pp, dict) and pp.get("o") == "append" and isinstance(pp.get("v"), str):
                                                        text += pp["v"]
                                            elif isinstance(v, str):
                                                text += v
                                        except:
                                            pass
                                print(f"  Lines: {count}, Text: {text[:200]}")
                                if text:
                                    print("  *** SUCCESS ***")
                                    await auth.close()
                                    return
                            else:
                                body_text = await resp.aread()
                                print(f"  Error: {body_text.decode()[:200]}")
                    except Exception as e:
                        print(f"\n{path} | {body_name} | {hdr_name} → ERROR: {str(e)[:100]}")
    
    await auth.close()

asyncio.run(test())
