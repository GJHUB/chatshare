import uuid
import json
import logging
import asyncio
import os
import time

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .state import auth, dispatcher, usage_tracker
from .converter import resolve_model, openai_to_backend, build_non_stream_response, MODEL_MAP, SSEParser
from .config import API_KEYS, ADMIN_KEY
from .db import get_pool, close_pool, ensure_schema
from .web_routes import router as web_router, _do_stream

logger = logging.getLogger(__name__)

app = FastAPI(title="ChatShare Proxy", version="1.0.0")

# Static files
_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Web API routes
app.include_router(web_router)


# --- 依赖 ---

async def verify_api_key(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    key = auth_header[7:] if auth_header.startswith("Bearer ") else auth_header
    key = (key or "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if key in API_KEYS:
        return {"api_key": key, "user_id": None, "username": "system"}

    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, username FROM chat_users WHERE api_key=$1", key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return {"api_key": key, "user_id": user["id"], "username": user["username"]}


async def verify_admin(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    key = auth_header[7:] if auth_header.startswith("Bearer ") else auth_header
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Admin access required")
    return key


async def log_api_request(request_id: str, api_ctx: dict, endpoint: str, model: str | None, status_code: int, latency_ms: int, error_code: str | None = None):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO api_requests (id, api_key, user_id, endpoint, model, status_code, latency_ms, error_code)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (id) DO UPDATE
                SET status_code=EXCLUDED.status_code,
                    latency_ms=EXCLUDED.latency_ms,
                    error_code=EXCLUDED.error_code
                """,
                request_id,
                api_ctx.get("api_key"),
                api_ctx.get("user_id"),
                endpoint,
                model,
                status_code,
                latency_ms,
                error_code,
            )
    except Exception as e:
        logger.warning(f"log_api_request failed: {e}")


# --- 请求模型 ---

class ChatMessage(BaseModel):
    role: str
    content: str | list

class ChatRequest(BaseModel):
    model: str = "gpt-4o"
    messages: list[ChatMessage]
    stream: bool = True
    temperature: float | None = None
    max_tokens: int | None = None


class NativeMessagePayload(BaseModel):
    role: str = "user"
    content: str
    attachments: list[dict] = []


class NativeConversationRequest(BaseModel):
    request_id: str | None = None
    model: str = "gpt-4o"
    message: NativeMessagePayload
    stream: bool = True
    response_mode: str = "blocking"


class NativeConversationCreateRequest(BaseModel):
    title: str | None = None
    model: str = "gpt-4o"


# --- 流式响应 ---

async def stream_response(car_session, backend_request: dict, model: str):
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    url = car_session.get_conversation_url()
    headers = car_session.get_headers()
    parser = SSEParser(model, chunk_id)

    try:
        async with car_session._client.stream("POST", url, json=backend_request, headers=headers, timeout=120) as resp:
            if resp.status_code == 401:
                raise HTTPException(status_code=502, detail="ChatShare session expired")
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                for chunk in parser.parse_line(line):
                    yield chunk
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'proxy_error'}})}\n\n"
    finally:
        dispatcher.release_car(car_session)


async def non_stream_response(car_session, backend_request: dict, model: str) -> dict:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    url = car_session.get_conversation_url()
    headers = car_session.get_headers()
    parser = SSEParser(model, chunk_id)

    try:
        async with car_session._client.stream("POST", url, json=backend_request, headers=headers, timeout=120) as resp:
            if resp.status_code == 401:
                raise HTTPException(status_code=502, detail="ChatShare session expired")
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                parser.parse_line(line)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Non-stream error: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        dispatcher.release_car(car_session)

    return build_non_stream_response(chunk_id, model, parser.full_text)


async def _collect_native_stream_text(gen):
    full_text = ""
    error = None
    async for chunk in gen:
        if not isinstance(chunk, str) or not chunk.startswith("data: "):
            continue
        raw = chunk[6:].strip()
        if raw == "[DONE]":
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("error"):
            error = str(obj.get("error"))
            break
        choices = (obj.get("choices") or []) if isinstance(obj, dict) else []
        if choices:
            delta = (choices[0].get("delta") or {})
            piece = delta.get("content")
            if piece:
                full_text += piece
    return full_text, error


# --- 页面路由 ---

@app.get("/")
async def index():
    return RedirectResponse(url="/static/index.html")

@app.get("/login")
async def login_page():
    return RedirectResponse(url="/static/login.html")


# --- API 路由 ---

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, api_ctx: dict = Depends(verify_api_key)):
    started = time.time()
    req_id = f"req_{uuid.uuid4().hex[:12]}"
    api_key = api_ctx["api_key"]
    if not usage_tracker.check_rate_limit(api_key):
        await log_api_request(req_id, api_ctx, "/v1/chat/completions", request.model, 429, int((time.time() - started) * 1000), "RATE_LIMITED")
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    channel, chatshare_model = resolve_model(request.model)

    if channel not in ("gpt",):
        await log_api_request(req_id, api_ctx, "/v1/chat/completions", request.model, 503, int((time.time() - started) * 1000), "UNSUPPORTED_MODEL")
        raise HTTPException(status_code=503, detail=f"模型 {request.model} 暂不支持通过 /v1/chat/completions 调用，请使用 Web 界面")

    from .dispatcher import NoCarAvailableError
    try:
        car_session = await dispatcher.select_car(channel)
    except NoCarAvailableError as e:
        await log_api_request(req_id, api_ctx, "/v1/chat/completions", request.model, 503, int((time.time() - started) * 1000), "NO_CAR_AVAILABLE")
        raise HTTPException(status_code=503, detail=str(e))

    car_session.is_busy = True
    usage_tracker.record(api_key, request.model)

    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    backend_request = openai_to_backend(messages, chatshare_model, stream=True)

    if request.stream:
        await log_api_request(req_id, api_ctx, "/v1/chat/completions", request.model, 200, int((time.time() - started) * 1000), None)
        return StreamingResponse(
            stream_response(car_session, backend_request, request.model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-Id": req_id},
        )
    else:
        backend_request["stream"] = True
        result = await non_stream_response(car_session, backend_request, request.model)
        await log_api_request(req_id, api_ctx, "/v1/chat/completions", request.model, 200, int((time.time() - started) * 1000), None)
        return JSONResponse(content={"request_id": req_id, "data": result})


@app.post("/v1/conversations")
async def create_native_conversation(body: NativeConversationCreateRequest, api_ctx: dict = Depends(verify_api_key)):
    req_id = f"req_{uuid.uuid4().hex[:12]}"
    user_id = api_ctx.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="This API key cannot create conversations")

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO chat_conversations (user_id,title,model) VALUES ($1,$2,$3) RETURNING id,title,model,created_at,updated_at",
            user_id,
            (body.title or "新对话"),
            body.model,
        )
    return {"request_id": req_id, "data": dict(row)}


@app.get("/v1/conversations")
async def list_native_conversations(limit: int = 20, api_ctx: dict = Depends(verify_api_key)):
    req_id = f"req_{uuid.uuid4().hex[:12]}"
    user_id = api_ctx.get("user_id")
    if not user_id:
        raise HTTPException(status_code=403, detail="This API key cannot list conversations")

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id,title,model,updated_at FROM chat_conversations WHERE user_id=$1 ORDER BY updated_at DESC LIMIT $2",
            user_id,
            max(1, min(limit, 100)),
        )
    return {"request_id": req_id, "data": [dict(r) for r in rows]}


@app.post("/v1/conversations/{conversation_id}/messages")
async def native_conversation_message(
    conversation_id: int,
    body: NativeConversationRequest,
    request: Request,
    api_ctx: dict = Depends(verify_api_key),
):
    started = time.time()
    req_id = body.request_id or request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:12]}"
    user_id = api_ctx.get("user_id")
    username = api_ctx.get("username")
    if not user_id:
        await log_api_request(req_id, api_ctx, f"/v1/conversations/{conversation_id}/messages", body.model, 403, int((time.time() - started) * 1000), "FORBIDDEN")
        raise HTTPException(status_code=403, detail="This API key cannot access native conversation endpoints")

    pool = await get_pool()
    dispatcher = request.app.state.dispatcher

    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT id, chatshare_conv_id, last_message_id FROM chat_conversations WHERE id=$1 AND user_id=$2",
            conversation_id,
            user_id,
        )
        if not conv:
            await log_api_request(req_id, api_ctx, f"/v1/conversations/{conversation_id}/messages", body.model, 404, int((time.time() - started) * 1000), "NOT_FOUND")
            raise HTTPException(status_code=404, detail="Conversation not found")

        chatshare_conv_id = conv["chatshare_conv_id"]
        last_msg_id = conv["last_message_id"]

        next_seq = await conn.fetchval(
            "SELECT COALESCE(MAX(seq),0)+1 FROM chat_messages WHERE conversation_id=$1", conversation_id
        )
        await conn.execute(
            "INSERT INTO chat_messages (conversation_id,role,content,seq,replaced,attachments) VALUES ($1,'user',$2,$3,false,$4)",
            conversation_id,
            body.message.content,
            next_seq,
            json.dumps(body.message.attachments or []),
        )

        history = await conn.fetch(
            "SELECT role,content FROM chat_messages WHERE conversation_id=$1 AND (replaced IS NULL OR replaced=false) ORDER BY created_at ASC",
            conversation_id,
        )

        await conn.execute("UPDATE chat_conversations SET model=$1, updated_at=NOW() WHERE id=$2", body.model, conversation_id)

    messages = [{"role": "user", "content": body.message.content}] if chatshare_conv_id else [
        {"role": r["role"], "content": r["content"]} for r in history
    ]

    gen = _do_stream(
        request,
        dispatcher,
        conversation_id,
        messages,
        body.model,
        user_id,
        username,
        chatshare_conv_id=chatshare_conv_id,
        last_message_id=last_msg_id,
        attachments=body.message.attachments or None,
    )

    if body.stream:
        await log_api_request(req_id, api_ctx, f"/v1/conversations/{conversation_id}/messages", body.model, 200, int((time.time() - started) * 1000), None)
        return StreamingResponse(
            gen,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-Id": req_id},
        )

    text, err = await _collect_native_stream_text(gen)
    if err:
        await log_api_request(req_id, api_ctx, f"/v1/conversations/{conversation_id}/messages", body.model, 502, int((time.time() - started) * 1000), "UPSTREAM_ERROR")
        return JSONResponse(status_code=502, content={
            "request_id": req_id,
            "error": {"code": "UPSTREAM_ERROR", "message": err, "retryable": True},
        })

    await log_api_request(req_id, api_ctx, f"/v1/conversations/{conversation_id}/messages", body.model, 200, int((time.time() - started) * 1000), None)
    return {
        "request_id": req_id,
        "data": {
            "conversation_id": conversation_id,
            "message": {"role": "assistant", "content": text},
        },
    }


@app.get("/v1/models")
async def list_models(api_ctx: dict = Depends(verify_api_key)):
    req_id = f"req_{uuid.uuid4().hex[:12]}"
    models = []
    for model, mapped in MODEL_MAP.items():
        mtype = "chat"
        if model in {"4o-image", "Nano-banana", "Nano-banana-Pro", "即梦-4.0画图模型", "即梦-4.1画图模型", "即梦-4.5画图模型"}:
            mtype = "image"
        if model in {"Veo_3_1", "即梦3.0视频模型"}:
            mtype = "video"
        models.append({"id": model, "type": mtype, "status": "active", "provider_model": mapped})
    return {"request_id": req_id, "data": models}


@app.get("/admin/status")
async def admin_status(admin_key: str = Depends(verify_admin)):
    return {
        "cars": dispatcher.get_all_status(),
        "users": usage_tracker.get_all(),
        "token_valid": auth.token is not None,
        "token_age": ((__import__("time").time() - auth.token_time) if auth.token else None),
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- 生命周期 ---

@app.on_event("startup")
async def startup():
    logger.info("ChatShare Proxy starting...")

    # Expose dispatcher on app state for web_routes
    app.state.dispatcher = dispatcher

    # Init DB pool and schema
    try:
        await get_pool()
        await ensure_schema()
        logger.info("Database pool and schema ready")
    except Exception as e:
        logger.error(f"Database init failed: {e}")

    # Init ChatShare auth
    try:
        await auth.ensure_token()
        logger.info("Initial login success")
    except Exception as e:
        logger.error(f"Initial login failed: {e}")

    async def cleanup_loop():
        while True:
            await asyncio.sleep(60)
            try:
                await dispatcher.cleanup_stale()
            except Exception as e:
                logger.warning(f"Cleanup error: {e}")

    asyncio.create_task(cleanup_loop())


@app.on_event("shutdown")
async def shutdown():
    for channel_sessions in dispatcher.car_sessions.values():
        for session in channel_sessions.values():
            await session.close()
    await auth.close()
    await close_pool()
    logger.info("ChatShare Proxy stopped")
