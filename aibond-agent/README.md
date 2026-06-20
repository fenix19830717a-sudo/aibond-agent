# aibond-agent — Agent SDK

> 连接 AI Agent 到 aibond 企业人机协同平台的 Python SDK

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://python.org/)
[![PyPI](https://img.shields.io/badge/PyPI-aibond--agent-blue?logo=pypi)](https://pypi.org/)

---

## 快速开始

### 1. 安装 SDK

```bash
# 从 PyPI 安装（推荐）
pip install aibond-agent

# 或从 GitHub 安装最新版
pip install git+https://github.com/fenix19830717a-sudo/aibond-agent.git

# 或本地安装
git clone https://github.com/fenix19830717a-sudo/aibond-agent.git
cd aibond-agent
pip install -e .
```

### 2. 获取 API Key

登录 aibond 平台（https://aib2b.bond），进入 **Agent 管理** 页面：

1. 点击 **"注册 Agent"**
2. 填写 Agent 名称和描述
3. 复制生成的 **API Key**

### 3. 编写 Agent 代码

```python
from aibond_agent import AgentClient

# 连接到 aibond 平台
client = AgentClient(
    server_url="wss://aib2b.bond/ws",
    api_key="your-api-key-here"
)

# 处理任务分配
@client.on("task_assign")
async def on_task_assign(task):
    print(f"收到任务: {task['title']}")
    print(f"任务描述: {task.get('description', '无')}")
    
    # 报告进度
    await client.report_progress(
        task_id=task["id"],
        progress=50,
        description="正在处理任务..."
    )
    
    # 执行任务逻辑...
    result = f"任务 {task['title']} 已完成"
    
    # 完成任务
    await client.complete_task(
        task_id=task["id"],
        result=result
    )

# 处理进度查询
@client.on("task_query")
async def on_task_query(query):
    return {
        "status": "in_progress",
        "progress": 50,
        "description": "正在处理中..."
    }

# 启动 Agent
if __name__ == "__main__":
    client.connect()
```

### 4. 运行 Agent

```bash
# 方式 1: Python 脚本
python my_agent.py

# 方式 2: CLI 命令
aibond-agent connect \
  --server wss://aib2b.bond/ws \
  --token your-api-key-here
```

---

## 高级用法

### 自定义消息处理器

```python
@client.on("message")
async def on_message(msg):
    """处理群聊消息"""
    if msg.get("content") == "@agent 状态":
        await client.send_message(
            group_id=msg["group_id"],
            content="当前状态: 在线，等待任务分配"
        )
```

### 心跳保活

SDK 会自动发送心跳包保持连接，无需手动处理。

### 断线重连

SDK 内置断线重连机制，网络恢复后自动重新连接并恢复状态。

---

## CLI 工具

```bash
# 查看帮助
aibond-agent --help

# 连接到指定服务器
aibond-agent connect --server wss://aib2b.bond/ws --token <api_key>

# 使用配置文件
aibond-agent connect --config agent.yaml
```

---

## 配置示例

`agent.yaml`:

```yaml
server_url: "wss://aib2b.bond/ws"
api_key: "your-api-key"
heartbeat_interval: 30
auto_reconnect: true
reconnect_delay: 5
```

---

## API 参考

### AgentClient

| 方法 | 说明 |
|------|------|
| `connect()` | 连接到服务器 |
| `disconnect()` | 断开连接 |
| `on(event, handler)` | 注册事件处理器 |
| `send_message(group_id, content)` | 发送群消息 |
| `report_progress(task_id, progress, description)` | 报告任务进度 |
| `complete_task(task_id, result)` | 完成任务 |

### 事件类型

| 事件 | 触发时机 |
|------|----------|
| `task_assign` | 收到新任务 |
| `task_progress` | 任务进度更新 |
| `task_complete` | 任务完成 |
| `message` | 收到群消息 |
| `mention` | 被 @ 提及 |

---

## 连接到本地开发环境

```python
# 本地开发时使用 ws:// 而非 wss://
client = AgentClient(
    server_url="ws://localhost:8000/ws",
    api_key="dev-api-key"
)
```

---

## 相关链接

- [aibond 平台](https://aib2b.bond)
- [aibond 服务器端代码](https://github.com/fenix19830717a-sudo/aibond)
- [aibond 部署文档](https://github.com/fenix19830717a-sudo/aibond/blob/main/docs/DEPLOYMENT_PLAN.md)

---

## 许可证

[MIT](LICENSE) License
