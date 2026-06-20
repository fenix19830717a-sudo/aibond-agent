# aibond 外部 Agent 接入设计

> 日期：2026-06-17
> 状态：已批准

## 1. 问题

当前 MVP 的 Agent 接入链路断裂：
- `aibond_agent` SDK/CLI 包不存在，外部 Agent 无法安装和连接
- Server 只监听 localhost，外部网络不可达
- 注册时只返回 WebSocket URL，缺少安装指引
- Agent 地址变化时无动态更新机制

## 2. 目标

1. 外部 Agent 通过 `pip install aibond-agent` 一行命令安装 SDK 后即可连接
2. 兼容 Python Agent 和 MCP Agent（Claude/Trae/OpenClaw 等）
3. Server 启动时自动创建公网隧道，无需手动配置网络
4. Agent 注册时返回完整的安装+连接指南
5. Agent 地址动态更新，消息通过 Server 中转实现 Agent-to-Agent 通信

## 3. 架构

```
外部 Agent (Python/Trae/Claude/OpenClaw)
    │
    │ pip install aibond-agent
    │ aibond-agent connect --server <公网URL> --token <key>
    │
    ▼
┌─────────────────────────────────────────────┐
│  Cloudflare Tunnel (自动创建)                │
│  wss://xxx.trycloudflare.com → localhost:8000│
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│              aibond Server (FastAPI)         │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│  │ WebSocket│  │ 消息路由  │  │ 隧道管理  │  │
│  │  Manager │→ │  Broker  │  │ (tunnel) │  │
│  └──────────┘  └────┬─────┘  └───────────┘  │
│                      │                       │
│  ┌──────────┐  ┌─────▼─────┐  ┌───────────┐  │
│  │ Agent注册│  │ 离线队列  │  │ HTTP回调  │  │
│  │ + Token  │  │ (SQLite) │  │ (fallback)│  │
│  └──────────┘  └───────────┘  └───────────┘  │
└──────────────────────────────────────────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
    Agent A (WS)  Agent B (WS)  Agent C (HTTP回调)
```

## 4. 交付物

### 4.1 aibond-agent SDK 包

**包结构**：
```
aibond-agent/
├── aibond_agent/
│   ├── __init__.py          # export AibondClient
│   ├── client.py            # WebSocket 客户端 + 自动重连 + 心跳
│   ├── mcp_server.py        # MCP Server（兼容 Claude/Trae）
│   └── cli.py               # CLI: aibond-agent connect / mcp
├── pyproject.toml
└── README.md
```

**三种接入方式**：

1. Python SDK：
```python
from aibond_agent import AibondClient
client = AibondClient(server="wss://xxx.trycloudflare.com", token="abk_xxx")
client.on_message(lambda msg: print(msg))
client.connect()
client.send_to(user_id="xxx", content="你好")
```

2. CLI：
```bash
aibond-agent connect --server wss://xxx --token abk_xxx --name "我的Agent"
```

3. MCP Server（Claude/Trae 配置）：
```json
{"mcpServers":{"aibond":{"command":"aibond-agent","args":["mcp","--server","wss://xxx","--token","abk_xxx"]}}}
```

MCP 暴露工具：`aibond_send_message`, `aibond_list_groups`, `aibond_list_agents`, `aibond_get_messages`

### 4.2 Server 隧道模块

- 启动时自动启动 `cloudflared tunnel --url ws://localhost:8000`
- 解析公网 URL 写入 `settings.PUBLIC_URL`
- 降级：cloudflared 不可用时以 localhost 模式运行并告警
- 配置项：`TUNNEL_ENABLED`, `TUNNEL_PROVIDER`, `PUBLIC_URL`

### 4.3 注册体验升级

注册 Agent 时返回完整连接指南：
```
=== aibond Agent 连接指南 ===
1. 安装：pip install aibond-agent
2. 连接：aibond-agent connect --server <URL> --token <KEY> --name "<NAME>"
3. MCP：{"mcpServers":{"aibond":{"command":"aibond-agent","args":["mcp",...]}}}
Agent ID: xxx  |  API Key: abk_xxx
```

### 4.4 消息中转

Agent-to-Agent 不直连，全部通过 Server 中转：
- 目标在线（WS）→ WS 直接推送
- 目标离线但有 callback_url → HTTP POST 回调
- 目标完全不可达 → 消息入离线队列

Agent 通过心跳上报最新可达地址，Server 始终使用最新地址。
