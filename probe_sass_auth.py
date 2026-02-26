import asyncio, httpx, re, base64, json
from src.auth import ChatShareAuth

SASS_NODE2_URL = "https://sass-node2.chatshare.biz"

async def check():
    auth = ChatShareAuth()
    await auth.ensure_token()
    
    # Enter gemini car
    cars = await auth.get_car_page("gemini")
    avail = [c for c in cars if c.get("available", True)]
    result = await auth.enter_car("gemini", avail[0]["carid"])
    chat_url = result["chat_url"]
    cookies = result["cookies"]
    
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    
    async with httpx.AsyncClient(verify=False, timeout=30, follow_redirects=True) as client:
        r = await client.get(chat_url, headers={"Cookie": cookie_str})
        body = r.text
        
        # Find all JWTs
        jwts = re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", body)
        print(f"JWTs found in gemini page: {len(jwts)}")
        seen = set()
        for t in jwts:
            if t in seen:
                continue
            seen.add(t)
            header = t.split(".")[0]
            header += "=" * (4 - len(header) % 4)
            try:
                h = json.loads(base64.urlsafe_b64decode(header))
                print(f"  alg={h.get('alg')} → {t[:80]}...")
            except:
                print(f"  (decode fail) → {t[:80]}...")
        
        # Check for accessToken patterns
        patterns = [
            r'accessToken["\']\s*:\s*["\']([^"\']+)',
            r'"accessToken"\s*:\s*"([^"]+)"',
            r"token\s*=\s*['\"]([^'\"]+)['\"]",
        ]
        for pat in patterns:
            matches = re.findall(pat, body)
            if matches:
                print(f"Pattern match: {matches[0][:80]}")
    
    # Now try: use the gemini gfsessionid + token for sass-node2
    print("\n--- Testing sass-node2 with gemini cookies ---")
    headers = {
        "Authorization": f"Bearer {cookies['token']}",
        "Cookie": cookie_str,
        "Content-Type": "application/json",
        "oai-device-id": cookies.get("gfsessionid", "test"),
        "oai-language": "zh-CN",
    }
    
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        # Try sass-node2 conversation with gemini cookies
        import uuid
        
        # prepare
        prep_body = {
            "action": "next", "fork_from_shared_post": False,
            "parent_message_id": "client-created-root",
            "model": "Gemini-3.1-Flash",
            "timezone_offset_min": -480, "timezone": "Asia/Shanghai",
            "conversation_mode": {"kind": "primary_assistant"},
            "system_hints": [], "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": {"app_name": "chatgpt.com"},
        }
        r = await client.post(f"{SASS_NODE2_URL}/backend-api/f/conversation/prepare", json=prep_body, headers=headers)
        print(f"prepare: {r.status_code} {r.text[:100]}")
        
        # sentinel
        sent_body = {
            "prepare_token": "You_Find_Me_Ha_Ha_Ha_Created_By_Nexus",
            "turnstile": "MDogU3ludGF4RXJyb3I6IEV4cGVjdGVkICcsJyBvciAnXScgYWZ0ZXIgYXJyYXkgZWxlbWVudCBpbiBKU09OIGF0IHBvc2l0aW9uIDE3IChsaW5lIDEgY29sdW1uIDE4KQ==",
        }
        r = await client.post(f"{SASS_NODE2_URL}/backend-api/sentinel/chat-requirements/finalize", json=sent_body, headers=headers)
        print(f"sentinel: {r.status_code}")
        
        # conversation
        conv_headers = dict(headers)
        conv_headers["openai-sentinel-chat-requirements-token"] = "Fuck_You"
        conv_body = {
            "action": "next",
            "messages": [{"id": str(uuid.uuid4()), "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hi, 一句话回答你是谁"]}}],
            "parent_message_id": "client-created-root",
            "model": "Gemini-3.1-Flash",
            "timezone_offset_min": -480, "timezone": "Asia/Shanghai",
            "conversation_mode": {"kind": "primary_assistant"},
            "supports_buffering": True, "supported_encodings": ["v1"],
        }
        
        async with client.stream("POST", f"{SASS_NODE2_URL}/backend-api/f/conversation", json=conv_body, headers=conv_headers, timeout=60) as resp:
            print(f"conversation: {resp.status_code}")
            if resp.status_code != 200:
                body = await resp.aread()
                print(f"error: {body.decode()[:300]}")
            else:
                text = ""
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    d = line[6:]
                    if d == "[DONE]":
                        print("[DONE]")
                        break
                    try:
                        obj = json.loads(d)
                        v = obj.get("v")
                        if isinstance(v, str):
                            text += v
                        elif isinstance(v, dict):
                            msg = v.get("message", {})
                            parts = msg.get("content", {}).get("parts", [])
                            if parts and isinstance(parts[0], str):
                                text = parts[0]
                        elif isinstance(v, list):
                            for p in v:
                                if isinstance(p, dict) and p.get("o") == "append" and isinstance(p.get("v"), str):
                                    text += p["v"]
                    except:
                        pass
                print(f"Response: {text[:300]}")
    
    await auth.close()

asyncio.run(check())
