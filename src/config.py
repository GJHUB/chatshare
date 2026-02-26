import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# 环境变量
CHATSHARE_URL = os.getenv("CHATSHARE_URL", "https://node2.chatshare.biz")
CHATSHARE_USERNAME = os.getenv("CHATSHARE_USERNAME", "")
CHATSHARE_PASSWORD = os.getenv("CHATSHARE_PASSWORD", "")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8100"))
PROXY_HOST = os.getenv("PROXY_HOST", "0.0.0.0")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

# AES 加密密钥
AES_KEY = bytes.fromhex("0a1b2c3d4e5f6071829aabbccddee123")

# 加载 config.yaml
_config_path = BASE_DIR / "config.yaml"
if _config_path.exists():
    with open(_config_path, "r") as f:
        FILE_CONFIG = yaml.safe_load(f) or {}
else:
    FILE_CONFIG = {}

API_KEYS = {item["key"]: item for item in FILE_CONFIG.get("api_keys", [])}
DISPATCHER_CONFIG = FILE_CONFIG.get("dispatcher", {})
GLOBAL_RATE_LIMIT = FILE_CONFIG.get("global_rate_limit", 200)
