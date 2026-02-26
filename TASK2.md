你是一个开发者，需要继续开发 chatshare-proxy 项目。

项目位置：/root/projects/chatshare-proxy/
PRD 文档：/root/projects/chatshare-proxy/PRD.md
Web 前端 PRD：/root/.openclaw/agents/shared/workspace/chatshare-web-prd.md

当前项目已有基础代码可以运行，但需要以下改进：

## 1. 已发现的问题和修复

- ChatShare 密码加密方式：AES-256-CFB128，key 是字符串 "0a1b2c3d4e5f6071829aabbccddee123" 直接作为 32 字节 key，随机 IV 拼在密文前面，base64 输出
- 登录接口需要带 timestamp 参数
- API 返回数据在 respData 字段而不是 data 字段
- enter_car 返回的是字符串 URL，不是 dict
- enter_car 返回 gfsessionid cookie，需要用这个 cookie 访问 backend-api
- SSE 响应使用 delta encoding v1 格式：首次是 "o":"add" 完整消息，后续是 "o":"patch" 增量，用 "o":"append" 往 parts/0 追加文本

## 2. sass-node2 完整接口分析（已实测验证通过）

ChatShare 有两种节点：
- **gpt-node2**（`gpt-node2.chatshare.biz`）：GPT 系列模型，通过 xy channel 进车获取
- **sass-node2**（`sass-node2.chatshare.biz`）：Claude/Deepseek/Grok/Gemini 等第三方模型

### 2.1 sass-node2 认证方式

sass-node2 使用独立的认证体系，不走 gpt-node2 的 gfsessionid：

**必需的认证信息：**
- `Authorization: Bearer <JWT>` — RS256 JWT，client_id 为 "SoruxGPT Nexus"
- Cookie `token` 和 `authorization` — HS256 JWT，包含 user_id 和 user_name
- Cookie `gfsessionid` — 会话 ID，绑定特定对话
- Cookie `oai-did` — 设备 ID
- Header `oai-device-id` — 同 oai-did
- Header `oai-language: zh-CN`

**获取方式：** 通过 `POST /share-login/v1/user/home/enter` 进入 sass-node2 的车辆后，从返回的跳转 URL 和 cookie 中获取。Bearer JWT 是 ChatShare 平台统一分发的。

### 2.2 sass-node2 对话流程（3步）

**Step 1: Prepare**
```
POST https://sass-node2.chatshare.biz/backend-api/f/conversation/prepare
Headers: Authorization, Cookie, oai-device-id, oai-language
Body: {"action":"next","fork_from_shared_post":false,"parent_message_id":"client-created-root","model":"<model_slug>","timezone_offset_min":-480,"timezone":"Asia/Shanghai","conversation_mode":{"kind":"primary_assistant"},"system_hints":[],"supports_buffering":true,"supported_encodings":["v1"],"client_contextual_info":{"app_name":"chatgpt.com"}}
Response: {"conduit_token":"saas_nexus_no_token","status":"ok"}
```

**Step 2: Sentinel Finalize**
```
POST https://sass-node2.chatshare.biz/backend-api/sentinel/chat-requirements/finalize
Headers: 同上
Body: {"prepare_token":"You_Find_Me_Ha_Ha_Ha_Created_By_Nexus","turnstile":"MDogU3ludGF4RXJyb3I6IEV4cGVjdGVkICcsJyBvciAnXScgYWZ0ZXIgYXJyYXkgZWxlbWVudCBpbiBKU09OIGF0IHBvc2l0aW9uIDE3IChsaW5lIDEgY29sdW1uIDE4KQ=="}
Response: {"token":"Fuck_You","turnstile":{"required":false},...}
```
注意：prepare_token 和返回的 token 都是硬编码值。

**Step 3: Conversation（SSE 流式）**
```
POST https://sass-node2.chatshare.biz/backend-api/f/conversation
Headers: 同上 + openai-sentinel-chat-requirements-token: Fuck_You
Body: {"action":"next","messages":[{"id":"<uuid>","author":{"role":"user"},"content":{"content_type":"text","parts":["<用户消息>"]}}],"parent_message_id":"client-created-root","model":"<model_slug>","timezone_offset_min":-480,"timezone":"Asia/Shanghai","conversation_mode":{"kind":"primary_assistant"},"supports_buffering":true,"supported_encodings":["v1"]}
Response: SSE 流式，格式同 gpt-node2 的 delta encoding v1
```

**关键区别：**
- URL 路径是 `/backend-api/f/conversation`（多了个 `/f/`），不是 `/backend-api/conversation`
- 需要额外的 `openai-sentinel-chat-requirements-token: Fuck_You` header
- prepare_token 固定为 `"You_Find_Me_Ha_Ha_Ha_Created_By_Nexus"`

### 2.3 sass-node2 模型列表接口

```
GET https://sass-node2.chatshare.biz/backend-api/models?iim=false&is_gizmo=false
Headers: 同上
Response: 完整模型列表 JSON
```

### 2.4 sass-node2 可用模型（已验证）

| 分类 | 模型 slug | 说明 |
|------|-----------|------|
| Codex编程 | GPT-5.2-codex | codex 编程模型 |
| Codex编程 | GPT-5.2-codex-max | codex 长时复杂任务 |
| Codex编程 | GPT-5.3-codex | 最新 codex |
| DeepSeek | Deepseek-V3.2-满血版 | 官网最新 V3.2 |
| DeepSeek | Deepseek-R1-满血版 | V3.2 思考模式 |
| Grok | Grok-3-beta | 128k 上下文 |
| Grok | Grok-4 | 第四代，支持联网 |
| Grok | Grok-4-深度研究 | 深度研究模型 |
| Grok | Grok-4.2-thinking | 最先进思考模型 |
| Grok | Grok-4.2 | 简洁有效 |
| Gemini | Gemini-3.1-Flash | 速度更快 |
| Gemini | Gemini-3.1-pro[联网版，稍慢] | 联网版 |
| Gemini | Gemini-3.1-pro[API版，稳定] | API 稳定版 |
| Claude | Claude code（通用版） | 代码+文案 |
| Claude | Claude-4.6-sonnet（编程版） | 仅代码编程 |
| Claude | Claude-4.6-sonnet（通用版） | 代码+文案 |
| Claude | Claude-opus-4-6（编程版） | 仅代码编程 |
| 即梦 | 即梦3.0视频模型 | 5s 视频 |
| 即梦 | 即梦-4.0/4.1/4.5画图模型 | 图片生成 |
| 谷歌 | Veo_3_1 | 视频生成 |
| 谷歌 | Nano-banana / Nano-banana-Pro | 画图 |
| Sora | 4o-image | 基于 sora 画图 |
| GPT | gpt-5-1-pro / thinking / instant / auto | 5.1 系列 |
| GPT | gpt-5-2-pro / thinking / instant / auto | 5.2 系列 |

### 2.5 重要发现

- sass-node2 前端显示的模型名和后端实际调用的模型可能不同
- 测试发现选择 `Claude-opus-4-6（编程版）` 时，server_ste_metadata 返回的 model_slug 是 `i-mini-m`
- 但对话功能正常，能正常收发消息
- Cookie/session 有效期较短，过期后需要重新获取

## 3. 更新模型映射

需要更新 MODEL_MAP，加入所有实际可用的模型 slug：

### gpt-node2 模型（通过 xy channel 进车）
- gpt-5-2, gpt-5-2-instant, gpt-5-2-thinking, gpt-5-2-pro
- gpt-5-1, gpt-5-1-instant, gpt-5-1-thinking, gpt-5-1-pro
- research, agent-mode

### sass-node2 模型（通过 sass channel 或直接访问）
- Claude-opus-4-6（编程版）
- Claude-4.6-sonnet（编程版）
- Claude-4.6-sonnet（通用版）
- Claude code（通用版）
- Deepseek-V3.2-满血版
- Deepseek-R1-满血版
- Grok-3-beta, Grok-4, Grok-4-深度研究, Grok-4.2-thinking, Grok-4.2
- Gemini-3.1-Flash, Gemini-3.1-pro[联网版，稍慢], Gemini-3.1-pro[API版，稳定]
- GPT-5.2-codex, GPT-5.2-codex-max, GPT-5.3-codex

## 4. 开发任务

请阅读现有代码，理解架构，然后：

1. **新增 sass-node2 支持**：在 dispatcher.py 中添加 sass-node2 的会话管理，包括 prepare → sentinel finalize → conversation 三步流程
2. **更新 converter.py**：支持 sass-node2 的请求/响应格式转换
3. **更新模型映射**：在 config.py 或 converter.py 中更新完整的模型列表
4. **更新 server.py**：根据模型自动路由到 gpt-node2 或 sass-node2
5. **确保代码可以直接运行**

完成后运行：openclaw system event --text "Done: chatshare-proxy sass-node2 support added" --mode now
