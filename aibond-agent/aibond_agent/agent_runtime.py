"""Agent Runtime - 将平台消息转化为 LLM 对话的运行时框架。

核心设计：
- 平台消息 = 用户输入（通过 WebSocket 接收）
- Agent 拥有自己的 LLM 和 Skills
- LLM 根据消息决定调用哪些 Skill
- 执行结果通过 WebSocket 返回平台
- 通信通道长期保持，按需调用

用法::

    from aibond_agent import AgentRuntime
    from aibond_agent.skills import SkillRegistry

    # 注册你的 Skills
    skills = SkillRegistry()
    @skills.register("write_file")
    def write_file(path: str, content: str):
        with open(path, 'w') as f:
            f.write(content)
        return {"status": "ok", "path": path}

    # 启动 Agent（自带 LLM 推理循环）
    agent = AgentRuntime(
        server="https://aib2b.bond",
        token="your-api-key",
        name="CodeAgent",
        skills=skills,
        llm_client=your_llm_client,  # OpenAI / Claude / 本地模型
    )
    await agent.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from aibond_agent.client import AibondClient

logger = logging.getLogger("aibond_agent.runtime")


class SkillRegistry:
    """Skill 注册表 - Agent 的能力集合。"""

    def __init__(self):
        self._skills: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}

    def register(self, name: str, description: str = "", schema: dict = None):
        """装饰器：注册一个 Skill。

        示例::

            @skills.register("write_file", description="写入文件", schema={...})
            def write_file(path: str, content: str):
                ...
        """
        def decorator(func: Callable) -> Callable:
            self._skills[name] = func
            self._schemas[name] = schema or {}
            func._skill_description = description
            return func
        return decorator

    def get(self, name: str) -> Callable | None:
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        """返回所有 Skill 的元信息（用于上报平台）。"""
        return [
            {
                "name": name,
                "description": getattr(func, "_skill_description", ""),
                "schema": self._schemas.get(name, {}),
            }
            for name, func in self._skills.items()
        ]

    def execute(self, name: str, arguments: dict) -> Any:
        """执行指定 Skill。"""
        func = self._skills.get(name)
        if not func:
            raise ValueError(f"Skill not found: {name}")
        return func(**arguments)


class AgentRuntime:
    """Agent 运行时 - 连接平台 + LLM 推理 + Skill 调用。

    消息流::

        平台用户消息 -> WebSocket -> AgentRuntime -> LLM -> 决定调用 Skill
                                                    -> 执行 Skill
                                                    -> 返回结果到平台
    """

    def __init__(
        self,
        server: str,
        token: str,
        name: str,
        skills: SkillRegistry,
        llm_client: Any = None,
        system_prompt: str = "",
    ):
        self.client = AibondClient(server=server, token=token, name=name)
        self.skills = skills
        self.llm_client = llm_client
        self.system_prompt = system_prompt or self._default_system_prompt()
        self._running = False

    def _default_system_prompt(self) -> str:
        """默认系统提示词 - 告诉 LLM 如何与平台交互。"""
        skills_desc = json.dumps(self.skills.list_skills(), ensure_ascii=False, indent=2)
        return f"""你是一个连接到 aibond 平台的 AI Agent。你的任务是通过平台接收用户请求，分析需求，调用合适的 Skill 完成任务，并将结果返回给用户。

## 可用 Skills

{skills_desc}

## 工作原则

1. 收到用户消息后，先分析用户意图
2. 如果需要调用 Skill，使用 function call 格式
3. 执行完成后，用自然语言向用户汇报结果
4. 如果用户只是闲聊，直接回复即可
5. 保持友好、专业的语气

## 响应格式

- 直接回复用户：正常对话文本
- 调用 Skill：使用 tool_call 格式
- 汇报结果：说明做了什么，结果如何
"""

    async def run(self) -> None:
        """启动 Agent 运行时。"""
        self._running = True

        # 注册消息处理器
        self.client.on_message("message")(self._on_message)
        self.client.on_message("task_assign")(self._on_task_assign)
        self.client.on_message("mention")(self._on_mention)

        # 连接成功后自动上报 Skills
        async def on_connected():
            skills_list = [s["name"] for s in self.skills.list_skills()]
            if skills_list:
                await self.client.register(skills=skills_list)
                logger.info("Skills registered: %s", skills_list)

        self.client.on_connected(on_connected)

        # 连接平台（阻塞）
        await self.client.connect()

    async def _on_message(self, msg: dict) -> None:
        """处理群消息 - 等同于用户通过 CLI 对话。"""
        content = msg.get("content", "")
        sender = msg.get("sender_name", "用户")
        group_id = msg.get("group_id")
        msg_id = msg.get("id", "")

        logger.info(f"[消息] {sender}: {content}")

        # 构建对话上下文
        context = {
            "type": "group_message",
            "sender": sender,
            "content": content,
            "group_id": group_id,
            "message_id": msg_id,
        }

        # 让 LLM 处理
        response = await self._llm_process(context)

        # 如果有回复内容，发送回平台
        if response.get("reply"):
            if group_id:
                await self.client.send_group_message(
                    group_id=group_id,
                    content=response["reply"]
                )
            elif msg.get("sender_id"):
                # 私聊场景：回复发送者
                await self.client.send_to(
                    target_id=msg["sender_id"],
                    content=response["reply"],
                    target_type=msg.get("sender_type", "user"),
                )

    async def _on_task_assign(self, msg: dict) -> None:
        """处理任务分配 - 等同于用户下发一个复杂任务。"""
        session_id = msg.get("session_id")
        title = msg.get("title", "")
        description = msg.get("description", "")

        logger.info(f"[任务] {title}: {description}")

        # 接受任务
        await self.client.accept_task(session_id)
        await self.client.report_progress(session_id, 10, "分析任务...")

        # 构建任务上下文
        context = {
            "type": "task",
            "session_id": session_id,
            "title": title,
            "description": description,
        }

        # 让 LLM 处理任务
        try:
            await self.client.report_progress(session_id, 30, "执行中...")
            response = await self._llm_process(context)
            await self.client.report_progress(session_id, 90, "汇总结果...")

            # 完成任务
            await self.client.complete_task(
                session_id=session_id,
                result=response.get("result", {}),
                summary=response.get("reply", "任务完成")
            )
        except Exception as e:
            logger.exception("Task execution failed")
            await self.client.complete_task(
                session_id=session_id,
                result={"error": str(e)},
                summary=f"任务失败: {e}"
            )

    async def _on_mention(self, msg: dict) -> None:
        """处理 @ 提及 - 高优先级响应。"""
        await self._on_message(msg)

    async def _llm_process(self, context: dict) -> dict:
        """调用 LLM 处理用户请求。

        如果没有配置 LLM，使用简单的规则匹配作为 fallback。
        """
        if self.llm_client is None:
            return self._rule_based_process(context)

        # 构建 messages
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]

        try:
            # 调用 LLM（这里假设 llm_client 有 chat_completion 方法）
            result = await self.llm_client.chat_completion(messages)
            return self._parse_llm_response(result)
        except Exception as e:
            logger.exception("LLM call failed")
            return {"reply": f"处理出错: {e}", "result": {}}

    def _rule_based_process(self, context: dict) -> dict:
        """无 LLM 时的规则匹配 fallback。"""
        content = context.get("content", "")
        ctx_type = context.get("type", "")

        if ctx_type == "task":
            title = context.get("title", "未命名任务")
            desc = context.get("description", "")
            return {
                "reply": f"任务 '{title}' 已接受。描述: {desc}\n\n注意：当前未配置 LLM，仅做简单确认。配置 LLM 后可智能处理任务。",
                "result": {"status": "accepted", "title": title},
            }

        # 群消息 / 私聊
        skills_info = ", ".join(s["name"] for s in self.skills.list_skills()) or "（无）"
        lower_content = content.lower()

        if any(kw in content for kw in ["你好", "hello", "hi", "嗨"]):
            return {"reply": f"你好！我是 {self.client.name}，当前在线。我的 Skills: {skills_info}"}

        if any(kw in content for kw in ["技能", "skill", "能力", "能做什么"]):
            skills_detail = "\n".join(f"  - {s['name']}: {s['description']}" for s in self.skills.list_skills())
            return {"reply": f"我的可用 Skills:\n{skills_detail or '  （暂无）'}"}

        if any(kw in content for kw in ["状态", "status", "在线"]):
            return {"reply": f"当前在线，Skills: {skills_info}"}

        if any(kw in content for kw in ["帮助", "help", "？", "?"]):
            return {"reply": f"我是 {self.client.name}，可以帮你完成任务。输入 '技能' 查看我的能力，或直接告诉我你需要什么。"}

        return {"reply": f"收到: {content}\n\n我是 {self.client.name}，当前未配置 LLM。配置 LLM 后我可以更智能地处理你的请求。"}

    def _parse_llm_response(self, result: Any) -> dict:
        """解析 LLM 响应，提取回复文本和 tool calls。"""
        # 这里根据实际 LLM 输出格式解析
        # 简化版本：假设 LLM 返回的是 JSON 格式
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {"reply": result}
        return {"reply": str(result)}

    async def stop(self) -> None:
        """停止 Agent 运行时。"""
        self._running = False
        await self.client.disconnect()
