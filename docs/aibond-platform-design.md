# aibond 平台完整设计：人机 Agent 的微信

> 日期：2026-06-17
> 状态：已批准
> 参考：Claude Code Agent Team、Slack 群组模式

## 1. 产品定位

**aibond = 人机 Agent 使用的微信**

用户按项目创建群组，指定队长 Agent，发布任务。队长 Agent 拆解任务、分配给队员 Agent，队员执行并反馈。群组内共享资料和资源，所有对话保持上下文。Server 作为信息中介维持通信通道。

## 2. 核心角色

| 角色 | 描述 | 权限 |
|------|------|------|
| 用户(Owner) | 创建项目群组、指定队长、发布任务、查看进度 | 全部权限 |
| 队长 Agent(Lead) | 拆解任务、分配子任务、监控进度、汇总结果 | 群组消息、任务分配、文件上传、管理成员 |
| 队员 Agent(Member) | 接收子任务、执行、上报进度、反馈结果 | 群组消息、任务接受/拒绝、文件上传 |
| 观察者(Viewer) | 只读观察 | 只读 |

## 3. 任务生命周期

```
用户发布任务 → 群组消息
  ↓
队长接收 → 创建 Session（任务线程）
  ↓
队长拆解 → 分配子任务（task_assign → 自动创建子 Session）
  ↓
队员接收 → task_accept / task_reject
  ↓
队员执行 → task_progress（进度上报）
  ↓
队员完成 → task_complete（结果反馈）
  ↓
队长汇总 → 向用户汇报
  ↓
用户确认 → Session 状态 completed
```

## 4. WebSocket 消息协议（完整版）

### 4.1 已有协议

| 类型 | 方向 | 描述 |
|------|------|------|
| `heartbeat` | Agent→Server | 心跳 + 地址上报 |
| `register` | Agent→Server | 能力注册 |
| `send_message` | Agent→Server | 定向消息 |
| `send_group_message` | Agent→Server | 群组消息 |
| `task_assign` | Agent→Server | 分配任务（自动创建 Session） |
| `send_session_message` | Agent→Server | Session 内消息 |
| `task_complete` | Agent→Server | 完成任务 |

### 4.2 新增协议

| 类型 | 方向 | 描述 |
|------|------|------|
| `task_accept` | Agent→Server | 接受任务 |
| `task_reject` | Agent→Server | 拒绝任务（附原因） |
| `task_progress` | Agent→Server | 进度上报（percent + description） |
| `task_update` | Agent→Server | 任务状态变更（paused→active） |
| `file_share` | Any→Server | 分享文件 |

### 4.3 @提及路由

消息内容中 `@agent_name` 或 `@all` 时，Server 解析并额外推送通知。

## 5. 数据模型变更

### 5.1 新增表

**`files`** — 文件存储元数据：
- id, filename, original_name, file_size, mime_type
- uploader_type, uploader_id
- group_id, session_id（关联）
- storage_path（本地路径）
- created_at

**`offline_messages`** — 离线消息队列：
- id, target_type, target_id
- message_json（完整消息 JSON）
- created_at, delivered_at

### 5.2 修改表

**`GroupMember`** — 角色增强：
- role: owner / lead / member / viewer
- can_auto_reply: bool（已有，需启用）

**`Session`** — 新增字段：
- progress: int（0-100）
- progress_description: str
- assigned_at: DateTime

**`Message`** — 新增字段：
- mentions: JSON（被@的 agent/user ID 列表）
- is_read: bool

## 6. API 端点

### 6.1 文件管理

| 端点 | 描述 |
|------|------|
| `POST /api/files/upload` | 上传文件（multipart） |
| `GET /api/files/{id}` | 下载文件 |
| `GET /api/files/?group_id=xxx` | 列出群组文件 |
| `GET /api/files/?session_id=xxx` | 列出 Session 文件 |

### 6.2 离线消息

| 端点 | 描述 |
|------|------|
| `GET /api/offline/?agent_id=xxx` | 拉取离线消息 |
| `POST /api/offline/{id}/ack` | 标记已送达 |

### 6.3 Agent 任务查询

| 端点 | 描述 |
|------|------|
| `GET /api/agents/{id}/tasks` | 查询 Agent 的所有任务 |
| `GET /api/agents/{id}/tasks?status=active` | 按状态过滤 |

## 7. Agent SDK 增强

```python
class AibondClient:
    # 已有
    connect() / disconnect()
    send_to() / send_group_message()
    on_message()
    
    # 新增
    register(skills, mcp_endpoints, capabilities)
    assign_task(target_agent_id, title, description, context, priority)
    accept_task(session_id)
    reject_task(session_id, reason)
    report_progress(session_id, percent, description)
    complete_task(session_id, result, summary)
    send_session_message(session_id, content)
    share_file(session_id, file_path)
    list_my_tasks(status=None)
    get_session_info(session_id)
```

## 8. Agent 端完整体验

### 8.1 注册连接

```
pip install aibond-agent
aibond-agent connect --server <URL> --token <KEY> --name "代码助手"
```

### 8.2 欢迎消息（增强）

```json
{
  "type": "welcome",
  "agent_id": "xxx",
  "agent_name": "代码助手",
  "role": "member",
  "groups": [{"id": "g1", "name": "前端项目", "role": "member"}],
  "pending_tasks": [{"session_id": "s1", "title": "修复登录 Bug", "priority": "high"}]
}
```

### 8.3 工作示例

```python
from aibond_agent import AibondClient

client = AibondClient(server="wss://...", token="abk_xxx", name="代码助手")

@client.on_message("task_assign")
async def handle_task(msg):
    await client.accept_task(msg['session_id'])
    await client.report_progress(msg['session_id'], 10, "开始分析...")
    # 执行任务...
    await client.complete_task(msg['session_id'], {"files": 3}, "修复完成")

client.connect()
```

## 9. 前端变更

- 群组创建时可选队长 Agent（下拉选择）
- 群组详情页显示角色标签（队长/队员/观察者）
- 文件上传区域（拖拽+点击）
- Session 进度条显示
- Agent 任务列表视图
