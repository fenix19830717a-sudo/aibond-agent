"""Aibond Agent Client - WebSocket connection with heartbeat and auto-reconnect."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from typing import Any, Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("aibond_agent")

# Default heartbeat interval in seconds
HEARTBEAT_INTERVAL = 15

# Reconnect backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s (capped)
RECONNECT_BASE_DELAY = 1
RECONNECT_MAX_DELAY = 60


class AibondClient:
    """WebSocket client for connecting to the Aibond server.

    Usage::

        client = AibondClient(server="http://localhost:8000", token="my-api-key", name="my-agent")
        client.on_message(lambda msg: print(msg))
        await client.connect()
    """

    def __init__(self, server: str, token: str, name: str = ""):
        """Initialize the client.

        Args:
            server: Server base URL, e.g. ``http://localhost:8000``.
            token: API key for authentication.
            name: Optional display name for this agent.
        """
        self.server = server.rstrip("/")
        self.token = token
        self.name = name

        self._agent_id: str | None = None
        self._ws: ClientConnection | None = None
        self._message_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._message_callback: Callable[[dict[str, Any]], None] | None = None
        self._type_handlers: dict[str, Callable] = {}
        self._recv_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._on_connected_callback: Callable | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_message(self, msg_type: str = None):
        """装饰器：按消息类型注册回调。

        支持两种用法：

        1. 装饰器模式（推荐）::

            @client.on_message("task_assign")
            async def handle_task(msg):
                ...

            @client.on_message()  # 无参数 = 所有消息
            async def handle_any(msg):
                ...

        2. 直接调用模式（向后兼容）::

            client.on_message(lambda msg: print(msg))
        """
        # 直接调用模式：on_message(callback) —— msg_type 是一个 callable
        if callable(msg_type):
            self._message_callbacks.append(msg_type)
            return msg_type

        # 装饰器模式：on_message("task_assign") 或 on_message()
        def decorator(func):
            if msg_type:
                self._type_handlers[msg_type] = func
            else:
                self._message_callback = func
            return func
        return decorator

    def on_connected(self, func: Callable):
        """Register a callback to be called after WebSocket connects successfully."""
        self._on_connected_callback = func

    async def connect(self) -> None:
        """Connect to the Aibond server.

        1. Calls the REST API to resolve the agent_id from the token.
        2. Opens a WebSocket connection.
        3. Starts the heartbeat and receive loops.
        """
        self._running = True
        self._agent_id = await self._fetch_agent_id()

        ws_url = self._build_ws_url()
        logger.info("Connecting to %s", ws_url)

        backoff = RECONNECT_BASE_DELAY
        while self._running:
            try:
                async with websockets.connect(
                    ws_url,
                    additional_headers={"Authorization": f"Bearer {self.token}"},
                ) as ws:
                    self._ws = ws
                    logger.info("WebSocket connected (agent_id=%s)", self._agent_id)

                    # Trigger on_connected callback if registered
                    if self._on_connected_callback:
                        try:
                            result = self._on_connected_callback()
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            logger.exception("on_connected callback error")

                    backoff = RECONNECT_BASE_DELAY  # reset on success

                    # Start background tasks
                    self._heartbeat_task = asyncio.create_task(
                        self._heartbeat_loop(ws)
                    )
                    self._recv_task = asyncio.create_task(self._recv_loop(ws))

                    # Wait until either task finishes (disconnect)
                    done, _ = await asyncio.wait(
                        [self._heartbeat_task, self._recv_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in done:
                        t.result()  # re-raise exceptions if any

            except ConnectionClosed:
                logger.warning("WebSocket connection closed")
            except Exception:
                logger.exception("WebSocket connection error")

            self._ws = None
            self._cancel_tasks()

            if not self._running:
                break

            logger.info("Reconnecting in %ds ...", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX_DELAY)

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        self._running = False
        if self._ws:
            await self._ws.close()
        self._cancel_tasks()

    async def send_to(
        self,
        target_id: str,
        content: str,
        target_type: str = "user",
    ) -> None:
        """Send a message to a target (user or agent).

        Args:
            target_id: ID of the target.
            content: Message content.
            target_type: ``"user"`` or ``"agent"``.
        """
        await self._send_json({
            "type": "send_message",
            "target_id": target_id,
            "target_type": target_type,
            "content": content,
        })

    async def send_group_message(self, group_id: str, content: str) -> None:
        """Send a message to a group.

        Args:
            group_id: ID of the group.
            content: Message content.
        """
        await self._send_json({
            "type": "send_group_message",
            "group_id": group_id,
            "content": content,
        })

    async def register(self, skills: list = None, mcp_endpoints: list = None, capabilities: dict = None):
        """注册 Agent 能力。

        Args:
            skills: 技能列表。
            mcp_endpoints: MCP 端点列表。
            capabilities: 能力描述字典。
        """
        payload = {
            "type": "register",
            "skills": skills or [],
            "mcp_endpoints": mcp_endpoints or [],
            "capabilities": capabilities or {},
        }
        await self._send(payload)

    async def assign_task(self, target_agent_id: str, title: str, description: str = "",
                          context: dict = None, priority: str = "normal", group_id: str = ""):
        """分配任务给另一个 Agent（自动创建 Session）。

        Args:
            target_agent_id: 目标 Agent ID。
            title: 任务标题。
            description: 任务描述。
            context: 上下文信息。
            priority: 优先级，如 ``"normal"``、``"high"``、``"low"``。
            group_id: 关联的群组 ID。
        """
        payload = {
            "type": "task_assign",
            "target_agent_id": target_agent_id,
            "group_id": group_id,
            "title": title,
            "description": description,
            "priority": priority,
            "context": context or {},
        }
        await self._send(payload)

    async def accept_task(self, session_id: str):
        """接受任务。

        Args:
            session_id: 任务对应的 Session ID。
        """
        await self._send({"type": "task_accept", "session_id": session_id})

    async def reject_task(self, session_id: str, reason: str = ""):
        """拒绝任务。

        Args:
            session_id: 任务对应的 Session ID。
            reason: 拒绝原因。
        """
        await self._send({"type": "task_reject", "session_id": session_id, "reason": reason})

    async def report_progress(self, session_id: str, percent: int, description: str = ""):
        """上报任务进度。

        Args:
            session_id: 任务对应的 Session ID。
            percent: 进度百分比（0-100）。
            description: 进度描述。
        """
        await self._send({
            "type": "task_progress",
            "session_id": session_id,
            "percent": percent,
            "description": description,
        })

    async def complete_task(self, session_id: str, result: dict = None, summary: str = ""):
        """完成任务。

        Args:
            session_id: 任务对应的 Session ID。
            result: 任务结果字典。
            summary: 结果摘要。
        """
        await self._send({
            "type": "task_complete",
            "session_id": session_id,
            "result": result or {},
            "summary": summary,
        })

    async def send_session_message(self, session_id: str, content: str, msg_type: str = "text"):
        """在 Session 内发送消息。

        Args:
            session_id: Session ID。
            content: 消息内容。
            msg_type: 消息类型，默认 ``"text"``。
        """
        await self._send({
            "type": "send_session_message",
            "session_id": session_id,
            "content": content,
            "msg_type": msg_type,
        })

    async def list_my_tasks(self, status: str = None):
        """查询我的任务列表（通过 REST API）。

        Args:
            status: 可选的任务状态过滤，如 ``"pending"``、``"in_progress"``、``"completed"``。

        Returns:
            任务列表（dict）。
        """
        import urllib.request
        import urllib.parse
        import json as _json

        parsed = urllib.parse.urlparse(self.server)
        http_scheme = "https" if parsed.scheme in ("https", "wss") else "http"
        base_url = f"{http_scheme}://{parsed.netloc}"

        url = f"{base_url}/api/agents/me"
        payload = _json.dumps({"token": self.token}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
            agent_id = data["id"]

        tasks_url = f"{base_url}/api/agents/{agent_id}/tasks"
        if status:
            tasks_url += f"?status={urllib.parse.quote(status)}"
        req2 = urllib.request.Request(tasks_url)
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            return _json.loads(resp2.read().decode())

    async def get_session_info(self, session_id: str):
        """获取 Session 详情（通过 REST API）。

        Args:
            session_id: Session ID。

        Returns:
            Session 详情字典。
        """
        import urllib.request
        import urllib.parse
        import json as _json

        parsed = urllib.parse.urlparse(self.server)
        http_scheme = "https" if parsed.scheme in ("https", "wss") else "http"
        base_url = f"{http_scheme}://{parsed.netloc}"
        url = f"{base_url}/api/sessions/{session_id}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return _json.loads(resp.read().decode())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_agent_id(self) -> str:
        """Call REST API to get agent_id associated with the token."""
        import urllib.request

        # Determine HTTP base URL from WebSocket server URL
        parsed = urllib.parse.urlparse(self.server)
        http_scheme = "https" if parsed.scheme in ("https", "wss") else "http"
        base_url = f"{http_scheme}://{parsed.netloc}"

        url = f"{base_url}/api/agents/me"
        payload = json.dumps({"token": self.token}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                agent_id = data.get("id") or data.get("agent_id")
                if not agent_id:
                    raise RuntimeError("No agent_id in response")
                return str(agent_id)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Failed to fetch agent_id: HTTP {e.code} {e.read().decode()}")

    def _build_ws_url(self) -> str:
        """Build the WebSocket URL from the server base URL."""
        parsed = urllib.parse.urlparse(self.server)
        scheme = "wss" if parsed.scheme in ("https", "wss") else "ws"
        host = parsed.netloc or parsed.path
        path = f"/ws/agent/{self._agent_id}"
        query = urllib.parse.urlencode({"api_key": self.token})
        return f"{scheme}://{host}{path}?{query}"

    async def _send_json(self, payload: dict[str, Any]) -> None:
        """Send a JSON message over the WebSocket."""
        if self._ws is None:
            raise RuntimeError("Not connected")
        await self._ws.send(json.dumps(payload))

    # Alias used by task-related methods
    _send = _send_json

    async def _heartbeat_loop(self, ws: ClientConnection) -> None:
        """Send heartbeat every HEARTBEAT_INTERVAL seconds."""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await ws.send(json.dumps({"type": "heartbeat"}))
                logger.debug("Heartbeat sent")
        except ConnectionClosed:
            logger.debug("Heartbeat loop ended (connection closed)")
        except asyncio.CancelledError:
            pass

    async def _recv_loop(self, ws: ClientConnection) -> None:
        """Receive messages and dispatch to callbacks."""
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received: %s", raw)
                    continue

                # Put into queue for async consumers
                await self._message_queue.put(msg)

                # Dispatch to type-specific handler first
                msg_type = msg.get("type", "")
                type_handler = self._type_handlers.get(msg_type)
                if type_handler is not None:
                    try:
                        result = type_handler(msg)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("Type handler error for type '%s'", msg_type)
                elif self._message_callback is not None:
                    # Fall back to generic message callback
                    try:
                        result = self._message_callback(msg)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("Generic message callback error")

                # Dispatch to legacy sync callbacks
                for cb in self._message_callbacks:
                    try:
                        cb(msg)
                    except Exception:
                        logger.exception("Message callback error")

        except ConnectionClosed:
            logger.debug("Receive loop ended (connection closed)")
        except asyncio.CancelledError:
            pass

    def _cancel_tasks(self) -> None:
        """Cancel heartbeat and receive tasks."""
        for task in (self._heartbeat_task, self._recv_task):
            if task and not task.done():
                task.cancel()
        self._heartbeat_task = None
        self._recv_task = None

    # ------------------------------------------------------------------
    # Async iterator interface
    # ------------------------------------------------------------------

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        """Async iterator over incoming messages.

        Usage::

            async for msg in client.messages():
                print(msg)
        """
        while self._running:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                yield msg
            except asyncio.TimeoutError:
                continue

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        return self.messages()


# Need to import for type hint
from typing import AsyncIterator
