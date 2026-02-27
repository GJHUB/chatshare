import time
import hashlib
import logging
from Crypto.Cipher import AES
import httpx

from .config import CHATSHARE_URL, CHATSHARE_USERNAME, CHATSHARE_PASSWORD

logger = logging.getLogger(__name__)

LOGIN_PATH = "/share-login/v1/user/auth/login"
CAR_PAGE_PATH = "/share-login/v1/user/home/carpage"
ENTER_CAR_PATH = "/share-login/v1/user/home/enter"


class ChatShareAuth:
    def __init__(self, username: str = None, password: str = None, base_url: str = None):
        self.username = username or CHATSHARE_USERNAME
        self.password = password or CHATSHARE_PASSWORD
        self.base_url = (base_url or CHATSHARE_URL).rstrip("/")
        self.token: str | None = None
        self.token_time: float = 0
        self.token_ttl: float = 3600 * 12  # 12小时刷新一次
        self._client = httpx.AsyncClient(timeout=30, verify=False)

    @staticmethod
    def encrypt_password(password: str) -> str:
        """AES-256-CFB128 加密密码，随机IV拼在密文前，base64输出"""
        import os, base64
        key = b'0a1b2c3d4e5f6071829aabbccddee123'  # 32 bytes AES-256
        iv = os.urandom(16)
        cipher = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128)
        encrypted = cipher.encrypt(password.encode())
        return base64.b64encode(iv + encrypted).decode()

    async def login(self) -> str:
        """登录 ChatShare，返回 token"""
        encrypted_pwd = self.encrypt_password(self.password)
        url = f"{self.base_url}{LOGIN_PATH}"
        timestamp = str(int(time.time()))
        payload = {
            "username": self.username,
            "password": encrypted_pwd,
            "timestamp": timestamp,
        }
        logger.info(f"Official API request: url={url} payload={payload}")
        resp = await self._client.post(url, json=payload)
        data = resp.json()
        logger.info(f"Official API response: url={url} status={resp.status_code} body={str(data)[:1200]}")
        resp.raise_for_status()

        # 从 cookie 或响应体获取 token
        token = resp.cookies.get("token")
        if not token:
            token = data.get("data", {}).get("token") or data.get("token")
        if not token:
            raise ValueError(f"Login failed, no token in response: {data}")

        self.token = token
        self.token_time = time.time()
        logger.info("ChatShare login success, token obtained")
        return token

    async def ensure_token(self) -> str:
        """确保 token 有效，过期则重新登录"""
        if not self.token or (time.time() - self.token_time > self.token_ttl):
            retry = 3
            for i in range(retry):
                try:
                    return await self.login()
                except Exception as e:
                    logger.warning(f"Login attempt {i+1}/{retry} failed: {e}")
                    if i == retry - 1:
                        raise
        return self.token

    def get_headers(self) -> dict:
        """返回带 token 的请求头"""
        return {
            "Cookie": f"token={self.token}",
            "Content-Type": "application/json",
        }

    async def _force_relogin(self) -> str:
        """强制重新登录（忽略 TTL，直接刷新 token）"""
        self.token = None
        self.token_time = 0
        return await self.ensure_token()

    async def get_car_page(self, channel: str, page: int = 1, size: int = 50) -> list[dict]:
        """获取车辆列表，401 时自动重新登录重试"""
        await self.ensure_token()
        url = f"{self.base_url}{CAR_PAGE_PATH}"
        params = {"channel": channel, "page": page, "size": size}
        resp = await self._client.get(url, params=params, headers=self.get_headers())
        if resp.status_code == 401:
            logger.warning("get_car_page got 401, forcing re-login")
            await self._force_relogin()
            resp = await self._client.get(url, params=params, headers=self.get_headers())
        resp.raise_for_status()
        data = resp.json()
        resp_data = data.get("respData") or data.get("data") or {}
        if resp_data is None:
            resp_data = {}
        return resp_data.get("list", []) if isinstance(resp_data, dict) else []

    async def enter_car(self, channel: str, car_id: str) -> dict:
        """进入车辆，返回 {chat_url, cookies}，401 时自动重新登录重试"""
        await self.ensure_token()
        url = f"{self.base_url}{ENTER_CAR_PATH}"

        def _build_payload():
            timestamp = str(int(time.time()))
            raw = f"{car_id}{timestamp}"
            sign = hashlib.md5(raw.encode()).hexdigest()
            return {
                "channel": channel,
                "car_id": car_id,
                "timestamp": timestamp,
                "sign": sign,
            }

        resp = await self._client.post(url, json=_build_payload(), headers=self.get_headers())
        if resp.status_code == 401:
            logger.warning("enter_car got 401, forcing re-login")
            await self._force_relogin()
            resp = await self._client.post(url, json=_build_payload(), headers=self.get_headers())
        resp.raise_for_status()
        data = resp.json()
        resp_data = data.get("respData") or data.get("data") or ""
        chat_url = resp_data if isinstance(resp_data, str) else resp_data.get("url", "")
        cookies = dict(resp.cookies)
        cookies["token"] = self.token
        return {"chat_url": chat_url, "cookies": cookies}

    async def close(self):
        await self._client.aclose()
