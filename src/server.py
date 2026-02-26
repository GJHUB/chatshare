import uuid
import json
import logging
import asyncio
import os

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .state import auth, dispatcher, usage_tracker
from .converter import resolve_model, openai_to_backend, build_non_stream_response, MODEL_MAP, SSEParser
from .config import API_KEYS, ADMIN_KEY
from .db import get_pool, close_pool
from .web_routes import router as web_router

logger = logging.getLogger(__name__)

app = FastAPI(title="ChatShare Proxy", version="1.0.0")

# Static files
_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Web API routes
app.include_router(web_router)


# --- 依赖 ---

async def verify_api_key(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
    else:
        key = auth_header
    if key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key


async def verify_admin(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    key = auth_header[7:] if auth_header.startswith("Bearer ") else auth_header
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Admin access required")
    return key


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


# --- 页面路由 ---

@app.get("/")
async def index():
    return RedirectResponse(url="/static/index.html")

@app.get("/login")
async def login_page():
    return RedirectResponse(url="/static/login.html")


# --- API 路由 ---

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, api_key: str = Depends(verify_api_key)):
    if not usage_tracker.check_rate_limit(api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    channel, chatshare_model = resolve_model(request.model)

    if channel not in ("gpt",):
        raise HTTPException(status_code=503, detail=f"模型 {request.model} 暂不支持通过 /v1/chat/completions 调用，请使用 Web 界面")

    from .dispatcher import NoCarAvailableError
    try:
        car_session = await dispatcher.select_car(channel)
    except NoCarAvailableError as e:
        raise HTTPException(status_code=503, detail=str(e))

    car_session.is_busy = True
    usage_tracker.record(api_key, request.model)

    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    backend_request = openai_to_backend(messages, chatshare_model, stream=True)

    if request.stream:
        return StreamingResponse(
            stream_response(car_session, backend_request, request.model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        backend_request["stream"] = True
        result = await non_stream_response(car_session, backend_request, request.model)
        return JSONResponse(content=result)


@app.get("/v1/models")
async def list_models(api_key: str = Depends(verify_api_key)):
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "owned_by": "chatshare"}
            for model in MODEL_MAP.keys()
        ],
    }


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

    # Init DB pool
    try:
        await get_pool()
        logger.info("Database pool ready")
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
