"""MinIO storage module for ChatShare - backup/archive conversations."""

import io
import json
import logging
import asyncio
from functools import partial
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = "100.87.204.122:9000"
MINIO_ACCESS_KEY = "admin"
MINIO_SECRET_KEY = "minio@admin2026"
MINIO_BUCKET = "chatshare-data"
MINIO_SECURE = False


class MinIOStorage:
    def __init__(self):
        self.client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
        self.bucket = MINIO_BUCKET
        self._ensure_bucket()

    def _ensure_bucket(self):
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created bucket: {self.bucket}")
        except Exception as e:
            logger.error(f"MinIO bucket check failed: {e}")

    def _user_prefix(self, user_id: int, username: str) -> str:
        return f"users/user_{user_id}_{username}"

    def _put_json(self, path: str, data: dict):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.client.put_object(
            self.bucket, path, io.BytesIO(raw), len(raw),
            content_type="application/json",
        )

    def _put_bytes(self, path: str, raw: bytes, content_type: str = "application/x-ndjson"):
        self.client.put_object(
            self.bucket, path, io.BytesIO(raw), len(raw),
            content_type=content_type,
        )

    def _get_bytes(self, path: str) -> bytes | None:
        try:
            resp = self.client.get_object(self.bucket, path)
            data = resp.read()
            resp.close()
            resp.release_conn()
            return data
        except S3Error:
            return None

    # ── User ──────────────────────────────────────────────────────────────

    def create_user_folder(self, user_id: int, username: str):
        prefix = self._user_prefix(user_id, username)
        self._put_bytes(f"{prefix}/.keep", b"", "application/octet-stream")
        logger.info(f"MinIO: created user folder {prefix}")

    # ── Conversation ──────────────────────────────────────────────────────

    def create_conversation(self, user_id: int, username: str, conv_id: int, metadata: dict):
        prefix = self._user_prefix(user_id, username)
        self._put_json(f"{prefix}/conversations/conv_{conv_id}.json", metadata)
        # Create empty JSONL
        self._put_bytes(f"{prefix}/conversations/conv_{conv_id}.jsonl", b"")

    def update_conversation_meta(self, user_id: int, username: str, conv_id: int, metadata: dict):
        prefix = self._user_prefix(user_id, username)
        self._put_json(f"{prefix}/conversations/conv_{conv_id}.json", metadata)

    def delete_conversation(self, user_id: int, username: str, conv_id: int):
        prefix = self._user_prefix(user_id, username)
        for suffix in (".json", ".jsonl"):
            try:
                self.client.remove_object(self.bucket, f"{prefix}/conversations/conv_{conv_id}{suffix}")
            except S3Error:
                pass

    # ── Messages ──────────────────────────────────────────────────────────

    def append_message(self, user_id: int, username: str, conv_id: int, message: dict):
        path = f"{self._user_prefix(user_id, username)}/conversations/conv_{conv_id}.jsonl"
        existing = self._get_bytes(path) or b""
        new_line = json.dumps(message, ensure_ascii=False) + "\n"
        updated = existing + new_line.encode("utf-8")
        self._put_bytes(path, updated)

    def get_messages(self, user_id: int, username: str, conv_id: int) -> list[dict]:
        path = f"{self._user_prefix(user_id, username)}/conversations/conv_{conv_id}.jsonl"
        raw = self._get_bytes(path)
        if not raw:
            return []
        lines = raw.decode("utf-8").strip().split("\n")
        return [json.loads(line) for line in lines if line.strip()]

    def mark_messages_replaced(self, user_id: int, username: str, conv_id: int, from_seq: int):
        """Mark messages with seq >= from_seq as replaced."""
        msgs = self.get_messages(user_id, username, conv_id)
        updated_lines = []
        for m in msgs:
            if m.get("seq", 0) >= from_seq:
                m["replaced"] = True
            updated_lines.append(json.dumps(m, ensure_ascii=False))
        raw = ("\n".join(updated_lines) + "\n").encode("utf-8")
        path = f"{self._user_prefix(user_id, username)}/conversations/conv_{conv_id}.jsonl"
        self._put_bytes(path, raw)

    def mark_single_replaced(self, user_id: int, username: str, conv_id: int, seq: int):
        """Mark a single message as replaced."""
        msgs = self.get_messages(user_id, username, conv_id)
        updated_lines = []
        for m in msgs:
            if m.get("seq") == seq:
                m["replaced"] = True
            updated_lines.append(json.dumps(m, ensure_ascii=False))
        raw = ("\n".join(updated_lines) + "\n").encode("utf-8")
        path = f"{self._user_prefix(user_id, username)}/conversations/conv_{conv_id}.jsonl"
        self._put_bytes(path, raw)


# Singleton
_storage: MinIOStorage | None = None


def get_storage() -> MinIOStorage:
    global _storage
    if _storage is None:
        _storage = MinIOStorage()
    return _storage


async def run_sync(fn, *args):
    """Run a sync MinIO operation in executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(fn, *args))
