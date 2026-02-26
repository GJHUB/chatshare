# ChatShare Web 前端 - 产品需求文档

> 版本：v1.1（根据 ChatShare 原版界面截图更新）
> 日期：2026-02-23
> 作者：PM Agent

---

## 1. 项目概述

### 1.1 背景
ChatShare API 中转服务（chatshare-proxy）已完成后端开发，对外暴露标准 OpenAI `/v1/chat/completions` 接口。现需要一个前端聊天网页，让团队成员能通过浏览器直接与大模型对话。

### 1.2 目标
- 提供完整的 AI 聊天界面（左侧对话列表 + 右侧聊天区）
- 支持用户登录注册
- 支持多模型切换
- 对话历史持久化存储
- 通过公网 IP 140.143.185.247 访问

### 1.3 技术方案
| 项目 | 选型 | 说明 |
|------|------|------|
| 前端 | 纯 HTML/CSS/JS | 无框架，轻量好维护 |
| 后端 | 集成到 chatshare-proxy（FastAPI） | 新增用户/对话管理 API |
| 数据库 | PostgreSQL 17.7（副机） | 用户、对话、消息表 |
| 部署 | 与 chatshare-proxy 一起 | 主机 140.143.185.247:8100 |

---

## 2. 页面布局

### 2.1 整体结构（参考 ChatShare 原版界面）
```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
├────────────┬─────────────────────────────────────────────────┤
│  左侧边栏  │  ┌─ 模型选择器（下拉）─────────────────────┐   │
│  260px     │  └──────────────────────────────────────────┘   │
│            │                                                 │
│  [新聊天]   │                                                │
│  [搜索聊天] │           消息列表                              │
│            │      （用户消息 + AI 回复）                      │
│  ─────────  │                                                │
│  你的聊天   │      每条 AI 回复底部：                         │
│  - 对话1   │      [复制][点赞][点踩][重新生成]               │
│  - 对话2   │                                                │
│  - 对话3   │                                                │
│  - ...     │                                                │
│            │                                                 │
│  ─────────  │  ┌──────────────────────────────────────────┐  │
│  用户信息   │  │ [+]  输入框（询问任何问题）     [发送]    │  │
│  user/Pro  │  └──────────────────────────────────────────┘  │
├────────────┴─────────────────────────────────────────────────┤
└──────────────────────────────────────────────────────────────┘
```

### 2.2 左侧边栏细节
- 顶部：「新聊天」按钮 + 「搜索聊天」入口
- 中部：「你的聊天」分组，按时间倒序展示对话列表
- 底部：用户头像 + 用户名 + 账户类型
- 每个对话项 hover 显示「重命名」和「删除」操作

### 2.3 顶部模型选择器
- 位于聊天区左上角（非全局顶部栏）
- 下拉展开后分组显示模型（详见 3.4 模型切换）

### 2.4 底部输入框
- 左侧「+」按钮（本期预留位置，不实现附件功能）
- 中间输入框，placeholder：「询问任何问题」
- 右侧发送按钮（圆形，带波纹动效）

### 2.5 登录/注册页
- 简洁的居中卡片式布局
- 支持用户名 + 密码登录
- 支持注册新账号
- 登录后跳转到聊天页

---

## 3. 功能模块

### 3.1 用户系统

#### 3.1.1 注册
- 字段：用户名、密码、昵称（可选）
- 用户名唯一性校验
- 密码最少 6 位
- 注册成功自动登录

#### 3.1.2 登录
- 用户名 + 密码登录
- 返回 JWT Token，存 localStorage
- Token 有效期 7 天
- 过期自动跳转登录页

#### 3.1.3 用户信息
- 每个用户自动分配一个 API Key（用于调用 chatshare-proxy）
- 用户无需感知 API Key 的存在，后端自动处理

### 3.2 对话管理

#### 3.2.1 新建对话
- 点击「新建对话」按钮创建
- 默认标题：取第一条消息的前 20 个字
- 自动切换到新对话

#### 3.2.2 对话列表
- 左侧边栏展示当前用户的所有对话
- 按最后活跃时间倒序排列
- 显示：对话标题 + 最后消息时间
- 支持重命名对话（双击标题编辑）
- 支持删除对话（hover 显示删除图标）

#### 3.2.3 对话切换
- 点击左侧对话项切换
- 切换时加载该对话的历史消息
- 当前对话高亮显示

### 3.3 聊天功能

#### 3.3.1 发送消息
- 输入框支持多行（Shift+Enter 换行，Enter 发送）
- 发送后立即显示用户消息气泡
- 自动滚动到底部

#### 3.3.2 AI 回复（流式）
- 调用 `/v1/chat/completions`（stream=true）
- 实时逐字显示 AI 回复（打字机效果）
- 回复过程中显示「正在思考...」状态
- 支持中途停止生成（Stop 按钮）

#### 3.3.3 消息展示
- 用户消息：简洁文本展示，无气泡背景（参考 ChatGPT 风格）
- AI 回复：左对齐，无气泡，宽幅展示
- 支持 Markdown 渲染（代码块、列表、表格、加粗等）
- 代码块支持语法高亮 + 一键复制
- 每条 AI 回复底部显示操作按钮栏：
  - 复制（复制全文）
  - 点赞 👍
  - 点踩 👎
  - 重新生成 🔄
- 消息之间适当留白，阅读舒适

#### 3.3.4 上下文管理
- 每次请求发送当前对话的完整历史消息
- 可设置上下文长度限制（默认最近 20 条）

### 3.4 模型切换

#### 3.4.1 模型选择器
- 位于聊天区左上角，点击展开下拉面板
- 当前选中的模型名显示在选择器上（如「Gemini-3.1-pro[API版，稳定]」）
- 下拉面板分组展示，部分分组有子菜单（箭头 `>`）：

| 分组 | 模型 | 说明 |
|------|------|------|
| （顶级快捷） | Instant | 即时响应模型 |
| （顶级快捷） | Auto | 自动决定思考时长 |
| （顶级快捷） | Thinking | 深入思考，答案更优 |
| （顶级快捷） | Pro | 专业级研究智能 |
| 传统GPT模型 | → 子菜单 | GPT-4o、GPT-4o-mini 等 |
| Sora图片生成模型 | → 子菜单 | Sora 系列 |
| 谷歌图片视频生成模型 | → 子菜单 | Google 生成系列 |
| 即梦图片视频生成模型 | → 子菜单 | 即梦系列 |
| Claude系列模型 | → 子菜单 | Claude 3 Opus/Sonnet 等 |
| Gemini系列模型 | → 子菜单 | Gemini-3.1-pro 等 |
| Grok系列模型 | → 子菜单 | Grok 系列 |
| Deepseek系列模型 | → 子菜单 | Deepseek 系列 |
| Codex编程系列模型 | → 子菜单 | Codex 编程系列 |

- 具体子菜单内的模型列表，从 ChatShare 的 `/backend-api/models` 接口动态获取
- 如果接口不可用，使用本地配置的静态模型列表作为 fallback
- 切换模型后，新消息使用新模型，不影响历史消息
- 记住用户上次选择的模型（存 localStorage + 数据库）

### 3.5 其他功能

#### 3.5.1 响应式设计
- 桌面端：左侧边栏 + 右侧聊天区
- 移动端（<768px）：侧边栏可收起，汉堡菜单切换
- 输入框自适应高度

#### 3.5.2 主题
- 默认深色主题（参考截图的 ChatShare/ChatGPT 深色风格）
- 配色参考：
  - 背景：#212121（聊天区）、#171717（侧边栏）
  - 文字：#ECECEC（主文字）、#999（次要文字）
  - 输入框：#2F2F2F 圆角矩形
  - 模型选择器：半透明深色背景
- 暂不做主题切换，后续可扩展

#### 3.5.3 快捷键
- `Enter`：发送消息
- `Shift + Enter`：换行
- `Ctrl + N`：新建对话

---

## 4. 后端新增 API

### 4.1 用户相关

```
POST /api/auth/register
  body: { username, password, nickname? }
  → { token, user: { id, username, nickname } }

POST /api/auth/login
  body: { username, password }
  → { token, user: { id, username, nickname } }

GET /api/auth/me
  headers: Authorization: Bearer <token>
  → { id, username, nickname, created_at }
```

### 4.2 对话相关

```
GET /api/conversations
  → [{ id, title, model, updated_at, last_message_preview }]

POST /api/conversations
  body: { title?, model? }
  → { id, title, model, created_at }

PUT /api/conversations/:id
  body: { title? }
  → { id, title }

DELETE /api/conversations/:id
  → { ok: true }
```

### 4.3 消息相关

```
GET /api/conversations/:id/messages
  query: ?limit=50&before=<message_id>
  → [{ id, role, content, model, created_at }]

POST /api/conversations/:id/messages
  body: { content, model }
  → SSE 流式响应（同时保存用户消息和 AI 回复到数据库）
```

注意：`POST /api/conversations/:id/messages` 是核心接口，它会：
1. 保存用户消息到数据库
2. 从数据库加载对话历史
3. 调用 chatshare-proxy 的 `/v1/chat/completions`
4. 流式返回 AI 回复
5. AI 回复完成后保存到数据库

---

## 5. 数据库设计

使用副机 PostgreSQL（100.87.204.122:5432）。

### 5.1 表结构

```sql
-- 用户表
CREATE TABLE chat_users (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(50) UNIQUE NOT NULL,
    password    VARCHAR(255) NOT NULL,  -- bcrypt 哈希
    nickname    VARCHAR(50),
    api_key     VARCHAR(100) UNIQUE NOT NULL,  -- 自动生成的内部 API Key
    created_at  TIMESTAMP DEFAULT NOW()
);

-- 对话表
CREATE TABLE chat_conversations (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES chat_users(id) ON DELETE CASCADE,
    title       VARCHAR(200) DEFAULT '新对话',
    model       VARCHAR(50) DEFAULT 'gpt-4o',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_conversations_user ON chat_conversations(user_id, updated_at DESC);

-- 消息表
CREATE TABLE chat_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,  -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    model           VARCHAR(50),           -- AI 回复时记录使用的模型
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON chat_messages(conversation_id, created_at);
```

### 5.2 数据库用户
- 新建数据库用户 `chatshare`，专用于此项目
- 新建数据库 `chatshare_db`

---

## 6. 前端文件结构

```
chatshare-proxy/
├── static/                  # 前端静态文件
│   ├── index.html           # 主页面（聊天界面）
│   ├── login.html           # 登录/注册页
│   ├── css/
│   │   └── style.css        # 样式
│   ├── js/
│   │   ├── app.js           # 主逻辑（对话管理、消息发送）
│   │   ├── auth.js          # 登录注册逻辑
│   │   ├── api.js           # API 调用封装
│   │   └── markdown.js      # Markdown 渲染（可用 marked.js）
│   └── assets/
│       └── logo.svg         # Logo
├── src/
│   ├── ... (现有模块)
│   ├── db.py                # 数据库连接（新增）
│   ├── models.py            # 数据模型（新增）
│   ├── user_auth.py         # 用户认证（新增）
│   └── web_routes.py        # Web API 路由（新增）
```

---

## 7. 第三方库（前端 CDN）

| 库 | 用途 | CDN |
|---|---|---|
| marked.js | Markdown 渲染 | cdnjs |
| highlight.js | 代码语法高亮 | cdnjs |

不引入其他框架，保持轻量。

---

## 8. 安全设计

| 项目 | 方案 |
|------|------|
| 密码存储 | bcrypt 哈希，不存明文 |
| 用户认证 | JWT Token，7 天有效期 |
| API 保护 | 所有 /api/* 接口需要 JWT |
| XSS 防护 | Markdown 渲染时转义 HTML |
| CORS | 同源部署，无需额外配置 |

---

## 9. 部署方案

### 9.1 访问方式
- 公网 IP：140.143.185.247
- 端口：8100（与 chatshare-proxy 共用）
- 访问地址：`http://140.143.185.247:8100`
- 根路径 `/` 返回聊天页面

### 9.2 静态文件服务
FastAPI 挂载静态文件：
```python
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")
```

### 9.3 路由规则
| 路径 | 说明 |
|------|------|
| `/` | 重定向到 `/static/index.html`（聊天页） |
| `/login` | 重定向到 `/static/login.html`（登录页） |
| `/api/*` | Web API（用户、对话、消息） |
| `/v1/*` | 原有 OpenAI 兼容 API（不变） |
| `/static/*` | 静态资源 |

---

## 10. 开发计划

| 阶段 | 内容 | 预计工时 |
|------|------|----------|
| W1 | 数据库建表 + 用户认证 API | 1.5h |
| W2 | 对话/消息 CRUD API | 2h |
| W3 | 登录/注册页面 | 1h |
| W4 | 聊天界面布局 + 样式 | 2h |
| W5 | 聊天核心逻辑（发送、流式接收、Markdown） | 3h |
| W6 | 对话管理（列表、切换、删除、重命名） | 1.5h |
| W7 | 模型切换 + 响应式适配 | 1h |
| W8 | 联调测试 + 部署 | 1h |

**总计：约 13 小时**

---

## 11. 验收标准

1. ✅ 用户可以注册、登录
2. ✅ 登录后看到完整聊天界面（左侧对话列表 + 右侧聊天区）
3. ✅ 可以新建对话、切换对话、删除对话、重命名对话
4. ✅ 发送消息后 AI 流式回复，逐字显示
5. ✅ 支持 Markdown 渲染和代码高亮
6. ✅ 可以切换模型（GPT/Claude/Gemini）
7. ✅ 对话历史持久化，刷新页面不丢失
8. ✅ 移动端可用
9. ✅ 通过 http://140.143.185.247:8100 可访问

---

## 12. 后续扩展（不在本期）

1. **对话搜索**：搜索历史对话内容
2. **对话分享**：生成分享链接
3. **文件上传**：支持上传图片/文件给模型
4. **管理后台**：用户管理、用量统计
5. **主题切换**：深色/浅色模式
6. **对话导出**：导出为 Markdown/PDF

---

*文档结束*
