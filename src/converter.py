import uuid
import time
import json
import logging

logger = logging.getLogger(__name__)

# 模型映射: 用户传入的模型名 → (node_type, ChatShare model slug)
# node_type: "gpt" = gpt-node2, "sass" = sass-node2
MODEL_MAP = {
    # === GPT 系列（通过 soruxgpt 进车，走 sass-node2）===
    # GPT-5.2 系列
    "gpt-5-2": ("sass", "gpt-5-2"),
    "gpt-5-2-instant": ("sass", "gpt-5-2-instant"),
    "gpt-5-2-thinking": ("sass", "gpt-5-2-thinking"),
    "gpt-5-2-pro": ("sass", "gpt-5-2-pro"),
    # GPT-5.1 系列
    "gpt-5-1": ("sass", "gpt-5-1"),
    "gpt-5-1-instant": ("sass", "gpt-5-1-instant"),
    "gpt-5-1-thinking": ("sass", "gpt-5-1-thinking"),
    "gpt-5-1-pro": ("sass", "gpt-5-1-pro"),
    # 其他 GPT
    "research": ("sass", "research"),
    "agent-mode": ("sass", "agent-mode"),
    # 兼容旧名 → 映射到 5.2
    "gpt-4o": ("sass", "gpt-5-2-instant"),
    "gpt-4o-mini": ("sass", "gpt-5-2-instant"),
    "gpt-4": ("sass", "gpt-5-2"),
    "gpt-3.5-turbo": ("sass", "gpt-5-2-instant"),
    "auto": ("sass", "gpt-5-2"),

    # === sass-node2 模型 ===
    # Claude 系列
    # Opus 和 Code 走 sass-node2（soruxgpt），Sonnet 走 claude-node2（原生 API）
    "claude-opus-4": ("sass", "Claude-opus-4-6（编程版）"),
    "claude-opus": ("sass", "Claude-opus-4-6（编程版）"),
    "claude-4.6-sonnet-code": ("claude", "Claude-4.6-sonnet（编程版）"),
    "claude-4.6-sonnet": ("claude", "Claude-4.6-sonnet（通用版）"),
    "claude-sonnet": ("claude", "Claude-4.6-sonnet（通用版）"),
    "claude-code": ("sass", "Claude code（通用版）"),
    # 也支持直接传 ChatShare 原始 slug
    "Claude-opus-4-6（编程版）": ("sass", "Claude-opus-4-6（编程版）"),
    "Claude-4.6-sonnet（编程版）": ("claude", "Claude-4.6-sonnet（编程版）"),
    "Claude-4.6-sonnet（通用版）": ("claude", "Claude-4.6-sonnet（通用版）"),
    "Claude code（通用版）": ("sass", "Claude code（通用版）"),

    # Deepseek 系列（通过 soruxgpt 进车，走 sass-node2）
    "deepseek-v3": ("sass", "Deepseek-V3.2-满血版"),
    "deepseek-r1": ("sass", "Deepseek-R1-满血版"),
    "Deepseek-V3.2-满血版": ("sass", "Deepseek-V3.2-满血版"),
    "Deepseek-R1-满血版": ("sass", "Deepseek-R1-满血版"),

    # Grok 系列（通过 soruxgpt 进车，走 sass-node2）
    "grok-3": ("sass", "Grok-3-beta"),
    "grok-4": ("sass", "Grok-4"),
    "grok-4-research": ("sass", "Grok-4-深度研究"),
    "grok-4.2-thinking": ("sass", "Grok-4.2-thinking"),
    "grok-4.2": ("sass", "Grok-4.2"),
    "Grok-3-beta": ("sass", "Grok-3-beta"),
    "Grok-4": ("sass", "Grok-4"),
    "Grok-4-深度研究": ("sass", "Grok-4-深度研究"),
    "Grok-4.2-thinking": ("sass", "Grok-4.2-thinking"),
    "Grok-4.2": ("sass", "Grok-4.2"),

    # Gemini 系列（通过 soruxgpt 进车，走 sass-node2）
    "gemini-flash": ("sass", "Gemini-3.1-Flash"),
    "gemini-pro": ("sass", "Gemini-3.1-pro[API版，稳定]"),
    "gemini-pro-web": ("sass", "Gemini-3.1-pro[联网版，稍慢]"),
    "Gemini-3.1-Flash": ("sass", "Gemini-3.1-Flash"),
    "Gemini-3.1-pro[联网版，稍慢]": ("sass", "Gemini-3.1-pro[联网版，稍慢]"),
    "Gemini-3.1-pro[API版，稳定]": ("sass", "Gemini-3.1-pro[API版，稳定]"),

    # Codex 编程系列
    "codex-5.2": ("sass", "GPT-5.2-codex"),
    "codex-5.2-max": ("sass", "GPT-5.2-codex-max"),
    "codex-5.3": ("sass", "GPT-5.3-codex"),
    "GPT-5.2-codex": ("sass", "GPT-5.2-codex"),
    "GPT-5.2-codex-max": ("sass", "GPT-5.2-codex-max"),
    "GPT-5.3-codex": ("sass", "GPT-5.3-codex"),

    # 图片/视频模型（强制走 sass-node2）
    "4o-image": ("sass", "4o-image"),
    "Nano-banana": ("sass", "Nano-banana"),
    "Nano-banana-Pro": ("sass", "Nano-banana-Pro"),
    "即梦-4.0画图模型": ("sass", "即梦-4.0画图模型"),
    "即梦-4.1画图模型": ("sass", "即梦-4.1画图模型"),
    "即梦-4.5画图模型": ("sass", "即梦-4.5画图模型"),
    "Veo_3_1": ("sass", "Veo_3_1"),
    "即梦3.0视频模型": ("sass", "即梦3.0视频模型"),
}


def resolve_model(model: str) -> tuple[str, str]:
    """解析模型名，返回 (node_type, chatshare_model)
    node_type: "gpt" 或 "sass"
    """
    if model in MODEL_MAP:
        return MODEL_MAP[model]
    # 默认走 gpt-node2
    return ("gpt", model)


def _build_context_prompt(messages: list[dict]) -> tuple[str, str]:
    """从消息历史中提取上下文摘要和最后一条用户消息。
    
    将之前的对话历史压缩为一个上下文块，避免直接发送 assistant 回复
    导致模型重复之前的内容，同时保留多轮对话的上下文。
    
    Returns: (context_prefix, last_user_content)
    """
    system_parts = []
    history_pairs = []  # (user_msg, assistant_msg) pairs
    last_user_content = ""
    
    current_user = None
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part["text"])
            content = "\n".join(parts)
        
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            current_user = content
            last_user_content = content
        elif role == "assistant" and current_user:
            history_pairs.append((current_user, content))
            current_user = None
    
    # Build context prefix from history (exclude the last user message)
    context_parts = []
    if system_parts:
        context_parts.append("\n\n".join(system_parts))
    
    # Only include history if there are previous exchanges
    if history_pairs:
        context_parts.append("以下是之前的对话记录，请基于这些上下文回答用户的新问题：")
        for user_msg, ai_msg in history_pairs:
            # Truncate long AI responses to avoid bloat
            ai_summary = ai_msg[:500] + "..." if len(ai_msg) > 500 else ai_msg
            context_parts.append(f"用户: {user_msg}\n助手: {ai_summary}")
    
    context_prefix = "\n\n".join(context_parts) if context_parts else ""
    return context_prefix, last_user_content


def openai_to_backend_gpt(messages: list[dict], model: str, stream: bool = True, conversation_id: str = None, parent_message_id: str = None, attachments: list[dict] = None) -> dict:
    """OpenAI 请求格式 → gpt-node2 backend-api 格式
    
    如果有 conversation_id 和 parent_message_id，透传给 ChatShare 实现历史会话续接。
    否则作为新对话，只发最后一条用户消息。
    """
    # 只发最后一条用户消息
    system_parts = []
    last_user_content = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part["text"])
            content = "\n".join(parts)
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            last_user_content = content

    final_content = last_user_content
    if system_parts and not conversation_id:
        final_content = "\n\n".join(system_parts) + "\n\n" + last_user_content

    backend_messages = [{
        "id": str(uuid.uuid4()),
        "author": {"role": "user"},
        "content": {
            "content_type": "text",
            "parts": [final_content],
        },
    }]
    if attachments:
        backend_messages[0]["metadata"] = {"attachments": attachments}

    result = {
        "action": "next",
        "messages": backend_messages,
        "model": model,
        "parent_message_id": parent_message_id or str(uuid.uuid4()),
        "stream": stream,
    }
    if conversation_id:
        result["conversation_id"] = conversation_id
    return result


def openai_to_backend_sass(messages: list[dict], model: str, conversation_id: str = None, parent_message_id: str = None, attachments: list[dict] = None) -> dict:
    """OpenAI 请求格式 → sass-node2 backend-api/f/conversation 格式
    
    如果有 conversation_id 和 parent_message_id，透传给 ChatShare 实现历史会话续接。
    """
    system_parts = []
    last_user_content = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part["text"])
            content = "\n".join(parts)
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            last_user_content = content

    final_content = last_user_content
    if system_parts and not conversation_id:
        final_content = "\n\n".join(system_parts) + "\n\n" + last_user_content

    message = {
        "id": str(uuid.uuid4()),
        "author": {"role": "user"},
        "content": {
            "content_type": "text",
            "parts": [final_content],
        },
    }

    if attachments:
        normalized_attachments = []
        image_parts = []
        has_image = False
        for item in attachments:
            file_id = item.get("id")
            if not file_id:
                continue
            mime_type = item.get("mime_type", "application/octet-stream")
            name = item.get("name", "file")
            size_bytes = int(item.get("size_bytes", item.get("size", 0)) or 0)
            width = int(item.get("width", 0) or 0)
            height = int(item.get("height", 0) or 0)

            normalized = {
                "id": file_id,
                "size": size_bytes,
                "name": name,
                "mime_type": mime_type,
                "source": "local",
            }
            if width > 0:
                normalized["width"] = width
            if height > 0:
                normalized["height"] = height
            normalized_attachments.append(normalized)

            if mime_type.startswith("image/"):
                has_image = True
                pointer = {
                    "content_type": "image_asset_pointer",
                    "asset_pointer": f"file-service://{file_id}",
                    "size_bytes": size_bytes,
                }
                if width > 0:
                    pointer["width"] = width
                if height > 0:
                    pointer["height"] = height
                image_parts.append(pointer)

        if normalized_attachments:
            message["metadata"] = {"attachments": normalized_attachments}
            if has_image:
                message["content"] = {
                    "content_type": "multimodal_text",
                    "parts": image_parts + [final_content or "请结合附件分析"],
                }

    backend_messages = [message]

    effective_parent_id = parent_message_id or ("client-created-root" if not conversation_id else str(uuid.uuid4()))
    result = {
        "action": "next",
        "messages": backend_messages,
        "parent_message_id": effective_parent_id,
        "model": model,
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_contextual_info": {
            "is_dark_mode": False,
            "time_since_loaded": 2047,
            "page_height": 418,
            "page_width": 1600,
            "pixel_ratio": 2,
            "screen_height": 1000,
            "screen_width": 1600,
            "app_name": "chatgpt.com",
        },
        "enable_message_followups": True,
        "system_hints": [],
        "paragen_cot_summary_display_override": "allow",
        "force_parallel_switch": "auto",
    }
    if conversation_id:
        result["conversation_id"] = conversation_id
    return result


def build_variant_request(conversation_id: str, parent_message_id: str, model: str) -> dict:
    """构造 ChatShare 切换模型重试的 variant 请求体"""
    return {
        "action": "variant",
        "conversation_id": conversation_id,
        "parent_message_id": parent_message_id,
        "model": model,
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "variant_purpose": "comparison_implicit",
        "conversation_mode": {"kind": "primary_assistant"},
        "enable_message_followups": True,
        "system_hints": [],
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_contextual_info": {
            "is_dark_mode": False,
            "time_since_loaded": 2047,
            "page_height": 452,
            "page_width": 1600,
            "pixel_ratio": 2,
            "screen_height": 1000,
            "screen_width": 1600,
            "app_name": "chatgpt.com",
        },
        "paragen_cot_summary_display_override": "allow",
        "force_parallel_switch": "auto",
    }


# 保持向后兼容
def openai_to_backend(messages: list[dict], model: str, stream: bool = True) -> dict:
    """向后兼容的转换函数，默认走 gpt 格式"""
    return openai_to_backend_gpt(messages, model, stream)


def _make_chunk(chunk_id: str, model: str, content: str = None, finish_reason: str = None, role: str = None) -> dict:
    """构造 OpenAI SSE chunk"""
    delta = {}
    if role:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason,
        }],
    }


class SSEParser:
    """解析 ChatShare delta encoding v1 SSE 流（gpt-node2 和 sass-node2 通用）"""

    def __init__(self, model: str, chunk_id: str):
        self.model = model
        self.chunk_id = chunk_id
        self.sent_role = False
        self.assistant_msg_id = None
        self.full_text = ""
        self.conversation_id = None
        self.last_message_id = None

    def parse_line(self, line: str) -> list[str]:
        """解析一行 SSE，返回 OpenAI 格式的 SSE chunks"""
        chunks = []
        if not line.startswith("data: "):
            return chunks

        data_str = line[6:].strip()
        if data_str == "[DONE]":
            finish = _make_chunk(self.chunk_id, self.model, finish_reason="stop")
            chunks.append(f"data: {json.dumps(finish)}\n\n")
            chunks.append("data: [DONE]\n\n")
            return chunks

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return chunks

        if not isinstance(data, dict):
            return chunks

        # Extract conversation_id and message_id for history passthrough
        if "conversation_id" in data and data["conversation_id"]:
            self.conversation_id = data["conversation_id"]
        # v1 delta format: data.v.message.id
        v = data.get("v")
        if isinstance(v, dict):
            msg = v.get("message", {})
            if isinstance(msg, dict) and msg.get("id"):
                self.last_message_id = msg["id"]
            if v.get("conversation_id"):
                self.conversation_id = v["conversation_id"]
        # non-v1 format: data.message.id
        msg_top = data.get("message", {})
        if isinstance(msg_top, dict) and msg_top.get("id"):
            self.last_message_id = msg_top["id"]

        appended_text = self._extract_text(data)
        if appended_text:
            if not self.sent_role:
                role_chunk = _make_chunk(self.chunk_id, self.model, role="assistant")
                chunks.append(f"data: {json.dumps(role_chunk)}\n\n")
                self.sent_role = True
            content_chunk = _make_chunk(self.chunk_id, self.model, content=appended_text)
            chunks.append(f"data: {json.dumps(content_chunk)}\n\n")

        return chunks

    def _extract_text(self, data: dict) -> str:
        """从 delta encoding 数据中提取新增文本"""
        op = data.get("o")
        v = data.get("v")

        # 纯 v 格式（Grok 等模型常用）: {"v":"text"} — 没有 o 和 p
        if op is None and isinstance(v, str) and "p" not in data:
            self.full_text += v
            return v

        # append 格式（sass-node2 常用）: {"o":"append","p":"/message/content/parts/0","v":"text"}
        if op == "append" and isinstance(v, str) and "/parts/" in data.get("p", ""):
            self.full_text += v
            return v

        # patch 格式: {"o":"patch","v":[{"o":"append","p":"/message/content/parts/0","v":"text"},...]}
        if isinstance(v, list):
            text_parts = []
            for patch in v:
                if (isinstance(patch, dict)
                        and patch.get("o") == "append"
                        and "/content/parts/" in patch.get("p", "")
                        and isinstance(patch.get("v"), str)):
                    text_parts.append(patch["v"])
                    self.full_text += patch["v"]
            return "".join(text_parts)

        # add 格式: {"o":"add","v":{"message":{...}}}
        if isinstance(v, dict):
            message = v.get("message", {})
            if not isinstance(message, dict):
                return ""
            author = message.get("author", {})
            if author.get("role") != "assistant":
                return ""
            content_type = message.get("content", {}).get("content_type", "")
            if content_type != "text":
                return ""
            parts = message.get("content", {}).get("parts", [])
            if parts and isinstance(parts[0], str) and parts[0]:
                self.full_text = parts[0]
                return parts[0]

        return ""


def build_non_stream_response(chunk_id: str, model: str, content: str) -> dict:
    """构造非流式 OpenAI 响应"""
    return {
        "id": chunk_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content,
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


class ClaudeSSEParser:
    """解析 Claude.ai 原生 SSE 流"""

    def __init__(self, model: str, chunk_id: str):
        self.model = model
        self.chunk_id = chunk_id
        self.sent_role = False
        self.full_text = ""

    def parse_line(self, line: str) -> list[str]:
        """解析一行 SSE，返回 OpenAI 格式的 SSE chunks"""
        chunks = []
        if not line.startswith("data: "):
            return chunks

        data_str = line[6:].strip()
        if data_str == "[DONE]":
            finish = _make_chunk(self.chunk_id, self.model, finish_reason="stop")
            chunks.append(f"data: {json.dumps(finish)}\n\n")
            chunks.append("data: [DONE]\n\n")
            return chunks

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return chunks

        if not isinstance(data, dict):
            return chunks

        # Claude.ai 格式: {"type":"completion","completion":"文本","stop_reason":null,...}
        if data.get("type") == "completion":
            text = data.get("completion", "")
            stop = data.get("stop_reason")

            if text:
                if not self.sent_role:
                    role_chunk = _make_chunk(self.chunk_id, self.model, role="assistant")
                    chunks.append(f"data: {json.dumps(role_chunk)}\n\n")
                    self.sent_role = True
                self.full_text += text
                content_chunk = _make_chunk(self.chunk_id, self.model, content=text)
                chunks.append(f"data: {json.dumps(content_chunk)}\n\n")

            if stop == "end_turn":
                finish = _make_chunk(self.chunk_id, self.model, finish_reason="stop")
                chunks.append(f"data: {json.dumps(finish)}\n\n")
                chunks.append("data: [DONE]\n\n")

        return chunks


class OpenAISSEParser:
    """解析标准 OpenAI /v1/chat/completions SSE 流（用于 Gemini/Grok/Deepseek 等兼容 API）
    
    上游已经是 OpenAI 格式，只需替换 model 名并收集 full_text。
    """

    def __init__(self, model: str, chunk_id: str):
        self.model = model
        self.chunk_id = chunk_id
        self.sent_role = False
        self.full_text = ""

    def parse_line(self, line: str) -> list[str]:
        chunks = []
        if not line.startswith("data: "):
            return chunks

        data_str = line[6:].strip()
        if data_str == "[DONE]":
            if not self.sent_role:
                return chunks
            finish = _make_chunk(self.chunk_id, self.model, finish_reason="stop")
            chunks.append(f"data: {json.dumps(finish)}\n\n")
            chunks.append("data: [DONE]\n\n")
            return chunks

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return chunks

        if not isinstance(data, dict):
            return chunks

        # 处理错误
        if "error" in data:
            chunks.append(f"data: {json.dumps({'error': data['error']})}\n\n")
            return chunks

        choices = data.get("choices", [])
        if not choices:
            return chunks

        delta = choices[0].get("delta", {})
        finish_reason = choices[0].get("finish_reason")
        role = delta.get("role")
        content = delta.get("content")

        if role and not self.sent_role:
            role_chunk = _make_chunk(self.chunk_id, self.model, role="assistant")
            chunks.append(f"data: {json.dumps(role_chunk)}\n\n")
            self.sent_role = True

        if content:
            if not self.sent_role:
                role_chunk = _make_chunk(self.chunk_id, self.model, role="assistant")
                chunks.append(f"data: {json.dumps(role_chunk)}\n\n")
                self.sent_role = True
            self.full_text += content
            content_chunk = _make_chunk(self.chunk_id, self.model, content=content)
            chunks.append(f"data: {json.dumps(content_chunk)}\n\n")

        if finish_reason:
            finish = _make_chunk(self.chunk_id, self.model, finish_reason=finish_reason)
            chunks.append(f"data: {json.dumps(finish)}\n\n")
            chunks.append("data: [DONE]\n\n")

        return chunks
