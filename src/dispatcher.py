import time
import logging
import asyncio
from dataclasses import dataclass, field

import httpx

from .auth import ChatShareAuth
from .config import DISPATCHER_CONFIG

logger = logging.getLogger(__name__)

SASS_NODE2_URL = "https://sass-node2.chatshare.biz"

# sass-node2 固定的认证参数
SASS_PREPARE_TOKEN = "You_Find_Me_Ha_Ha_Ha_Created_By_Nexus"
SASS_TURNSTILE = "MDogU3ludGF4RXJyb3I6IEV4cGVjdGVkICcsJyBvciAnXScgYWZ0ZXIgYXJyYXkgZWxlbWVudCBpbiBKU09OIGF0IHBvc2l0aW9uIDE3IChsaW5lIDEgY29sdW1uIDE4KQ=="
SASS_SENTINEL_TOKEN = "Fuck_You"


@dataclass
class CarSession:
    """gpt-node2 车辆会话"""
    channel: str
    car_id: str
    chat_url: str
    token: str
    cookies: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    is_busy: bool = False
    node_type: str = "gpt"
    _client: httpx.AsyncClient = field(default=None, repr=False)

    def __post_init__(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120, verify=False)

    def get_headers(self) -> dict:
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return {
            "Cookie": cookie_str,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    def get_conversation_url(self) -> str:
        # 提取 base URL（去掉路径后缀如 /app）
        from urllib.parse import urlparse
        parsed = urlparse(self.chat_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        # 非 gpt 节点（claude/gemini/grok/deepseek）走 /backend-api/f/conversation
        if self.node_type != "gpt":
            return f"{base_url}/backend-api/f/conversation"
        return f"{base_url}/backend-api/conversation"

    async def close(self):
        if self._client:
            await self._client.aclose()


@dataclass
class GeminiSession:
    """gemini-node2 会话 — 使用 /v1/chat/completions (OpenAI 兼容格式)"""
    channel: str = "gemini"
    car_id: str = ""
    chat_url: str = ""
    cookies: dict = field(default_factory=dict)
    access_token: str = ""
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    is_busy: bool = False
    node_type: str = "gemini"
    _client: httpx.AsyncClient = field(default=None, repr=False)

    def __post_init__(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120, verify=False, follow_redirects=False)

    @property
    def base_url(self) -> str:
        url = self.chat_url.rstrip("/")
        return url.rsplit("/app", 1)[0] if "/app" in url else url

    def get_headers(self) -> dict:
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        h = {
            "Cookie": cookie_str,
            "Content-Type": "application/json",
        }
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    def get_conversation_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    async def refresh_token(self) -> bool:
        """尝试通过 /auth/refresh 获取有效的 access token"""
        gfs = self.cookies.get("gfsessionid", "")
        if not gfs:
            return False
        try:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            resp = await self._client.post(
                f"{self.base_url}/auth/refresh",
                json={"refresh_token": gfs},
                headers={"Cookie": cookie_str, "Content-Type": "application/json"},
                timeout=8,
                follow_redirects=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token") or data.get("token") or data.get("data", {}).get("token", "")
                if token:
                    self.access_token = token
                    logger.info(f"Gemini refresh_token success for car {self.car_id}")
                    return True
            logger.warning(f"Gemini refresh_token failed: {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"Gemini refresh_token error: {e}")
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()


@dataclass
class ClaudeSession:
    """claude-node2 会话（Claude.ai 原生 API）"""
    channel: str
    car_id: str
    chat_url: str
    cookies: dict = field(default_factory=dict)
    org_uuid: str = ""
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    is_busy: bool = False
    node_type: str = "claude"
    _client: httpx.AsyncClient = field(default=None, repr=False)

    def __post_init__(self):
        if self._client is None:
            jar = httpx.Cookies()
            for k, v in self.cookies.items():
                jar.set(k, v)
            self._client = httpx.AsyncClient(timeout=120, verify=False, cookies=jar)

    def get_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    async def init_org(self):
        """从 /api/bootstrap 获取 org_uuid（先访问 /new 激活 session）"""
        # 访问 /new 激活 Claude session（会设置 anthropic-consent-preferences cookie）
        await self._client.get(f"{self.chat_url}/new", follow_redirects=True)
        # 再获取 bootstrap
        resp = await self._client.get(f"{self.chat_url}/api/bootstrap")
        resp.raise_for_status()
        data = resp.json() or {}
        account = data.get("account")
        if not account:
            raise ValueError("Claude bootstrap returned account=null")
        memberships = account.get("memberships", [])
        if memberships:
            self.org_uuid = memberships[0]["organization"]["uuid"]
            logger.info(f"Claude org_uuid: {self.org_uuid}")
        else:
            raise ValueError("No organization found in Claude bootstrap")

    def get_create_conv_url(self) -> str:
        return f"{self.chat_url}/api/organizations/{self.org_uuid}/chat_conversations"

    def get_completion_url(self, conv_uuid: str) -> str:
        return f"{self.chat_url}/api/organizations/{self.org_uuid}/chat_conversations/{conv_uuid}/completion"

    async def close(self):
        if self._client:
            await self._client.aclose()


@dataclass
class SassSession:
    """sass-node2 会话"""
    bearer_token: str
    cookies: dict = field(default_factory=dict)
    device_id: str = "35bbdd4c-b2f2-4f3f-bfe8-491b59a63130"
    sass_url: str = SASS_NODE2_URL
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    is_busy: bool = False
    node_type: str = "sass"
    _client: httpx.AsyncClient = field(default=None, repr=False)

    def __post_init__(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120, verify=False)

    def get_headers(self) -> dict:
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "Cookie": cookie_str,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "oai-device-id": self.device_id,
            "oai-language": "zh-CN",
        }

    async def get_sentinel_token(self) -> str:
        """直接获取 sentinel chat-requirements token"""
        url = f"{self.sass_url}/backend-api/sentinel/chat-requirements"
        try:
            resp = await self._client.post(url, json={}, headers=self.get_headers())
            if resp.status_code == 200:
                token = resp.json().get("token", "")
                logger.info(f"sass sentinel token: {token[:30]}...")
                return token
            logger.warning(f"sass get_sentinel_token status: {resp.status_code}")
        except Exception as e:
            logger.error(f"sass get_sentinel_token failed: {e}")
        return ""

    def get_conversation_headers(self, sentinel_token: str = "") -> dict:
        """对话请求需要额外的 sentinel token header"""
        headers = self.get_headers()
        headers["openai-sentinel-chat-requirements-token"] = sentinel_token or SASS_SENTINEL_TOKEN
        return headers

    def get_conversation_url(self) -> str:
        return f"{self.sass_url}/backend-api/f/conversation"

    async def prepare(self, model: str) -> bool:
        """Step 1: Prepare"""
        url = f"{self.sass_url}/backend-api/f/conversation/prepare"
        body = {
            "action": "next",
            "fork_from_shared_post": False,
            "parent_message_id": "client-created-root",
            "model": model,
            "timezone_offset_min": -480,
            "timezone": "Asia/Shanghai",
            "conversation_mode": {"kind": "primary_assistant"},
            "system_hints": [],
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": {"app_name": "chatgpt.com"},
        }
        try:
            resp = await self._client.post(url, json=body, headers=self.get_headers())
            data = resp.json()
            logger.info(f"sass prepare: {data}")
            return data.get("status") == "ok"
        except Exception as e:
            logger.error(f"sass prepare failed: {e}")
            return False

    async def sentinel_finalize(self) -> bool:
        """Step 2: Sentinel Finalize"""
        url = f"{self.sass_url}/backend-api/sentinel/chat-requirements/finalize"
        body = {
            "prepare_token": SASS_PREPARE_TOKEN,
            "turnstile": SASS_TURNSTILE,
        }
        try:
            resp = await self._client.post(url, json=body, headers=self.get_headers())
            data = resp.json()
            token = data.get("token", "")
            logger.info(f"sass sentinel finalize: token={token}")
            return bool(token)
        except Exception as e:
            logger.error(f"sass sentinel finalize failed: {e}")
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()


class NoCarAvailableError(Exception):
    pass


class CarDispatcher:
    def __init__(self, auth: ChatShareAuth):
        self.auth = auth
        self.car_sessions: dict[str, dict[str, CarSession]] = {}
        self.claude_sessions: list[ClaudeSession] = []
        self.sass_sessions: list[SassSession] = []
        self.gemini_sessions: list[GeminiSession] = []
        self._lock = asyncio.Lock()
        self.max_sessions = DISPATCHER_CONFIG.get("max_sessions_per_channel", 5)
        self.session_timeout = DISPATCHER_CONFIG.get("session_timeout", 300)

    # --- gpt-node2 车辆管理 ---

    async def get_available_cars(self, channel: str) -> list[dict]:
        # node_type → ChatShare channel 映射
        api_channel = {"gpt": "xy", "sass": "sass"}.get(channel, channel)
        cars = await self.auth.get_car_page(api_channel)
        available = [c for c in cars if c.get("available", True)]
        available.sort(key=lambda c: c.get("count", 999))
        return available

    async def _enter_car(self, channel: str, car_id: str) -> CarSession:
        api_channel = {"gpt": "xy", "sass": "sass"}.get(channel, channel)
        enter_data = await self.auth.enter_car(api_channel, car_id)
        chat_url = enter_data["chat_url"].rstrip("/")
        cookies = enter_data["cookies"]
        if not chat_url:
            raise NoCarAvailableError(f"No chat_url returned for car {car_id}")

        session = CarSession(
            channel=channel,
            car_id=car_id,
            chat_url=chat_url,
            token=self.auth.token,
            cookies=cookies,
            node_type=channel,
        )
        if channel not in self.car_sessions:
            self.car_sessions[channel] = {}
        self.car_sessions[channel][car_id] = session
        logger.info(f"Entered car {car_id} on {channel}, url={chat_url}")
        return session

    async def select_car(self, channel: str) -> CarSession:
        async with self._lock:
            if channel in self.car_sessions:
                for car_id, session in self.car_sessions[channel].items():
                    if not session.is_busy:
                        session.last_used = time.time()
                        return session

            cars = await self.get_available_cars(channel)
            if not cars:
                channel_names = {"gpt": "GPT", "grok": "Grok", "deepseek": "Deepseek", "gemini": "Gemini"}
                name = channel_names.get(channel, channel)
                raise NoCarAvailableError(f"{name} 暂无可用车辆")

            best_car = cars[0]
            return await self._enter_car(channel, best_car["carid"])

    # --- claude-node2 会话管理 ---

    async def get_claude_session(self) -> ClaudeSession:
        """获取一个全新的 claude-node2 会话（free 账号容易被踢，不复用）"""
        async with self._lock:
            return await self._create_claude_session()

    async def _create_claude_session(self) -> ClaudeSession:
        """通过进车获取 claude-node2 的认证信息，自动跳过无效车辆"""
        try:
            cars = await self.get_available_cars("claude")
            if not cars:
                raise NoCarAvailableError("No available claude car")

            # 尝试多辆车，跳过 account=null 的
            for car in cars[:10]:
                try:
                    enter_data = await self.auth.enter_car("claude", car["carid"])
                    chat_url = enter_data["chat_url"].rstrip("/")
                    cookies = enter_data["cookies"]

                    session = ClaudeSession(
                        channel="claude",
                        car_id=car["carid"],
                        chat_url=chat_url,
                        cookies=cookies,
                    )
                    await session.init_org()
                    self.claude_sessions.append(session)
                    logger.info(f"Created claude session via car {car['carid']}, org={session.org_uuid}")
                    return session
                except ValueError as e:
                    logger.warning(f"Claude car {car['carid']} unusable: {e}, trying next")
                    continue

            raise NoCarAvailableError("All claude cars returned account=null")
        except NoCarAvailableError:
            raise
        except Exception as e:
            logger.error(f"Failed to create claude session: {e}")
            raise NoCarAvailableError(f"Failed to create claude session: {e}")

    # --- sass-node2 会话管理 ---

    async def get_sass_session(self) -> SassSession:
        """获取一个可用的 sass-node2 会话"""
        async with self._lock:
            # 复用空闲会话
            for session in self.sass_sessions:
                if not session.is_busy:
                    session.last_used = time.time()
                    return session

            # 创建新会话（从 enter_car 获取认证信息）
            return await self._create_sass_session()

    async def _create_sass_session(self) -> SassSession:
        """通过 soruxgpt 进车获取 sass-node2 的认证信息，失败则 fallback 到 fakeoai (sass2-node2)"""
        entries = [
            ("soruxgpt", "soruxgpt", SASS_NODE2_URL),
            ("fakeoai", "fakeoai", "https://sass2-node2.chatshare.biz"),
        ]
        last_error = ""
        for channel, car_id, sass_url in entries:
            try:
                enter_data = await self.auth.enter_car(channel, car_id)
                cookies = enter_data["cookies"]
                bearer_token = self.auth.token

                session = SassSession(
                    bearer_token=bearer_token,
                    cookies=cookies,
                    sass_url=sass_url,
                )
                # 快速验证 sentinel 是否可用
                sentinel = await session.get_sentinel_token()
                if not sentinel or sentinel == SASS_SENTINEL_TOKEN:
                    logger.warning(f"sass session via {channel} sentinel failed, trying next")
                    await session.close()
                    continue

                self.sass_sessions.append(session)
                logger.info(f"Created new sass session via {channel} channel ({sass_url})")
                return session
            except Exception as e:
                last_error = str(e)
                logger.warning(f"sass session via {channel} failed: {e}")
                continue

        raise NoCarAvailableError(f"Failed to create sass session: {last_error}")

    async def prepare_sass_conversation(self, session: SassSession, model: str) -> bool:
        """执行 sass-node2 的 prepare + sentinel 两步"""
        ok = await session.prepare(model)
        if not ok:
            logger.warning("sass prepare failed")
            return False
        ok = await session.sentinel_finalize()
        if not ok:
            logger.warning("sass sentinel finalize failed")
            return False
        return True

    # --- gemini-node2 会话管理 ---

    async def get_gemini_session(self) -> GeminiSession:
        """获取一个可用的 gemini-node2 会话"""
        async with self._lock:
            for session in self.gemini_sessions:
                if not session.is_busy:
                    session.last_used = time.time()
                    return session
            return await self._create_gemini_session()

    async def _create_gemini_session(self) -> GeminiSession:
        """通过进车获取 gemini-node2 的认证信息，尝试 refresh 获取 access token"""
        try:
            cars = await self.get_available_cars("gemini")
            if not cars:
                raise NoCarAvailableError("Gemini 暂无可用车辆")

            last_error = ""
            for car in cars[:10]:
                try:
                    enter_data = await self.auth.enter_car("gemini", car["carid"])
                    chat_url = enter_data["chat_url"].rstrip("/")
                    cookies = enter_data["cookies"]

                    session = GeminiSession(
                        car_id=car["carid"],
                        chat_url=chat_url,
                        cookies=cookies,
                    )
                    # 尝试 refresh 获取 access token
                    ok = await session.refresh_token()
                    if ok:
                        self.gemini_sessions.append(session)
                        logger.info(f"Created gemini session via car {car['carid']}")
                        return session
                    else:
                        # refresh 失败，尝试用 gfsessionid 直接作为 token
                        gfs = cookies.get("gfsessionid", "")
                        if gfs:
                            session.access_token = gfs
                            # 快速验证: 发一个小请求看是否能用
                            try:
                                test_resp = await session._client.post(
                                    session.get_conversation_url(),
                                    json={"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "hi"}], "stream": False},
                                    headers=session.get_headers(),
                                    timeout=8,
                                    follow_redirects=False,
                                )
                                if test_resp.status_code == 200:
                                    self.gemini_sessions.append(session)
                                    logger.info(f"Created gemini session via car {car['carid']} (gfsessionid as token)")
                                    return session
                                else:
                                    last_error = f"status={test_resp.status_code}"
                            except Exception as e:
                                last_error = str(e)
                        logger.warning(f"Gemini car {car['carid']} refresh failed, trying next")
                        await session.close()
                        continue
                except Exception as e:
                    logger.warning(f"Gemini car {car['carid']} unusable: {e}")
                    last_error = str(e)
                    continue

            raise NoCarAvailableError(f"Gemini 所有车辆的会话均已过期，暂时无法使用")
        except NoCarAvailableError:
            raise
        except Exception as e:
            logger.error(f"Failed to create gemini session: {e}")
            raise NoCarAvailableError(f"Gemini 会话创建失败: {e}")

    # --- 通用 ---

    def release_car(self, session):
        """释放会话"""
        session.is_busy = False
        session.last_used = time.time()

    async def cleanup_stale(self):
        now = time.time()
        # 清理 gpt sessions
        for channel in list(self.car_sessions.keys()):
            for car_id in list(self.car_sessions[channel].keys()):
                session = self.car_sessions[channel][car_id]
                if now - session.last_used > self.session_timeout and not session.is_busy:
                    await session.close()
                    del self.car_sessions[channel][car_id]
                    logger.info(f"Cleaned up stale session: {channel}/{car_id}")
        # 清理 claude sessions
        self.claude_sessions = [
            s for s in self.claude_sessions
            if not (now - s.last_used > self.session_timeout and not s.is_busy)
        ]
        # 清理 sass sessions
        self.sass_sessions = [
            s for s in self.sass_sessions
            if not (now - s.last_used > self.session_timeout and not s.is_busy)
        ]
        # 清理 gemini sessions
        self.gemini_sessions = [
            s for s in self.gemini_sessions
            if not (now - s.last_used > self.session_timeout and not s.is_busy)
        ]

    def get_all_status(self) -> dict:
        result = {}
        for channel, sessions in self.car_sessions.items():
            result[channel] = [
                {
                    "car_id": s.car_id,
                    "chat_url": s.chat_url,
                    "is_busy": s.is_busy,
                    "last_used": s.last_used,
                    "age": time.time() - s.created_at,
                }
                for s in sessions.values()
            ]
        result["claude-node2"] = [
            {
                "car_id": s.car_id,
                "org_uuid": s.org_uuid,
                "is_busy": s.is_busy,
                "last_used": s.last_used,
                "age": time.time() - s.created_at,
            }
            for s in self.claude_sessions
        ]
        result["sass-node2"] = [
            {
                "is_busy": s.is_busy,
                "last_used": s.last_used,
                "age": time.time() - s.created_at,
            }
            for s in self.sass_sessions
        ]
        result["gemini-node2"] = [
            {
                "car_id": s.car_id,
                "is_busy": s.is_busy,
                "has_token": bool(s.access_token),
                "last_used": s.last_used,
                "age": time.time() - s.created_at,
            }
            for s in self.gemini_sessions
        ]
        return result
