import uuid
import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, Response, JSONResponse
from pydantic import BaseModel

from .db import get_pool
from .models import RegisterRequest, LoginRequest, ConversationCreate, ConversationUpdate, MessageCreate
from .user_auth import hash_password, verify_password, create_token, generate_api_key, get_current_user
from .converter import resolve_model, openai_to_backend_gpt, openai_to_backend_sass, build_variant_request, SSEParser, ClaudeSSEParser, OpenAISSEParser, MODEL_MAP, _make_chunk
from .dispatcher import NoCarAvailableError
from .storage import get_storage, run_sync

logger = logging.getLogger(__name__)

router = APIRouter()

MEDIA_GEN_MODELS = {
    "4o-image",
    "Nano-banana",
    "Nano-banana-Pro",
    "即梦-4.0画图模型",
    "即梦-4.1画图模型",
    "即梦-4.5画图模型",
    "Veo_3_1",
    "即梦3.0视频模型",
}


def _truncate(value: str, limit: int = 1200) -> str:
    if value is None:
        return ""
    s = str(value)
    return s if len(s) <= limit else s[:limit] + "...<truncated>"


def _log_upstream_request(url: str, payload=None):
    try:
        if payload is None:
            logger.info("Official API request: url=%s", url)
        elif isinstance(payload, (dict, list)):
            logger.info("Official API request: url=%s payload=%s", url, _truncate(json.dumps(payload, ensure_ascii=False)))
        elif isinstance(payload, (bytes, bytearray)):
            logger.info("Official API request: url=%s payload_bytes=%s", url, len(payload))
        else:
            logger.info("Official API request: url=%s payload=%s", url, _truncate(payload))
    except Exception:
        pass


def _log_upstream_response(url: str, status: int, body=None):
    try:
        if body is None:
            logger.info("Official API response: url=%s status=%s", url, status)
        elif isinstance(body, (bytes, bytearray)):
            txt = body.decode("utf-8", errors="ignore")
            logger.info("Official API response: url=%s status=%s body=%s", url, status, _truncate(txt))
        else:
            logger.info("Official API response: url=%s status=%s body=%s", url, status, _truncate(body))
    except Exception:
        pass


def _file_session_map(request: Request) -> dict:
    m = getattr(request.app.state, "file_upload_session_map", None)
    if m is None:
        m = {}
        request.app.state.file_upload_session_map = m
    return m


def _task_map(request: Request) -> dict:
    m = getattr(request.app.state, "generate_task_map", None)
    if m is None:
        m = {}
        request.app.state.generate_task_map = m
    return m


def _task_event_text(task: dict, start: int = 0) -> str:
    text = task.get("partial_text") or ""
    if start < 0:
        start = 0
    if start >= len(text):
        return ""
    return text[start:]



# ── Auth ──────────────────────────────────────────────────────────────────────

@router.post("/api/auth/register")
async def register(body: RegisterRequest):
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if await conn.fetchrow("SELECT id FROM chat_users WHERE username=$1", body.username):
            raise HTTPException(status_code=400, detail="用户名已存在")
        hashed = hash_password(body.password)
        api_key = generate_api_key()
        nickname = body.nickname or body.username
        user = await conn.fetchrow(
            "INSERT INTO chat_users (username,password,nickname,api_key) VALUES ($1,$2,$3,$4) RETURNING id,username,nickname",
            body.username, hashed, nickname, api_key,
        )
    # Create MinIO user folder
    try:
        storage = get_storage()
        await run_sync(storage.create_user_folder, user["id"], user["username"])
    except Exception as e:
        logger.error(f"MinIO create user folder failed: {e}")

    token = create_token(user["id"], user["username"])
    return {"token": token, "user": {"id": user["id"], "username": user["username"], "nickname": user["nickname"]}}


@router.post("/api/auth/login")
async def login(body: LoginRequest, request: Request):
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id,username,nickname,password FROM chat_users WHERE username=$1", body.username
        )
        if not user or not verify_password(body.password, user["password"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        forwarded_for = request.headers.get("x-forwarded-for", "")
        real_ip = (forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else None))
        user_agent = request.headers.get("user-agent", "")
        try:
            await conn.execute(
                "INSERT INTO login_audit (user_id, username, ip, user_agent) VALUES ($1,$2,$3,$4)",
                user["id"], user["username"], real_ip, user_agent,
            )
        except Exception as e:
            logger.warning(f"write login_audit failed: {e}")

    token = create_token(user["id"], user["username"])
    return {"token": token, "user": {"id": user["id"], "username": user["username"], "nickname": user["nickname"]}}


@router.get("/api/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id,username,nickname,created_at FROM chat_users WHERE id=$1", current_user["id"]
        )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(user)


# ── Models ────────────────────────────────────────────────────────────────────

@router.get("/api/models")
async def list_models(current_user: dict = Depends(get_current_user)):
    groups = [
        {"group": "GPT 系列", "models": [
            {"id": "gpt-5-2", "name": "GPT-5.2"},
            {"id": "gpt-5-2-instant", "name": "GPT-5.2 Instant"},
            {"id": "gpt-5-2-thinking", "name": "GPT-5.2 Thinking"},
            {"id": "gpt-5-2-pro", "name": "GPT-5.2 Pro"},
            {"id": "gpt-5-1", "name": "GPT-5.1"},
            {"id": "gpt-5-1-thinking", "name": "GPT-5.1 Thinking"},
            {"id": "gpt-5-1-pro", "name": "GPT-5.1 Pro"},
        ]},
        {"group": "Claude 系列", "models": [
            {"id": "claude-opus-4", "name": "Claude Opus 4"},
            {"id": "claude-4.6-sonnet", "name": "Claude 4.6 Sonnet"},
            {"id": "claude-4.6-sonnet-code", "name": "Claude 4.6 Sonnet (编程)"},
            {"id": "claude-code", "name": "Claude Code"},
        ]},
        {"group": "Gemini 系列", "models": [
            {"id": "gemini-pro", "name": "Gemini 3.1 Pro [API]"},
            {"id": "gemini-pro-web", "name": "Gemini 3.1 Pro [联网]"},
            {"id": "gemini-flash", "name": "Gemini 3.1 Flash"},
        ]},
        {"group": "Grok 系列", "models": [
            {"id": "grok-4", "name": "Grok 4"},
            {"id": "grok-4.2", "name": "Grok 4.2"},
            {"id": "grok-4.2-thinking", "name": "Grok 4.2 Thinking"},
            {"id": "grok-4-research", "name": "Grok 4 深度研究"},
            {"id": "grok-3", "name": "Grok 3"},
        ]},
        {"group": "Deepseek 系列", "models": [
            {"id": "deepseek-v3", "name": "Deepseek V3"},
            {"id": "deepseek-r1", "name": "Deepseek R1"},
        ]},
        {"group": "图片生成模型", "models": [
            {"id": "4o-image", "name": "4o-image"},
            {"id": "Nano-banana", "name": "Nano-banana"},
            {"id": "Nano-banana-Pro", "name": "Nano-banana-Pro"},
            {"id": "即梦-4.0画图模型", "name": "即梦 4.0 画图"},
            {"id": "即梦-4.1画图模型", "name": "即梦 4.1 画图"},
            {"id": "即梦-4.5画图模型", "name": "即梦 4.5 画图"},
        ]},
        {"group": "视频生成模型", "models": [
            {"id": "Veo_3_1", "name": "Veo 3.1"},
            {"id": "即梦3.0视频模型", "name": "即梦 3.0 视频"},
        ]},
        {"group": "Codex 编程系列", "models": [
            {"id": "codex-5.2", "name": "GPT-5.2 Codex"},
            {"id": "codex-5.2-max", "name": "GPT-5.2 Codex Max"},
            {"id": "codex-5.3", "name": "GPT-5.3 Codex"},
        ]},
    ]
    return groups



class GenerateTaskBody(BaseModel):
    conversation_id: int
    content: str
    model: str = "gpt-4o"
    attachments: list[dict] = []


async def _run_generate_task(app, task_id: str, user: dict, body: GenerateTaskBody):
    task_store = getattr(app.state, "generate_task_map", {})
    task = task_store.get(task_id)
    if not task:
        return

    dispatcher = app.state.dispatcher
    pool = await get_pool()
    conv_id = body.conversation_id

    try:
        async with pool.acquire() as conn:
            conv = await conn.fetchrow(
                "SELECT id, chatshare_conv_id, last_message_id FROM chat_conversations WHERE id=$1 AND user_id=$2",
                conv_id, user["id"],
            )
            if not conv:
                task["status"] = "error"
                task["error_code"] = "conversation_not_found"
                task["error_message"] = "Conversation not found"
                return

            chatshare_conv_id = conv["chatshare_conv_id"]
            last_msg_id = conv["last_message_id"]

            next_seq = await _get_next_seq(conn, conv_id)
            await conn.execute(
                "INSERT INTO chat_messages (conversation_id,role,content,seq,replaced) VALUES ($1,'user',$2,$3,false)",
                conv_id, body.content, next_seq,
            )

            history = await conn.fetch(
                "SELECT role,content FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false) ORDER BY created_at ASC",
                conv_id,
            )

            await conn.execute(
                "UPDATE chat_conversations SET model=$1, updated_at=NOW() WHERE id=$2",
                body.model, conv_id,
            )

        minio_msg = {
            "seq": next_seq, "role": "user", "content": body.content,
            "timestamp": datetime.utcnow().isoformat() + "Z", "replaced": False,
        }
        await _save_to_minio(user["id"], user["username"], conv_id, minio_msg)

        if chatshare_conv_id:
            messages = [{"role": "user", "content": body.content}]
        else:
            messages = [{"role": r["role"], "content": r["content"]} for r in history]

        class _Req:
            def __init__(self, app):
                self.app = app

        req = _Req(app)
        async for chunk in _do_stream(
            req, dispatcher, conv_id, messages, body.model, user["id"], user["username"],
            chatshare_conv_id=chatshare_conv_id, last_message_id=last_msg_id, attachments=body.attachments or None,
        ):
            if not isinstance(chunk, str) or not chunk.startswith("data: "):
                continue
            payload = chunk[6:].strip()
            if payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except Exception:
                continue

            if isinstance(obj, dict) and obj.get("error"):
                task["status"] = "error"
                task["error_code"] = "upstream_error"
                task["error_message"] = str(obj.get("error"))
                task["updated_at"] = datetime.utcnow().isoformat() + "Z"
                return

            choices = (obj.get("choices") or []) if isinstance(obj, dict) else []
            if choices:
                delta = (choices[0].get("delta") or {})
                piece = delta.get("content")
                if piece:
                    task["partial_text"] += piece
                    task["offset"] = len(task["partial_text"])
                    task["updated_at"] = datetime.utcnow().isoformat() + "Z"

        task["status"] = "done"
        task["result_text"] = task.get("partial_text", "")
        task["updated_at"] = datetime.utcnow().isoformat() + "Z"
    except Exception as e:
        task["status"] = "error"
        task["error_code"] = "task_exception"
        task["error_message"] = str(e)
        task["updated_at"] = datetime.utcnow().isoformat() + "Z"


@router.post("/backend-api/tasks/generate")
async def create_generate_task(body: GenerateTaskBody, request: Request, current_user: dict = Depends(get_current_user)):
    task_store = _task_map(request)
    request_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat() + "Z"
    task = {
        "request_id": request_id,
        "user_id": current_user["id"],
        "conversation_id": body.conversation_id,
        "model": body.model,
        "status": "running",
        "offset": 0,
        "partial_text": "",
        "result_text": "",
        "error_code": None,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    task_store[request_id] = task
    asyncio.create_task(_run_generate_task(request.app, request_id, current_user, body))
    return {"request_id": request_id, "status": "running"}


@router.get("/backend-api/tasks/{request_id}")
async def get_generate_task(request_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    task_store = _task_map(request)
    task = task_store.get(request_id)
    if not task or task.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=404, detail="Task not found")

    status = task.get("status")
    if status == "running":
        return {
            "request_id": request_id,
            "status": "running",
            "offset": task.get("offset", 0),
            "partial_text": task.get("partial_text", ""),
        }
    if status == "done":
        return {
            "request_id": request_id,
            "status": "done",
            "offset": task.get("offset", 0),
            "result_text": task.get("result_text", ""),
            "usage": None,
        }
    return {
        "request_id": request_id,
        "status": "error",
        "error_code": task.get("error_code") or "unknown",
        "error_message": task.get("error_message") or "unknown error",
    }


@router.get("/backend-api/tasks/{request_id}/events")
async def get_generate_task_events(request_id: str, request: Request, offset: int = 0, current_user: dict = Depends(get_current_user)):
    task_store = _task_map(request)
    task = task_store.get(request_id)
    if not task or task.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=404, detail="Task not found")
    delta = _task_event_text(task, offset)
    return {"request_id": request_id, "status": task.get("status"), "offset": task.get("offset", 0), "events": [delta] if delta else []}



# ── Conversations ─────────────────────────────────────────────────────────────

@router.get("/api/conversations")
async def list_conversations(current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.title, c.model, c.updated_at,
                   (SELECT content FROM chat_messages
                    WHERE conversation_id=c.id AND (replaced IS NULL OR replaced=false)
                    ORDER BY created_at DESC LIMIT 1) AS last_message_preview
            FROM chat_conversations c
            WHERE c.user_id=$1
            ORDER BY c.updated_at DESC
            """,
            current_user["id"],
        )
    return [dict(r) for r in rows]


@router.post("/api/conversations")
async def create_conversation(body: ConversationCreate, current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO chat_conversations (user_id,title,model) VALUES ($1,$2,$3) RETURNING id,title,model,created_at,updated_at",
            current_user["id"], body.title or "新对话", body.model or "gpt-4o",
        )
    conv = dict(row)
    # MinIO backup
    try:
        storage = get_storage()
        meta = {
            "id": conv["id"], "user_id": current_user["id"],
            "title": conv["title"], "model": conv["model"],
            "created_at": conv["created_at"].isoformat() if conv.get("created_at") else None,
            "updated_at": conv["updated_at"].isoformat() if conv.get("updated_at") else None,
            "message_count": 0,
        }
        await run_sync(storage.create_conversation, current_user["id"], current_user["username"], conv["id"], meta)
    except Exception as e:
        logger.error(f"MinIO create conv failed: {e}")
    return conv


@router.put("/api/conversations/{conv_id}")
async def update_conversation(conv_id: int, body: ConversationUpdate, current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE chat_conversations SET title=$1 WHERE id=$2 AND user_id=$3 RETURNING id,title",
            body.title, conv_id, current_user["id"],
        )
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # MinIO update meta
    try:
        storage = get_storage()
        async with pool.acquire() as conn:
            full = await conn.fetchrow("SELECT * FROM chat_conversations WHERE id=$1", conv_id)
        if full:
            cnt = await (await get_pool()).fetchval(
                "SELECT COUNT(*) FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false)", conv_id
            )
            meta = {
                "id": full["id"], "user_id": current_user["id"],
                "title": body.title, "model": full["model"],
                "created_at": full["created_at"].isoformat() if full.get("created_at") else None,
                "updated_at": full["updated_at"].isoformat() if full.get("updated_at") else None,
                "message_count": cnt,
            }
            await run_sync(storage.update_conversation_meta, current_user["id"], current_user["username"], conv_id, meta)
    except Exception as e:
        logger.error(f"MinIO update conv meta failed: {e}")
    return dict(row)


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: int, current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM chat_conversations WHERE id=$1 AND user_id=$2", conv_id, current_user["id"]
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Conversation not found")
    # MinIO delete
    try:
        storage = get_storage()
        await run_sync(storage.delete_conversation, current_user["id"], current_user["username"], conv_id)
    except Exception as e:
        logger.error(f"MinIO delete conv failed: {e}")
    return {"ok": True}


# ── Messages ──────────────────────────────────────────────────────────────────

@router.get("/api/conversations/{conv_id}/messages")
async def list_messages(conv_id: int, limit: int = 50, include_replaced: bool = False, current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await conn.fetchrow(
            "SELECT id FROM chat_conversations WHERE id=$1 AND user_id=$2", conv_id, current_user["id"]
        ):
            raise HTTPException(status_code=404, detail="Conversation not found")
        if include_replaced:
            rows = await conn.fetch(
                "SELECT id,seq,role,content,model,replaced,created_at FROM chat_messages WHERE conversation_id=$1 ORDER BY created_at ASC LIMIT $2",
                conv_id, limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT id,seq,role,content,model,replaced,created_at FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false) ORDER BY created_at ASC LIMIT $2",
                conv_id, limit,
            )
    return [dict(r) for r in rows]


async def _get_next_seq(conn, conv_id: int) -> int:
    val = await conn.fetchval(
        "SELECT COALESCE(MAX(seq),0) FROM chat_messages WHERE conversation_id=$1", conv_id
    )
    return val + 1


async def _save_to_minio(user_id, username, conv_id, msg_dict):
    """Background save message to MinIO."""
    try:
        storage = get_storage()
        await run_sync(storage.append_message, user_id, username, conv_id, msg_dict)
    except Exception as e:
        logger.error(f"MinIO append msg failed: {e}")


async def _update_minio_meta(user_id, username, conv_id):
    """Update conversation metadata in MinIO."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            conv = await conn.fetchrow("SELECT * FROM chat_conversations WHERE id=$1", conv_id)
            cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false)", conv_id
            )
        if conv:
            storage = get_storage()
            meta = {
                "id": conv["id"], "user_id": user_id,
                "title": conv["title"], "model": conv["model"],
                "created_at": conv["created_at"].isoformat() if conv.get("created_at") else None,
                "updated_at": conv["updated_at"].isoformat() if conv.get("updated_at") else None,
                "message_count": cnt,
            }
            await run_sync(storage.update_conversation_meta, user_id, username, conv_id, meta)
    except Exception as e:
        logger.error(f"MinIO update meta failed: {e}")


async def _do_variant_stream(request, dispatcher, conv_id, chatshare_conv_id, parent_message_id, model, user_id, username):
    """Use ChatShare's native variant action to retry with a different model."""
    channel, chatshare_model = resolve_model(model)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    logger.info(f"Variant: conv_id={conv_id}, cs_conv={chatshare_conv_id}, parent_msg={parent_message_id}, model={model}, channel={channel}, cs_model={chatshare_model}")

    # Build variant request
    variant_request = build_variant_request(chatshare_conv_id, parent_message_id, chatshare_model)

    # Acquire session based on channel
    # Variant always goes through sass/gpt conversation API (even for claude models)
    session = None
    try:
        if channel in ("sass", "claude"):
            session = await dispatcher.get_sass_session()
            session.is_busy = True
            sentinel_token = await session.get_sentinel_token()
            url = session.get_conversation_url()
            headers = session.get_conversation_headers(sentinel_token)
        elif channel == "gpt":
            session = await dispatcher.select_car(channel)
            session.is_busy = True
            url = session.get_conversation_url()
            headers = session.get_headers()
        else:
            yield f"data: {json.dumps({'error': f'模型 {model} 不支持 variant 重试'})}\n\n"
            yield "data: [DONE]\n\n"
            return
    except Exception as e:
        logger.error(f"Variant session acquire error: {e}")
        yield f"data: {json.dumps({'error': f'无法获取模型会话: {str(e)}'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    parser = SSEParser(model, chunk_id)
    try:
        _log_upstream_request(url, variant_request)
        async with session._client.stream("POST", url, json=variant_request, headers=headers, timeout=120) as resp:
            logger.info(f"Variant response status: {resp.status_code}")
            _log_upstream_response(url, resp.status_code)
            if resp.status_code == 401:
                logger.warning("Variant 401, session expired")
                yield f"data: {json.dumps({'error': 'Session expired'})}\n\n"
                yield "data: [DONE]\n\n"
                return
            if resp.status_code != 200:
                body = await resp.aread()
                logger.error(f"Variant non-200: {resp.status_code} body={body[:500]}")
                yield f"data: {json.dumps({'error': f'ChatShare returned {resp.status_code}'})}\n\n"
                yield "data: [DONE]\n\n"
                return
            content_type = (resp.headers.get("content-type") or "").lower()
            if "text/event-stream" not in content_type:
                body = await resp.aread()
                msg = body.decode("utf-8", errors="ignore")[:300] or f"HTTP {resp.status_code}"
                logger.warning(f"Variant non-SSE response: status={resp.status_code}, ct={content_type}, body={msg}")
                yield f"data: {json.dumps({'error': msg})}\n\n"
                yield "data: [DONE]\n\n"
                return
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                for chunk in parser.parse_line(line):
                    yield chunk
    except Exception as e:
        logger.error(f"Variant stream error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        if session:
            dispatcher.release_car(session)

    full_text = parser.full_text

    # Update chatshare IDs
    if parser.conversation_id or parser.last_message_id:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE chat_conversations SET chatshare_conv_id=COALESCE($1,chatshare_conv_id), last_message_id=COALESCE($2,last_message_id) WHERE id=$3",
                    parser.conversation_id, parser.last_message_id, conv_id,
                )
        except Exception as e:
            logger.error(f"Failed to save variant chatshare IDs: {e}")

    # Save AI response
    if full_text:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                next_seq = await _get_next_seq(conn, conv_id)
                await conn.execute(
                    "INSERT INTO chat_messages (conversation_id,role,content,model,seq,replaced) VALUES ($1,'assistant',$2,$3,$4,false)",
                    conv_id, full_text, model, next_seq,
                )
                await conn.execute("UPDATE chat_conversations SET updated_at=NOW() WHERE id=$1", conv_id)
            minio_msg = {
                "seq": next_seq, "role": "assistant", "content": full_text,
                "model": model, "timestamp": datetime.utcnow().isoformat() + "Z", "replaced": False,
            }
            await _save_to_minio(user_id, username, conv_id, minio_msg)
        except Exception as e:
            logger.error(f"Save variant AI response failed: {e}")


async def _do_stream(request, dispatcher, conv_id, messages, model, user_id, username, chatshare_conv_id=None, last_message_id=None, attachments=None):
    """Core streaming logic shared by send/edit/retry. Yields SSE chunks."""
    # Experiment mode: keep transformed file_id in conversation payload
    upstream_attachments = None
    if attachments:
        upstream_attachments = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            upstream_attachments.append(dict(item))
    channel, chatshare_model = resolve_model(model)
    is_media_gen_model = model in MEDIA_GEN_MODELS or chatshare_model in MEDIA_GEN_MODELS
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Acquire session
    claude_session = None
    session = None
    try:
        if channel == "claude":
            claude_session = await dispatcher.get_claude_session()
            claude_session.is_busy = True
        elif channel == "sass":
            # Attachment flow should reuse the same session as upload steps when possible
            if upstream_attachments:
                try:
                    file_id = (upstream_attachments[0] or {}).get("id") if upstream_attachments else None
                    bound = _file_session_map(request).get(file_id) if file_id else None
                    if bound and bound.get("session"):
                        session = bound["session"]
                    else:
                        session = await dispatcher.get_sass_session()
                except Exception:
                    session = await dispatcher.get_sass_session()
            else:
                session = await dispatcher.get_sass_session()
            session.is_busy = True
            sentinel_token = await session.get_sentinel_token()

            if is_media_gen_model:
                prepared = await session.prepare(chatshare_model)
                logger.info("Media model prepare: model=%s prepared=%s", chatshare_model, prepared)

            # HAR flow: use /backend-api/f/conversation
            url = session.get_conversation_url()
            headers = session.get_conversation_headers(sentinel_token)
            backend_request = openai_to_backend_sass(messages, chatshare_model, conversation_id=chatshare_conv_id, parent_message_id=last_message_id, attachments=upstream_attachments)
        elif channel == "gpt":
            session = await dispatcher.select_car(channel)
            session.is_busy = True
            url = session.get_conversation_url()
            headers = session.get_headers()
            backend_request = openai_to_backend_gpt(messages, chatshare_model, stream=True, conversation_id=chatshare_conv_id, parent_message_id=last_message_id, attachments=upstream_attachments)
        else:
            yield f"data: {json.dumps({'error': f'模型 {model} 暂不可用'})}\n\n"
            return
    except NoCarAvailableError as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return
    except Exception as e:
        logger.error(f"Session acquire error: {e}")
        yield f"data: {json.dumps({'error': f'无法获取模型会话: {str(e)}'})}\n\n"
        return

    if upstream_attachments:
        try:
            msg0 = (backend_request.get("messages") or [{}])[0]
            atts = ((msg0.get("metadata") or {}).get("attachments") or [])
            logger.info(
                "Attachment conversation request: model=%s channel=%s conv_id=%s parent=%s attachments=%s payload=%s",
                chatshare_model,
                channel,
                backend_request.get("conversation_id"),
                backend_request.get("parent_message_id"),
                json.dumps(atts, ensure_ascii=False),
                json.dumps(backend_request, ensure_ascii=False)[:1200],
            )
        except Exception:
            pass

    full_text = ""

    if claude_session:
        parser = ClaudeSSEParser(model, chunk_id)
        max_retries = 3
        current_session = claude_session
        # Build context-aware prompt for Claude
        # Compress history into context summary + last user message
        from .converter import _build_context_prompt
        context_prefix, last_user_content = _build_context_prompt(messages)
        prompt = last_user_content
        if context_prefix:
            prompt = context_prefix + "\n\n用户的新问题：" + last_user_content

        success = False
        for attempt in range(max_retries):
            conv_uuid = str(uuid.uuid4())
            try:
                create_url = current_session.get_create_conv_url()
                create_headers = current_session.get_headers()
                CLAUDE_MODEL_MAP = {
                    "Claude-opus-4-6（编程版）": "claude-opus-4-6",
                    "Claude-4.6-sonnet（编程版）": "claude-sonnet-4-6",
                    "Claude-4.6-sonnet（通用版）": "claude-sonnet-4-6",
                    "Claude code（通用版）": "claude-sonnet-4-6",
                }
                claude_model_id = CLAUDE_MODEL_MAP.get(chatshare_model, "claude-sonnet-4-6")
                create_resp = await current_session._client.post(
                    create_url, json={"name": "", "uuid": conv_uuid, "model": claude_model_id}, headers=create_headers
                )
                if create_resp.status_code not in (200, 201):
                    logger.warning(f"Claude create conv failed: {create_resp.status_code} (attempt {attempt+1})")
                    await current_session.close()
                    if attempt < max_retries - 1:
                        try:
                            current_session = await dispatcher._create_claude_session()
                        except Exception:
                            pass
                    continue

                comp_url = current_session.get_completion_url(conv_uuid)
                comp_body = {"prompt": prompt, "timezone": "Asia/Shanghai", "attachments": [], "files": []}
                async with current_session._client.stream(
                    "POST", comp_url, json=comp_body, headers=create_headers, timeout=120
                ) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        logger.warning(f"Claude completion {resp.status_code} (attempt {attempt+1}): {error_body.decode()[:300]}")
                        await current_session.close()
                        if attempt < max_retries - 1:
                            try:
                                current_session = await dispatcher._create_claude_session()
                            except Exception:
                                pass
                            continue
                        yield f"data: {json.dumps({'error': 'Claude 服务暂时不可用，请稍后重试'})}\n\n"
                        return

                    success = True
                    sent_done = False
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        for chunk in parser.parse_line(line):
                            yield chunk
                            if "[DONE]" in chunk:
                                sent_done = True
                    if not sent_done and parser.full_text:
                        finish = _make_chunk(chunk_id, model, finish_reason="stop")
                        yield f"data: {json.dumps(finish)}\n\n"
                        yield "data: [DONE]\n\n"
                break
            except Exception as e:
                logger.warning(f"Claude attempt {attempt+1} error: {e}")
                await current_session.close()
                if attempt < max_retries - 1:
                    try:
                        current_session = await dispatcher._create_claude_session()
                    except Exception:
                        pass
                else:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"

        if not success and not parser.full_text:
            yield f"data: {json.dumps({'error': 'Claude 所有重试均失败'})}\n\n"
        dispatcher.release_car(current_session)
        full_text = parser.full_text
    else:
        # GPT / sass / grok / deepseek
        parser = SSEParser(model, chunk_id)
        max_retries = 2
        current_session = session
        success = False
        for attempt in range(max_retries):
            try:
                _log_upstream_request(url, backend_request)
                async with current_session._client.stream("POST", url, json=backend_request, headers=headers, timeout=120) as resp:
                    _log_upstream_response(url, resp.status_code)
                    if resp.status_code == 401:
                        logger.warning(f"GPT/sass 401 (attempt {attempt+1}), refreshing session")
                        dispatcher.release_car(current_session)

                        # For gpt/grok/deepseek channels, drop the stale car session to avoid reusing
                        # the same expired cookies on retry.
                        if channel != "sass":
                            try:
                                if getattr(current_session, "car_id", None):
                                    dispatcher.car_sessions.get(channel, {}).pop(current_session.car_id, None)
                                await current_session.close()
                            except Exception:
                                pass

                        if attempt < max_retries - 1:
                            try:
                                if channel == "sass":
                                    current_session = await dispatcher._create_sass_session()
                                else:
                                    current_session = await dispatcher.select_car(channel)
                                current_session.is_busy = True
                                sentinel_token = await current_session.get_sentinel_token() if channel == "sass" else None
                                if channel == "sass" and is_media_gen_model:
                                    prepared = await current_session.prepare(chatshare_model)
                                    logger.info("Media model prepare on retry: model=%s prepared=%s", chatshare_model, prepared)
                                url = current_session.get_conversation_url()
                                headers = current_session.get_conversation_headers(sentinel_token) if channel == "sass" else current_session.get_headers()
                            except Exception as e2:
                                logger.error(f"Session refresh failed: {e2}")
                                yield f"data: {json.dumps({'error': '图片/视频通道登录态已过期，请稍后重试或刷新上游登录'})}\n\n"
                                yield "data: [DONE]\n\n"
                                return
                            continue
                        yield f"data: {json.dumps({'error': '图片/视频通道登录态已过期，请稍后重试或刷新上游登录'})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    content_type = (resp.headers.get("content-type") or "").lower()
                    if "text/event-stream" not in content_type:
                        body = await resp.aread()
                        try:
                            err = json.loads(body.decode("utf-8", errors="ignore"))
                            msg = err.get("detail") or err.get("error") or body.decode("utf-8", errors="ignore")[:300]
                        except Exception:
                            msg = body.decode("utf-8", errors="ignore")[:300] or f"HTTP {resp.status_code}"
                        _log_upstream_response(url, resp.status_code, msg)
                        logger.warning(
                            "Conversation non-SSE response: status=%s, ct=%s, body=%s, model=%s, conv_id=%s, parent=%s",
                            resp.status_code,
                            content_type,
                            msg,
                            backend_request.get("model"),
                            backend_request.get("conversation_id"),
                            backend_request.get("parent_message_id"),
                        )
                        yield f"data: {json.dumps({'error': msg})}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    success = True
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        for chunk in parser.parse_line(line):
                            yield chunk
                break
            except Exception as e:
                logger.error(f"Stream error (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    continue
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                yield "data: [DONE]\n\n"
        if not success and not parser.full_text:
            pass  # error already yielded
        dispatcher.release_car(current_session)
        full_text = parser.full_text

        # Save ChatShare conversation_id and last_message_id for history passthrough
        if parser.conversation_id or parser.last_message_id:
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE chat_conversations SET chatshare_conv_id=COALESCE($1,chatshare_conv_id), last_message_id=COALESCE($2,last_message_id) WHERE id=$3",
                        parser.conversation_id, parser.last_message_id, conv_id,
                    )
            except Exception as e:
                logger.error(f"Failed to save chatshare IDs: {e}")

    # Save AI response to DB + MinIO
    if full_text:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                next_seq = await _get_next_seq(conn, conv_id)
                await conn.execute(
                    "INSERT INTO chat_messages (conversation_id,role,content,model,seq,replaced) VALUES ($1,'assistant',$2,$3,$4,false)",
                    conv_id, full_text, model, next_seq,
                )
                await conn.execute("UPDATE chat_conversations SET updated_at=NOW() WHERE id=$1", conv_id)
            minio_msg = {
                "seq": next_seq, "role": "assistant", "content": full_text,
                "model": model, "timestamp": datetime.utcnow().isoformat() + "Z", "replaced": False,
            }
            await _save_to_minio(user_id, username, conv_id, minio_msg)
            await _update_minio_meta(user_id, username, conv_id)
        except Exception as e:
            logger.error(f"Failed to save AI message: {e}")


@router.post("/api/conversations/{conv_id}/messages")
async def send_message(conv_id: int, body: MessageCreate, request: Request, current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    dispatcher = request.app.state.dispatcher

    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT id, chatshare_conv_id, last_message_id FROM chat_conversations WHERE id=$1 AND user_id=$2", conv_id, current_user["id"]
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        chatshare_conv_id = conv["chatshare_conv_id"]
        last_msg_id = conv["last_message_id"]

        if body.force_new_chatshare_context:
            chatshare_conv_id = None
            last_msg_id = None

        # Save user message
        next_seq = await _get_next_seq(conn, conv_id)
        await conn.execute(
            "INSERT INTO chat_messages (conversation_id,role,content,seq,replaced) VALUES ($1,'user',$2,$3,false)",
            conv_id, body.content, next_seq,
        )

        # Load active history
        history = await conn.fetch(
            "SELECT role,content FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false) ORDER BY created_at ASC",
            conv_id,
        )

        # Update model + timestamp
        await conn.execute(
            "UPDATE chat_conversations SET model=$1, updated_at=NOW() WHERE id=$2",
            body.model, conv_id,
        )

        # Auto-title on first user message
        active_count = await conn.fetchval(
            "SELECT COUNT(*) FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false)", conv_id
        )
        if active_count <= 1:
            title = body.content[:30].strip().replace("\n", " ")
            if title:
                await conn.execute("UPDATE chat_conversations SET title=$1 WHERE id=$2", title, conv_id)

    # MinIO: save user message
    minio_msg = {
        "seq": next_seq, "role": "user", "content": body.content,
        "timestamp": datetime.utcnow().isoformat() + "Z", "replaced": False,
    }
    await _save_to_minio(current_user["id"], current_user["username"], conv_id, minio_msg)

    # If we have chatshare_conv_id, only send the last user message (ChatShare has full context)
    if chatshare_conv_id:
        messages = [{"role": "user", "content": body.content}]
    else:
        messages = [{"role": r["role"], "content": r["content"]} for r in history]

    return StreamingResponse(
        _do_stream(request, dispatcher, conv_id, messages, body.model, current_user["id"], current_user["username"], chatshare_conv_id=chatshare_conv_id, last_message_id=last_msg_id, attachments=body.attachments or None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Edit message ──────────────────────────────────────────────────────────────

from pydantic import BaseModel as _BM

class MessageEditBody(_BM):
    content: str
    model: str = "gpt-4o"

@router.put("/api/conversations/{conv_id}/messages/{msg_seq}")
async def edit_message(conv_id: int, msg_seq: int, body: MessageEditBody, request: Request, current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    dispatcher = request.app.state.dispatcher

    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT id FROM chat_conversations WHERE id=$1 AND user_id=$2", conv_id, current_user["id"]
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Find the message to edit
        msg = await conn.fetchrow(
            "SELECT id,seq,role FROM chat_messages WHERE conversation_id=$1 AND seq=$2 AND role='user' AND (replaced IS NULL OR replaced=false)",
            conv_id, msg_seq,
        )
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")

        # Mark this message and all after it as replaced
        await conn.execute(
            "UPDATE chat_messages SET replaced=true WHERE conversation_id=$1 AND seq>=$2 AND (replaced IS NULL OR replaced=false)",
            conv_id, msg_seq,
        )

        # MinIO: mark replaced
        try:
            storage = get_storage()
            await run_sync(storage.mark_messages_replaced, current_user["id"], current_user["username"], conv_id, msg_seq)
        except Exception as e:
            logger.error(f"MinIO mark replaced failed: {e}")

        # Insert new user message
        next_seq = await _get_next_seq(conn, conv_id)
        await conn.execute(
            "INSERT INTO chat_messages (conversation_id,role,content,seq,replaced) VALUES ($1,'user',$2,$3,false)",
            conv_id, body.content, next_seq,
        )

        # Load active history (up to and including the new message)
        history = await conn.fetch(
            "SELECT role,content FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false) ORDER BY created_at ASC",
            conv_id,
        )

        await conn.execute("UPDATE chat_conversations SET model=$1, updated_at=NOW() WHERE id=$2", body.model, conv_id)

    # MinIO: save new user message
    minio_msg = {
        "seq": next_seq, "role": "user", "content": body.content,
        "timestamp": datetime.utcnow().isoformat() + "Z", "replaced": False,
    }
    await _save_to_minio(current_user["id"], current_user["username"], conv_id, minio_msg)

    messages = [{"role": r["role"], "content": r["content"]} for r in history]

    return StreamingResponse(
        _do_stream(request, dispatcher, conv_id, messages, body.model, current_user["id"], current_user["username"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Retry message ─────────────────────────────────────────────────────────────

class RetryBody(_BM):
    model: str | None = None
    instruction: str | None = None

@router.post("/api/conversations/{conv_id}/messages/{msg_seq}/retry")
async def retry_message(conv_id: int, msg_seq: int, body: RetryBody, request: Request, current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    dispatcher = request.app.state.dispatcher

    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT id, model, chatshare_conv_id, last_message_id FROM chat_conversations WHERE id=$1 AND user_id=$2", conv_id, current_user["id"]
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Find the AI message to retry
        ai_msg = await conn.fetchrow(
            "SELECT id,seq,role FROM chat_messages WHERE conversation_id=$1 AND seq=$2 AND role='assistant' AND (replaced IS NULL OR replaced=false)",
            conv_id, msg_seq,
        )
        if not ai_msg:
            raise HTTPException(status_code=404, detail="AI message not found")

        # Mark this AI message as replaced
        await conn.execute(
            "UPDATE chat_messages SET replaced=true WHERE id=$1", ai_msg["id"]
        )

        # MinIO: mark single replaced
        try:
            storage = get_storage()
            await run_sync(storage.mark_single_replaced, current_user["id"], current_user["username"], conv_id, msg_seq)
        except Exception as e:
            logger.error(f"MinIO mark single replaced failed: {e}")

        use_model = body.model or conv["model"]
        chatshare_conv_id = conv["chatshare_conv_id"]
        last_msg_id = conv["last_message_id"]

        # If instruction provided, find the user message before this AI msg and modify
        if body.instruction:
            user_msg = await conn.fetchrow(
                "SELECT id,seq,content FROM chat_messages WHERE conversation_id=$1 AND seq<$2 AND role='user' AND (replaced IS NULL OR replaced=false) ORDER BY seq DESC LIMIT 1",
                conv_id, msg_seq,
            )
            if user_msg:
                modified_content = user_msg["content"] + "\n\n" + body.instruction
                await conn.execute("UPDATE chat_messages SET replaced=true WHERE id=$1", user_msg["id"])
                next_seq = await _get_next_seq(conn, conv_id)
                await conn.execute(
                    "INSERT INTO chat_messages (conversation_id,role,content,seq,replaced) VALUES ($1,'user',$2,$3,false)",
                    conv_id, modified_content, next_seq,
                )
                try:
                    storage = get_storage()
                    await run_sync(storage.mark_single_replaced, current_user["id"], current_user["username"], conv_id, user_msg["seq"])
                    minio_msg = {
                        "seq": next_seq, "role": "user", "content": modified_content,
                        "timestamp": datetime.utcnow().isoformat() + "Z", "replaced": False,
                    }
                    await _save_to_minio(current_user["id"], current_user["username"], conv_id, minio_msg)
                except Exception as e:
                    logger.error(f"MinIO retry user msg failed: {e}")

        await conn.execute("UPDATE chat_conversations SET model=$1, updated_at=NOW() WHERE id=$2", use_model, conv_id)

    # If we have chatshare_conv_id, use variant action (native ChatShare retry)
    if chatshare_conv_id and last_msg_id:
        return StreamingResponse(
            _do_variant_stream(request, dispatcher, conv_id, chatshare_conv_id, last_msg_id, use_model, current_user["id"], current_user["username"]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Fallback: no chatshare IDs, use regular stream with history
    async with pool.acquire() as conn:
        history = await conn.fetch(
            "SELECT role,content FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false) ORDER BY created_at ASC",
            conv_id,
        )
    messages = [{"role": r["role"], "content": r["content"]} for r in history]

    return StreamingResponse(
        _do_stream(request, dispatcher, conv_id, messages, use_model, current_user["id"], current_user["username"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── File upload proxy ─────────────────────────────────────────────────────────

@router.post("/backend-api/files")
async def proxy_file_upload(request: Request, current_user: dict = Depends(get_current_user)):
    """透传文件登记到 ChatShare（JSON 元信息，不走 multipart）"""
    dispatcher = request.app.state.dispatcher
    session = None
    try:
        session = await dispatcher.get_sass_session()
        session.is_busy = True
        sentinel_token = await session.get_sentinel_token()

        payload = await request.json()
        file_name = str(payload.get("file_name") or payload.get("filename") or "").strip()
        file_size = int(payload.get("file_size") or payload.get("size") or 0)
        use_case = str(payload.get("use_case") or "multimodal").strip() or "multimodal"
        timezone_offset_min = int(payload.get("timezone_offset_min", -480))
        reset_rate_limits = bool(payload.get("reset_rate_limits", False))

        if not file_name or file_size <= 0:
            raise HTTPException(status_code=400, detail="file_name/file_size 无效")

        files_req = {
            "file_name": file_name,
            "file_size": file_size,
            "use_case": use_case,
            "timezone_offset_min": timezone_offset_min,
            "reset_rate_limits": reset_rate_limits,
        }

        auth_headers = session.get_conversation_headers(sentinel_token)
        auth_headers["Content-Type"] = "application/json"
        auth_headers.pop("Accept", None)

        upload_api_url = f"{session.sass_url}/backend-api/files"
        _log_upstream_request(upload_api_url, files_req)
        resp = await session._client.post(upload_api_url, json=files_req, headers=auth_headers, timeout=60)

        if resp.status_code == 401:
            logger.warning("File register 401, refreshing session")
            session.is_busy = False
            session = await dispatcher._create_sass_session()
            session.is_busy = True
            sentinel_token = await session.get_sentinel_token()
            auth_headers = session.get_conversation_headers(sentinel_token)
            auth_headers["Content-Type"] = "application/json"
            auth_headers.pop("Accept", None)
            resp = await session._client.post(upload_api_url, json=files_req, headers=auth_headers, timeout=60)

        result = resp.json()
        _log_upstream_response(upload_api_url, resp.status_code, json.dumps(result, ensure_ascii=False))

        file_id = result.get("file_id") or result.get("id")
        upload_url = result.get("upload_url")
        if isinstance(upload_url, str) and upload_url:
            try:
                from urllib.parse import urlparse
                purl = urlparse(upload_url)
                if purl.path.startswith("/file_upload/"):
                    result["upload_url_origin"] = upload_url
                    result["upload_proxy_url"] = purl.path + (("?" + purl.query) if purl.query else "")
                    result["upload_url"] = result["upload_proxy_url"]
            except Exception:
                pass

        logger.info(f"File upload proxy: status={resp.status_code}, file_id={file_id or 'N/A'}, response={json.dumps(result, ensure_ascii=False)[:200]}")

        if file_id and session:
            fmap = _file_session_map(request)
            fmap[file_id] = {"session": session, "ts": datetime.utcnow().timestamp()}

        try:
            if file_id:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO proxy_files (user_id, file_id, filename, mime_type, size_bytes) VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
                        current_user["id"], file_id, file_name, payload.get("mime_type", ""), file_size,
                    )
        except Exception as e:
            logger.error(f"Failed to record file info: {e}")

        return JSONResponse(content=result, status_code=resp.status_code)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload proxy error: {e}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")
    finally:
        if session:
            session.is_busy = False


@router.post("/backend-api/files/process_upload_stream")
async def proxy_process_upload_stream(request: Request, current_user: dict = Depends(get_current_user)):
    """透传上传确认阶段（Step 3），优先复用与 file_id 绑定的会话。"""
    dispatcher = request.app.state.dispatcher
    session = None
    try:
        body = await request.body()
        payload = {}
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}
        file_id = payload.get("file_id")

        fmap = _file_session_map(request)
        bound = fmap.get(file_id) if file_id else None
        if bound and bound.get("session"):
            session = bound["session"]
        else:
            session = await dispatcher.get_sass_session()
        session.is_busy = True

        sentinel_token = await session.get_sentinel_token()
        headers = session.get_conversation_headers(sentinel_token)
        headers["Content-Type"] = "application/json"

        process_url = f"{session.sass_url}/backend-api/files/process_upload_stream"
        _log_upstream_request(process_url, payload)
        resp = await session._client.post(
            process_url,
            headers=headers,
            content=body,
            timeout=120,
        )
        _log_upstream_response(process_url, resp.status_code, resp.content[:400])

        resp_ct = resp.headers.get("content-type", "application/json")
        return Response(content=resp.content, status_code=resp.status_code, media_type=resp_ct.split(";")[0])
    except Exception as e:
        logger.error(f"process_upload_stream proxy error: {e}")
        raise HTTPException(status_code=500, detail=f"process_upload_stream 透传失败: {str(e)}")
    finally:
        if session:
            session.is_busy = False


@router.api_route("/backend-api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_backend_api(path: str, request: Request, current_user: dict = Depends(get_current_user)):
    """通配透传 backend-api 其余接口（含多阶段上传）"""
    dispatcher = request.app.state.dispatcher
    session = None
    try:
        session = await dispatcher.get_sass_session()
        session.is_busy = True
        sentinel_token = await session.get_sentinel_token()

        upstream_url = f"{session.sass_url}/backend-api/{path}"
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

        headers = session.get_conversation_headers(sentinel_token)
        content_type = request.headers.get("content-type")
        if content_type:
            headers["Content-Type"] = content_type

        body = await request.body()
        _log_upstream_request(upstream_url, body)
        resp = await session._client.request(
            request.method,
            upstream_url,
            headers=headers,
            content=body if body else None,
            timeout=120,
        )
        _log_upstream_response(upstream_url, resp.status_code, resp.content[:400])

        # 401 retry once
        if resp.status_code == 401:
            logger.warning(f"Wildcard proxy 401 on {path}, refreshing session")
            session.is_busy = False
            session = await dispatcher._create_sass_session()
            session.is_busy = True
            sentinel_token = await session.get_sentinel_token()
            headers = session.get_conversation_headers(sentinel_token)
            if content_type:
                headers["Content-Type"] = content_type
            resp = await session._client.request(
                request.method,
                upstream_url,
                headers=headers,
                content=body if body else None,
                timeout=120,
            )

        resp_ct = resp.headers.get("content-type", "application/json")
        return Response(content=resp.content, status_code=resp.status_code, media_type=resp_ct.split(";")[0])

    except Exception as e:
        logger.error(f"Wildcard backend-api proxy error ({path}): {e}")
        raise HTTPException(status_code=500, detail=f"backend-api 透传失败: {str(e)}")
    finally:
        if session:
            session.is_busy = False


@router.api_route("/file_upload/{path:path}", methods=["PUT", "POST", "OPTIONS"])
async def proxy_file_upload_object(path: str, request: Request, current_user: dict = Depends(get_current_user)):
    """透传文件对象上传阶段（Step 2）"""
    dispatcher = request.app.state.dispatcher
    session = None
    try:
        incoming_file_id = path

        fmap = _file_session_map(request)
        bound = fmap.get(incoming_file_id)
        if bound and bound.get("session"):
            session = bound["session"]
        else:
            session = await dispatcher.get_sass_session()
        session.is_busy = True
        sentinel_token = await session.get_sentinel_token()

        upstream_url = f"{session.sass_url}/file_upload/{incoming_file_id}"
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

        headers = session.get_conversation_headers(sentinel_token)
        content_type = request.headers.get("content-type", "application/octet-stream")
        headers["Content-Type"] = content_type
        headers.pop("Accept", None)

        body = await request.body()
        _log_upstream_request(upstream_url, body)
        resp = await session._client.request(
            request.method,
            upstream_url,
            headers=headers,
            content=body if body else None,
            timeout=120,
        )
        _log_upstream_response(upstream_url, resp.status_code, resp.content[:400])

        if resp.status_code == 401:
            logger.warning(f"file_upload proxy 401 on {path}, refreshing session")
            session.is_busy = False
            session = await dispatcher._create_sass_session()
            session.is_busy = True
            sentinel_token = await session.get_sentinel_token()
            headers = session.get_conversation_headers(sentinel_token)
            headers["Content-Type"] = content_type
            headers.pop("Accept", None)
            resp = await session._client.request(
                request.method,
                upstream_url,
                headers=headers,
                content=body if body else None,
                timeout=120,
            )

        raw = resp.content or b""
        lower = raw.lower()
        # Guard against pseudo-success: HTTP 201 but body says Unauthorized/error
        if resp.status_code in (200, 201, 204) and (b"unauthorized" in lower or b'"detail":"unauthorized"' in lower or b'"error"' in lower):
            logger.error(f"file_upload pseudo-success rejected: status={resp.status_code}, body={raw[:200]}")
            raise HTTPException(status_code=401, detail="文件对象上传鉴权失败")

        resp_ct = resp.headers.get("content-type", "application/octet-stream")
        return Response(content=raw, status_code=resp.status_code, media_type=resp_ct.split(";")[0])

    except Exception as e:
        logger.error(f"file_upload proxy error ({path}): {e}")
        raise HTTPException(status_code=500, detail=f"file_upload 透传失败: {str(e)}")
    finally:
        if session:
            session.is_busy = False
