import time
import logging
from collections import defaultdict

from .config import API_KEYS, GLOBAL_RATE_LIMIT

logger = logging.getLogger(__name__)


class UsageTracker:
    def __init__(self):
        # {api_key: {"total": int, "models": {model: int}, "requests": [timestamp, ...]}}
        self.usage: dict[str, dict] = defaultdict(lambda: {
            "total": 0,
            "models": defaultdict(int),
            "requests": [],
        })

    def record(self, api_key: str, model: str):
        """记录一次请求"""
        now = time.time()
        entry = self.usage[api_key]
        entry["total"] += 1
        entry["models"][model] += 1
        entry["requests"].append(now)
        # 只保留最近5分钟的请求记录（用于限流计算）
        cutoff = now - 300
        entry["requests"] = [t for t in entry["requests"] if t > cutoff]

    def check_rate_limit(self, api_key: str) -> bool:
        """检查是否超过限流，返回 True 表示允许"""
        now = time.time()
        one_min_ago = now - 60

        # 检查单用户限流
        key_config = API_KEYS.get(api_key, {})
        user_limit = key_config.get("rate_limit", 60)
        user_requests = self.usage[api_key]["requests"]
        recent_user = sum(1 for t in user_requests if t > one_min_ago)
        if recent_user >= user_limit:
            logger.warning(f"Rate limit hit for key {api_key[:10]}...: {recent_user}/{user_limit}")
            return False

        # 检查全局限流
        total_recent = 0
        for entry in self.usage.values():
            total_recent += sum(1 for t in entry["requests"] if t > one_min_ago)
        if total_recent >= GLOBAL_RATE_LIMIT:
            logger.warning(f"Global rate limit hit: {total_recent}/{GLOBAL_RATE_LIMIT}")
            return False

        return True

    def get_usage(self, api_key: str) -> dict:
        """获取某个 key 的用量"""
        entry = self.usage[api_key]
        return {
            "total": entry["total"],
            "models": dict(entry["models"]),
            "recent_1min": sum(1 for t in entry["requests"] if t > time.time() - 60),
        }

    def get_all(self) -> dict:
        """获取所有用量"""
        return {k: self.get_usage(k) for k in self.usage}
