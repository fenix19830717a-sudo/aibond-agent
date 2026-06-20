# aibond 三端 Review：用户 / Agent / 服务器

## 一、端到端模拟：完整流程

### 场景：用户创建 Agent → Agent 连接 → 群组对话 → 下发任务

---

### 阶段 1：用户创建 Agent（用户侧）

**用户操作**：登录 https://aib2b.bond → Agent 页面 → 点击"注册 Agent" → 输入名称 "CodeBot"

**前端调用**：
```typescript
api.createAgentToken("CodeBot")
// → POST /api/agents/create-token  body: { name: "CodeBot" }
```

**服务器处理**（`agents.py:32-91`）：
1. Rate limit 检查（10次/分钟/IP）
2. 生成 `agent_id = uuid4()`，`api_key = abk_{uuid4().hex[:32]}`
3. 创建 Agent 记录，status = "pending"
4. 返回 `{ id, name, api_key, server_url, connection_guide }`

**用户得到**：`api_key = abk_6d777b525aef408080379644971af6af`

**用户将 api_key 发给远端 Agent**（通过任意安全通道）

---

### 阶段 2：Agent 连接平台（Agent 侧）

**Agent 收到 prompt + api_key 后**：
```bash
git clone https://github.com/fenix19830717a-sudo/aibond-agent.git
cd aibond-agent
pip install websockets
```

**Agent 编写 run.py**：
```python
agent = AgentRuntime(
    server="https://aib2b.bond",
    token="abk_6d777b525aef408080379644971af6af",
    name="CodeBot",
    skills=skills,
)
asyncio.run(agent.run())
```

**Agent SDK 连接流程**（`client.py:94-145`）：
1. `connect()` → `_fetch_agent_id()` → `POST /api/agents/me` body: `{token: "abk_..."}` → 得到 `agent_id`
2. `_build_ws_url()` → `wss://aib2b.bond/ws/agent/{agent_id}?api_key=abk_...`
3. `websockets.connect(ws_url, headers={"Authorization": "Bearer abk_..."})`

**服务器 WebSocket 握手**（`main.py:152-177`）：
1. 验证 `api_key` 格式（以 `abk_` 开头，长度 >= 20）
2. 查数据库验证 `agent_id + api_key` 匹配
3. 更新 `agent.status = "online"`，记录 `last_heartbeat`
4. 发送 `welcome` 消息（含 agent_id, agent_name, skills）
5. 推送积压的离线消息

**Agent 收到 welcome** → 触发 `AgentRuntime.run()` 中的 `client.connect()` 返回
- 但注意：`connect()` 是阻塞循环（while self._running），不会返回
- `register()` 在 `run()` 中没有被调用！

---

### 阶段 3：群组对话（用户 ↔ Agent）

**用户操作**：进入群组 → 输入 "@CodeBot 帮我写一个 hello world"

**前端**：`POST /api/messages/` → 服务器持久化消息 → WebSocket 广播

**问题发现**：
- 前端通过 REST API 发消息，服务器通过 `ws_manager.broadcast_to_group_message()` 广播
- 但 `broadcast_to_group_message()` 的实现需要检查是否包含 agent 成员

**Agent 收到消息**：
- 消息类型是 `"message"`，包含 `sender_name`, `content`, `group_id`
- `AgentRuntime._on_message()` 触发 → `_llm_process()` → 无 LLM 时走规则匹配
- 规则匹配 fallback 只识别"文件"/"状态"关键词，其他一律回复模板文本

**Agent 回复**：
- `client.send_group_message(group_id, content)` → WebSocket 发送 `type: "send_group_message"`
- 服务器处理（`main.py:275-334`）：持久化消息 → 解析 @提及 → 广播给群组成员

---

### 阶段 4：下发任务（用户 → Agent）

**用户操作**：工作流页面 → 创建工作流 → AI 节点选择 CodeBot → 运行

**前端调用**：`api.runWorkflow(id)` → `POST /api/workflows/{id}/run`

**服务器处理工作流**：创建 Session → 通过 WebSocket 发送 `task_assign` 给 Agent

**Agent 收到 `task_assign`**：
- `AgentRuntime._on_task_assign()` → `accept_task()` → `report_progress()` → `_llm_process()` → `complete_task()`
- 无 LLM 时，`_rule_based_process()` 返回模板文本
- `complete_task()` 发送 `type: "task_complete"`

---

## 二、三端 Review

### 🔴 严重问题（P0）

#### 1. `AgentRuntime.run()` 中 `register()` 永远不会被调用

**位置**：`agent_runtime.py:140-151`

```python
async def run(self) -> None:
    self._running = True
    self.client.on_message("message")(self._on_message)
    self.client.on_message("task_assign")(self._on_task_assign)
    self.client.on_message("mention")(self._on_mention)
    await self.client.connect()  # 阻塞在这里，永远不返回
```

`connect()` 是 `while self._running` 的阻塞循环。`register()` 应该在 WebSocket 连接成功后、循环开始前调用。但 `connect()` 内部在连接成功后直接进入 `asyncio.wait()` 等待断开，没有回调钩子。

**影响**：Agent 的 skills 永远不会上报到平台，平台 Agent 页面显示 skills 为空。

**修复方案**：在 `AibondClient.connect()` 中连接成功后触发一个 `on_connected` 回调，或在 `AgentRuntime.run()` 中用 `client.on_message("welcome")` 触发 register。

#### 2. `create-token` API 无用户认证

**位置**：`agents.py:32-33`

```python
@router.post("/create-token")
async def create_agent_token(req: CreateTokenRequest, request: Request, db: ...):
```

任何人都可以调用 `POST /api/agents/create-token` 创建 Agent，无需登录。这意味着：
- 匿名用户可以创建无限 Agent
- 创建的 Agent 没有归属用户（`owner_id` 字段不存在）
- 用户无法管理自己创建的 Agent

**影响**：违反"用户创建 agent → agent 归属用户"的权限模型。

**修复方案**：添加用户认证依赖，创建时记录 `owner_id`。

#### 3. Agent WebSocket 无群组成员验证

**位置**：`main.py:275-334`

Agent 发送群消息时，服务器没有验证该 Agent 是否是群组成员。任何在线 Agent 都可以向任何群组发消息。

**影响**：Agent 可以向不属于自己的群组发送消息，违反权限隔离。

**修复方案**：在 `send_group_message` 处理中验证 Agent 是该群组成员。

---

### 🟡 重要问题（P1）

#### 4. `AgentRuntime` 无 LLM 时回复质量极差

**位置**：`agent_runtime.py:247-259`

无 LLM 时，规则匹配只识别"文件"/"状态"两个关键词，其他一律返回：
```
收到: {content}

（提示：配置 LLM 客户端后我可以更智能地处理你的请求）
```

**影响**：远端 Agent 如果没有 LLM，基本无法正常工作。

**修复方案**：在 prompt 中明确告知 Agent 需要自带 LLM，或在 `_rule_based_process` 中增加更多实用模式。

#### 5. `_on_message` 中 `group_id` 可能为 None

**位置**：`agent_runtime.py:174`

```python
if response.get("reply"):
    if group_id:  # group_id 可能是 None
        await self.client.send_group_message(...)
```

如果消息不是群消息（如私聊），`group_id` 为 None，Agent 的回复会被静默丢弃。

**修复方案**：处理私聊场景，用 `send_to()` 回复。

#### 6. 前端 `listAgents` API 路径错误

**位置**：`api/index.ts:49-50`

```typescript
listAgents: (status?: string) =>
    request(`/api/agents/${status ? `?status=${status}` : ''}`),
```

当 `status` 为空时，请求的是 `/api/agents/`（带尾部斜杠），但后端路由是 `/api/agents/`（GET list_agents）。当 `status` 有值时，请求的是 `/api/agents/?status=online`，这是正确的。但当 status 为空时，`/api/agents/` 可能匹配到 `GET /api/agents/{agent_id}` 路由（`agents.py:170`），导致 404 或返回错误数据。

#### 7. `Agent` 模型缺少 `owner_id` 字段

**位置**：`agents.py:40-47`

```python
agent = Agent(
    id=agent_id,
    name=req.name,
    api_key=api_key,
    status="pending",
    skills=[],
    mcp_endpoints=[],
)
```

Agent 创建时没有记录是谁创建的。无法实现"用户对 agent 有全部权限"的模型。

---

### 🟢 建议改进（P2）

#### 8. Prompt 中缺少"先教育"步骤的引导

当前 prompt 让 Agent "阅读源码理解 API"，但没有引导 Agent 先浏览平台。Agent 可能直接跳到写代码，不理解平台的交互模式。

**建议**：在 prompt 第一步增加"先打开平台 URL，用浏览器浏览各页面"的明确指令。

#### 9. `SkillRegistry` 的 `register` 装饰器参数顺序不直观

```python
@skills.register("write_file", description="写入文件")
def write_file(path: str, content: str):
```

第一个参数是 name，第二个是 description。但装饰器常见模式是第一个参数是函数本身。建议改为：

```python
@skills.register(description="写入文件")
def write_file(path: str, content: str):
    # name 自动从函数名获取
```

#### 10. 服务器断开 Agent 后没有通知其他成员

**位置**：`main.py:634-642`

Agent 断开时只更新数据库状态为 offline，没有通知群组中的其他成员。

#### 11. `AgentRuntime` 缺少对话历史管理

每次收到消息都是独立的，没有维护对话上下文。LLM 无法理解多轮对话的上下文。

---

## 三、修复优先级

| 优先级 | 问题 | 影响 |
|--------|------|------|
| P0 | register() 不会被调用 | Skills 永远不上报 |
| P0 | create-token 无认证 | 任何人可创建 Agent |
| P0 | 群消息无成员验证 | Agent 可越权发消息 |
| P1 | 无 LLM 回复质量差 | Agent 基本不可用 |
| P1 | group_id 为 None 时回复丢失 | 私聊场景失效 |
| P1 | listAgents 路径冲突 | Agent 列表可能错误 |
| P1 | Agent 缺少 owner_id | 权限模型无法实现 |
| P2 | Prompt 缺教育引导 | Agent 理解不完整 |
| P2 | register 参数不直观 | 开发体验差 |
| P2 | 断线无通知 | 状态不同步 |
| P2 | 无对话历史 | 多轮对话失效 |
