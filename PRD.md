# ChatShare API 中转服务 - 产品需求文档

> 版本：v1.0  
> 日期：2026-02-22  
> 作者：PM Agent  

---

## 1. 项目概述

### 1.1 项目背景
ChatShare 是一个大模型共享平台，集成了 ChatGPT、Claude、Gemini 等模型。但该平台单账号只能一人登录，多人同时使用会互踢。需要搭建一个 API 中转服务，实现多人共享同一个 ChatShare 账号。

### 1.2 项目目标
- 对外暴露标准 OpenAI `/v1/chat/completions` 接口
- 内部转发到 ChatShare 的 `backend-api/conversation`
- 支持多人同时使用，互不干扰
- 自动选车（选空闲车辆），用户无感知

### 1.3 核心价值
- **多人共享**：一个 ChatShare 账号多人同时用，不互踢
- **标准接口**：兼容 OpenAI API 格式，任意客户端可接入
- **自动调度**：智能选车，负载均衡
- **零成本**：部署在副机上，无额外费用

---

## 2. ChatShare 接口分析（已实测验证）

### 2.1 认证流程
```
POST /share-login/v1/user/auth/login
  → 返回 JWT Token（cookie: token）
  → 密码加密：AES-CFB，key=0a1b2c3d4e5f6071829aabbccddee123
```

### 2.2 车辆管理
```
GET /share-login/v1/user/home/carpage?channel={channel}&page=1&size=50
  → 返回车辆列表（carid, count, available, plan_type）

POST /share-login/v1/user/home/enter
  → body: {channel, car_id, timestamp, sign}
  → 返回跳转URL（如 https://gpt-node2.chatshare.biz）
```

### 2.3 对话接口
```
POST {chat_url}/backend-api/conversation
  → body: {action, messages, model, parent_message_id, stream}
  → 返回 SSE 流式响应

GET {chat_url}/backend-api/models
  → 返回可用模型列表

GET {chat_url}/backend-api/conversations?offset=0&limit=20
  → 返回对话列表
```

### 2.4 可用 Channel
| Channel | 说明 | 车辆类型 |
|---------|------|----------|
| xy | ChatGPT（主力） | team |
| claude | Claude | pro |
| gemini | Gemini | pro |

### 2.5 可用模型（xy channel 实测）
- GPT-5.2 Pro / Thinking / Instant
- GPT-5.1 Pro / Thinking / Instant
- GPT-4o / GPT-4o-mini
- o1 / o1-mini / o3-mini
- auto（自动选择）

---

## 3. 系统架构

### 3.1 整体流程
```
┌─────────────────────────────────────────────────────────────┐
│                     用户请求                                 │
│                                                             │
│  POST /v1/chat/completions                                  │
│  Authorization: Bearer sk-xxx                               │
│  {"model": "gpt-4o", "messages": [...], "stream": true}     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     中转服务                                 │
│                                                             │
│  1. 验证 API Key                                            │
│  2. 解析 model → 确定 channel（xy/claude/gemini）            │
│  3. 从车辆池选一辆空闲车                                     │
│  4. 转换请求格式（OpenAI → backend-api）                     │
│  5. 转发请求到 ChatShare                                     │
│  6. 转换响应格式（SSE → OpenAI SSE）                         │
│  7. 返回给用户                                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     ChatShare                                │
│                                                             │
│  backend-api/conversation → SSE 流式响应                     │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 技术栈
| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.10+ / Node.js | |
| Web框架 | FastAPI（推荐） | 原生支持 SSE 流式 |
| 部署 | 副机（100.87.204.122） | Docker 或直接运行 |
| 端口 | 8100 | Tailscale 内网访问 |

---

## 4. 功能模块

### 4.1 认证管理模块（auth.py）

#### 功能
- ChatShare 账号登录，维护 Token
- Token 自动刷新（过期前重新登录）
- 多 API Key 管理（给不同用户分配 Key）

#### 接口设计
```python
class ChatShareAuth:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.token = None
        self.token_expiry = None
    
    def login(self) -> str:
        """登录并返回token"""
    
    def ensure_token(self) -> str:
        """确保token有效，过期则重新登录"""
    
    @staticmethod
    def encrypt_password(password: str) -> str:
        """AES-CFB加密密码"""
```

#### API Key 管理
```python
# 配置文件 config.yaml
api_keys:
  - key: "sk-user1-xxxxx"
    name: "火锅"
    rate_limit: 60  # 每分钟请求数
  - key: "sk-user2-xxxxx"
    name: "用户2"
    rate_limit: 30
```

### 4.2 车辆调度模块（dispatcher.py）

#### 功能
- 获取各 channel 的车辆列表
- 智能选车（选 count 最小的可用车辆）
- 车辆会话池管理（复用已进入的车辆 session）
- 车辆健康检查

#### 接口设计
```python
class CarDispatcher:
    def __init__(self, auth: ChatShareAuth):
        self.auth = auth
        self.car_sessions = {}  # {channel: {car_id: session}}
    
    def get_available_cars(self, channel: str) -> list[dict]:
        """获取可用车辆列表，按count排序"""
    
    def select_car(self, channel: str) -> CarSession:
        """
        智能选车：
        1. 优先复用已有session
        2. 没有则选count最小的车
        3. 进入车辆，创建session
        """
    
    def release_car(self, channel: str, car_id: str):
        """释放车辆session"""
    
    def health_check(self):
        """检查所有session是否有效"""
```

#### 选车策略
```python
def select_car(self, channel: str) -> CarSession:
    # 1. 检查是否有空闲的已连接session
    for car_id, session in self.car_sessions.get(channel, {}).items():
        if not session.is_busy:
            return session
    
    # 2. 获取车辆列表，选count最小的
    cars = self.get_available_cars(channel)
    available = [c for c in cars if c['available']]
    if not available:
        raise NoCarAvailableError(f"No available car for {channel}")
    
    best_car = min(available, key=lambda c: c['count'])
    
    # 3. 进入车辆
    session = self._enter_car(channel, best_car['carid'])
    return session
```

### 4.3 格式转换模块（converter.py）

#### 功能
- OpenAI 请求格式 → ChatShare backend-api 格式
- ChatShare SSE 响应 → OpenAI SSE 响应
- 模型名称映射

#### 模型映射
```python
MODEL_MAP = {
    # OpenAI 标准名 → ChatShare model
    "gpt-4o": ("xy", "gpt-4o"),
    "gpt-4o-mini": ("xy", "gpt-4o-mini"),
    "gpt-4": ("xy", "gpt-4o"),
    "gpt-3.5-turbo": ("xy", "gpt-4o-mini"),
    "o1": ("xy", "o1"),
    "o1-mini": ("xy", "o1-mini"),
    "o3-mini": ("xy", "o3-mini"),
    "auto": ("xy", "auto"),
    
    # Claude 系列
    "claude-3-opus": ("claude", "claude-3-opus"),
    "claude-3-sonnet": ("claude", "claude-3-sonnet"),
    "claude-3.5-sonnet": ("claude", "claude-3.5-sonnet"),
    
    # Gemini 系列
    "gemini-pro": ("gemini", "gemini-pro"),
    "gemini-ultra": ("gemini", "gemini-ultra"),
}
```

#### 请求转换
```python
def openai_to_backend(request: dict) -> dict:
    """
    OpenAI格式:
    {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}], "stream": true}
    
    转换为 backend-api 格式:
    {
        "action": "next",
        "messages": [{"id": uuid, "author": {"role": "user"}, 
                      "content": {"content_type": "text", "parts": ["hi"]}}],
        "model": "gpt-4o",
        "parent_message_id": uuid,
        "stream": true
    }
    """
```

#### 响应转换
```python
def backend_sse_to_openai_sse(event_data: str) -> str:
    """
    ChatShare SSE:
    data: {"v": {"message": {"content": {"parts": ["Hello"]}, ...}}}
    
    转换为 OpenAI SSE:
    data: {"id": "chatcmpl-xxx", "object": "chat.completion.chunk",
           "choices": [{"delta": {"content": "Hello"}, "index": 0}]}
    """
```

### 4.4 API 服务模块（server.py）

#### 对外接口

**POST /v1/chat/completions**
```python
@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, api_key: str = Depends(verify_api_key)):
    """
    标准 OpenAI Chat Completions 接口
    支持 stream=true/false
    """
    # 1. 解析model，确定channel
    channel, model = MODEL_MAP.get(request.model, ("xy", "auto"))
    
    # 2. 选车
    car_session = dispatcher.select_car(channel)
    
    # 3. 转换请求
    backend_request = converter.openai_to_backend(request)
    
    # 4. 转发并转换响应
    if request.stream:
        return StreamingResponse(
            stream_response(car_session, backend_request),
            media_type="text/event-stream"
        )
    else:
        return await non_stream_response(car_session, backend_request)
```

**GET /v1/models**
```python
@app.get("/v1/models")
async def list_models(api_key: str = Depends(verify_api_key)):
    """返回可用模型列表"""
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "owned_by": "chatshare"}
            for model in MODEL_MAP.keys()
        ]
    }
```

**GET /admin/status**
```python
@app.get("/admin/status")
async def admin_status(admin_key: str = Depends(verify_admin)):
    """管理接口：查看车辆状态、用户用量"""
    return {
        "cars": dispatcher.get_all_status(),
        "users": usage_tracker.get_all(),
        "token_expiry": auth.token_expiry
    }
```

### 4.5 用量统计模块（usage.py）

#### 功能
- 按 API Key 统计请求次数
- 按模型统计用量
- 限流控制

```python
class UsageTracker:
    def __init__(self):
        self.usage = {}  # {api_key: {model: count, total: count, last_request: time}}
    
    def record(self, api_key: str, model: str):
        """记录一次请求"""
    
    def check_rate_limit(self, api_key: str) -> bool:
        """检查是否超过限流"""
    
    def get_usage(self, api_key: str) -> dict:
        """获取用量统计"""
```

---

## 5. 高可用设计

### 5.1 Token 管理
| 场景 | 处理 |
|------|------|
| Token 过期 | 自动重新登录 |
| 登录失败 | 重试3次，告警通知 |
| 被踢下线 | 检测401，自动重新登录+选车 |

### 5.2 车辆调度
| 场景 | 处理 |
|------|------|
| 车辆满员 | 自动切换到下一辆空闲车 |
| 所有车满 | 返回 503，提示稍后重试 |
| 车辆session失效 | 自动重新进入 |
| 对话超时 | 30秒超时，释放车辆 |

### 5.3 请求重试
```python
@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
async def forward_request(car_session, request):
    """转发请求，失败自动重试（换车）"""
    try:
        return await car_session.send(request)
    except (SessionExpired, CarUnavailable):
        # 重新选车
        car_session = dispatcher.select_car(channel)
        return await car_session.send(request)
```

### 5.4 限流
| 对象 | 限制 | 说明 |
|------|------|------|
| 单用户 | 可配置（默认60次/分钟） | 防止滥用 |
| 全局 | 200次/分钟 | 保护 ChatShare 账号 |

---

## 6. 目录结构

```
chatshare-proxy/
├── src/
│   ├── __init__.py
│   ├── auth.py           # ChatShare认证
│   ├── dispatcher.py     # 车辆调度
│   ├── converter.py      # 格式转换
│   ├── server.py         # FastAPI服务
│   ├── usage.py          # 用量统计
│   └── config.py         # 配置管理
├── config.yaml           # 配置文件
├── .env                  # 环境变量
├── requirements.txt
├── Dockerfile
├── main.py               # 入口
└── README.md
```

---

## 7. 配置

### 7.1 环境变量（.env）
```bash
# ChatShare 账号
CHATSHARE_URL=https://node2.chatshare.biz
CHATSHARE_USERNAME=30T12rGgFUb
CHATSHARE_PASSWORD=991625

# 服务
PROXY_PORT=8100
PROXY_HOST=0.0.0.0

# 管理
ADMIN_KEY=your-admin-key
```

### 7.2 配置文件（config.yaml）
```yaml
# API Keys
api_keys:
  - key: "sk-huoguo-xxxxx"
    name: "火锅"
    rate_limit: 60
  - key: "sk-user2-xxxxx"
    name: "用户2"
    rate_limit: 30

# 车辆调度
dispatcher:
  max_sessions_per_channel: 5    # 每个channel最多同时保持的session数
  session_timeout: 300           # session空闲超时（秒）
  prefer_low_count: true         # 优先选人少的车

# 全局限流
global_rate_limit: 200           # 每分钟
```

---

## 8. 使用方式

### 8.1 客户端接入
```python
# 任何支持 OpenAI API 的客户端都能用
import openai

client = openai.OpenAI(
    api_key="sk-huoguo-xxxxx",
    base_url="http://100.87.204.122:8100/v1"
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "你好"}],
    stream=True
)
for chunk in response:
    print(chunk.choices[0].delta.content, end="")
```

### 8.2 curl 测试
```bash
curl http://100.87.204.122:8100/v1/chat/completions \
  -H "Authorization: Bearer sk-huoguo-xxxxx" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]}'
```

### 8.3 兼容的客户端
- ChatGPT-Next-Web
- LobeChat
- OpenClaw
- 任何支持自定义 OpenAI API Base URL 的工具

---

## 9. 部署

### Docker 部署（推荐）
```bash
docker build -t chatshare-proxy .
docker run -d \
  --name chatshare-proxy \
  -p 8100:8100 \
  --env-file .env \
  -v ./config.yaml:/app/config.yaml \
  --restart always \
  chatshare-proxy
```

### 直接运行
```bash
pip install -r requirements.txt
python main.py
```

---

## 10. 开发计划

| 阶段 | 内容 | 预计工时 |
|------|------|----------|
| M1 | 认证模块（登录+Token管理） | 1h |
| M2 | 车辆调度（选车+session池） | 2h |
| M3 | 格式转换（请求+SSE响应） | 3h |
| M4 | API服务（FastAPI+流式） | 2h |
| M5 | 用量统计+限流 | 1h |
| M6 | Docker部署+测试 | 2h |

**总计：约 11 小时**

---

## 11. 风险与应对

| 风险 | 概率 | 应对 |
|------|------|------|
| ChatShare 改接口 | 低 | 模块化设计，便于适配 |
| 账号被封 | 低 | 控制请求频率 |
| 车辆全满 | 中 | 排队机制，返回503 |
| SSE格式变化 | 低 | 转换层独立，易修改 |

---

## 12. 后续扩展

1. **Web管理面板**：查看用量、管理Key、监控车辆状态
2. **多账号池**：支持多个ChatShare账号轮换
3. **对话历史**：保存对话记录到数据库
4. **Claude/Gemini支持**：扩展到其他channel

---

*文档结束*
