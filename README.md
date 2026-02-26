# ChatShare API Proxy

> Web 前端版本：v1.4.1（基于 PRD v1.4，hover 显示按钮 + 重试浮层菜单）

ChatShare 大模型共享平台的 API 中转服务。对外暴露标准 OpenAI `/v1/chat/completions` 接口，内部转发到 ChatShare。

## 功能

- 标准 OpenAI API 兼容接口
- 自动选车、负载均衡
- 多用户 API Key 管理
- 流式/非流式响应
- 用量统计与限流

## 快速开始

### 直接运行

```bash
pip install -r requirements.txt
python main.py
```

### Docker

```bash
docker build -t chatshare-proxy .
docker run -d --name chatshare-proxy -p 8100:8100 --env-file .env -v ./config.yaml:/app/config.yaml --restart always chatshare-proxy
```

## 使用

```bash
curl http://localhost:8100/v1/chat/completions \
  -H "Authorization: Bearer sk-huoguo-chatshare2026" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]}'
```

## 配置

- `.env` — ChatShare 账号和服务端口
- `config.yaml` — API Key、调度策略、限流

## 支持的模型

GPT-4o, GPT-4o-mini, o1, o1-mini, o3-mini, Claude 3 系列, Gemini 系列
