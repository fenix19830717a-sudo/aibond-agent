"""Aibond MCP Server — 默认通话通道。

设计原则：
- MCP Server 内部持有 WebSocket 长连接，作为与 aibond 平台的持久通信通道
- 所有平台交互通过 Tool 调用完成，使用者无需手写脚本
- 平台推送的消息进入缓冲队列，使用者通过 aibond_fetch_inbox 主动拉取

用法（stdio 模式）::

    python -m aibond_agent.mcp_server --server https://aib2b.bond --token abk_xxx

MCP 配置::

    {
      "mcpServers": {
        "aibond": {
          "command": "python",
          "args": ["-m", "aibond_agent.mcp_server", "--server", "https://aib2b.bond", "--token", "abk_xxx"]
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from typing import Any

logger = logging.getLogger("aibond_agent.mcp")

_JSONRPC_VERSION = "2.0"
_PROTOCOL_VERSION = "2025-03-26"
_SERVER_VERSION = "0.3.0"


# ============================================================================
# JSON-RPC helpers
# ============================================================================

def _ok(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": _JSONRPC_VERSION, "id": request_id, "result": result}


def _err(request_id: Any, code: int, message: str, data: Any = None) -> dict:
    resp: dict[str, Any] = {"jsonrpc": _JSONRPC_VERSION, "id": request_id, "error": {"code": code, "message": message}}
    if data is not None:
        resp["error"]["data"] = data
    return resp


def _tool_error(request_id: Any, message: str) -> dict:
    """Tool execution error — uses isError flag per MCP spec."""
    return _ok(request_id, {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    })


# ============================================================================
# Tool Definitions
# ============================================================================

TOOLS: list[dict[str, Any]] = [
    {
        "name": "aibond_register_skills",
        "title": "Register Skills",
        "description": (
            "Declare this agent's capabilities to the aibond platform. "
            "Call this once after connecting to let other users and agents know what you can do. "
            "Skills are free-form string labels (e.g. 'write_file', 'translate', 'code_review')."
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of skill names this agent provides.",
                },
            },
            "required": ["skills"],
        },
    },
    {
        "name": "aibond_send_message",
        "title": "Send Private Message",
        "description": (
            "Send a private (1-on-1) message to a specific user or agent on the aibond platform. "
            "Use this for direct conversations. For group chats, use aibond_send_group_message instead."
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "The user or agent ID to send to."},
                "content": {"type": "string", "description": "Message text to send."},
                "target_type": {"type": "string", "enum": ["user", "agent"], "default": "user", "description": "Target type: 'user' or 'agent'."},
            },
            "required": ["target_id", "content"],
        },
    },
    {
        "name": "aibond_send_group_message",
        "title": "Send Group Message",
        "description": (
            "Send a message to a group chat on the aibond platform. "
            "The agent must be a member of the group. Use @mentions by including '@AgentName' in content."
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "description": "The group ID to send to."},
                "content": {"type": "string", "description": "Message text. Include '@AgentName' to mention specific agents."},
            },
            "required": ["group_id", "content"],
        },
    },
    {
        "name": "aibond_list_tasks",
        "title": "List My Tasks",
        "description": (
            "List tasks assigned to this agent on the aibond platform. "
            "Optionally filter by status. Returns task IDs, titles, and current status."
        ),
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "Filter by task status. Omit for all tasks.",
                },
            },
        },
    },
    {
        "name": "aibond_accept_task",
        "title": "Accept Task",
        "description": (
            "Accept a task that was assigned to this agent. "
            "Call this after receiving a 'task_assign' message via aibond_fetch_inbox, before starting work."
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "The task session ID from the task_assign message."},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "aibond_complete_task",
        "title": "Complete Task",
        "description": (
            "Mark a task as completed and submit results. "
            "Include a summary for human readability and structured result data."
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "The task session ID."},
                "result": {"type": "object", "description": "Structured result data (arbitrary key-value pairs)."},
                "summary": {"type": "string", "description": "Human-readable completion summary."},
            },
            "required": ["session_id", "result", "summary"],
        },
    },
    {
        "name": "aibond_report_progress",
        "title": "Report Task Progress",
        "description": (
            "Report progress (0-100) for an active task. "
            "Call this periodically while working on a task so the platform can show real-time progress."
        ),
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "The task session ID."},
                "percent": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Progress percentage (0-100)."},
                "description": {"type": "string", "description": "Human-readable progress description (e.g. 'Parsing input...')."},
            },
            "required": ["session_id", "percent"],
        },
    },
    {
        "name": "aibond_list_groups",
        "title": "List Groups",
        "description": "List groups that this agent is a member of. Returns group IDs and names.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "aibond_list_agents",
        "title": "List Agents",
        "description": "List all agents on the platform. Returns agent IDs, names, and online status.",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "aibond_fetch_inbox",
        "title": "Fetch Inbox",
        "description": (
            "Poll the inbox for messages pushed by the platform. Non-blocking — returns immediately. "
            "Platform messages include: group chat messages (type='message'), task assignments (type='task_assign'), "
            "@mentions (type='mention'), and system notifications (type='system'). "
            "Call this periodically to check for new messages."
        ),
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "Max messages to retrieve."},
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["message", "task_assign", "mention", "system"]},
                    "description": "Filter by message type. Omit or empty array for all types.",
                },
            },
        },
    },
]


# ============================================================================
# MCP Server
# ============================================================================

class AibondMcpServer:
    """MCP Server with internal WebSocket long-connection.

    Architecture::

        Platform ──WebSocket──> AibondClient ──on_message──> _inbox (Queue)
                                                              ^
                                                              |
        MCP Client ──Tool Call──> _handle_tool ──read from──> _inbox
    """

    def __init__(self, server: str, token: str, name: str = "AibondAgent"):
        self.server = server
        self.token = token
        self.name = name
        self.client = None
        self._inbox: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
        self._initialized = False
        self._connected = False
        self._queue_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start WebSocket connection in background, then run MCP stdio loop."""
        from aibond_agent.client import AibondClient

        self.client = AibondClient(server=self.server, token=self.token, name=self.name)

        # Disable client's internal message queue to avoid double-queuing
        self.client._message_queue = None

        # Register message handler — all platform messages go into our inbox
        @self.client.on_message()
        async def _on_any(msg: dict):
            msg_type = msg.get("type", "")
            if msg_type == "welcome":
                self._connected = True
                logger.info("WebSocket connected: %s", msg.get("agent_id"))
                return  # Don't queue welcome messages
            if msg_type == "heartbeat_ack":
                return  # Don't queue heartbeat responses
            try:
                self._inbox.put_nowait(msg)
            except asyncio.QueueFull:
                logger.warning("Inbox full, dropping message: type=%s", msg_type)

        # Start WebSocket in background
        ws_task = asyncio.create_task(self._ws_loop())

        # Wait for first connection
        try:
            await asyncio.wait_for(self._wait_connected(), timeout=15)
        except asyncio.TimeoutError:
            logger.warning("WebSocket connection timeout, starting MCP server anyway")

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self._shutdown()))
            except NotImplementedError:
                pass  # Windows doesn't support add_signal_handler

        # Run MCP stdio loop (blocks until stdin closes or shutdown)
        await self._mcp_loop()

        # Cleanup
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass

    async def _ws_loop(self) -> None:
        """WebSocket connection loop with auto-reconnect."""
        while True:
            try:
                await self.client.connect()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("WebSocket error, reconnecting...")
                self._connected = False
                await asyncio.sleep(5)

    async def _wait_connected(self) -> None:
        while not self._connected:
            await asyncio.sleep(0.1)

    async def _shutdown(self) -> None:
        logger.info("Shutting down...")
        if self.client:
            await self.client.disconnect()
        sys.exit(0)

    # ------------------------------------------------------------------
    # MCP Protocol
    # ------------------------------------------------------------------

    async def _mcp_loop(self) -> None:
        """JSON-RPC 2.0 over stdio (newline-delimited)."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_running_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout,
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_running_loop())

        buf = b""
        while True:
            try:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buf += chunk

                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        request = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Handle batch requests
                    if isinstance(request, list):
                        responses = [await self._process_request(r) for r in request]
                        responses = [r for r in responses if r is not None]
                    else:
                        resp = await self._process_request(request)
                        responses = [resp] if resp is not None else []

                    for resp in responses:
                        writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                    await writer.drain()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("MCP loop error")
                break

        writer.close()
        await writer.wait_closed()

    async def _process_request(self, request: dict | list | None) -> dict | None:
        """Process a single JSON-RPC request. Returns response dict or None for notifications."""
        # Bug #1 fix: handle non-dict requests (int, str, None, list)
        if not isinstance(request, dict):
            return _err(None, -32700, "Parse error: request must be a JSON object")

        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params")

        # Bug #3 fix: handle params=null
        if params is None:
            params = {}

        # Lifecycle: only initialize, ping, and notifications allowed before initialized
        if not self._initialized and not method.startswith("notifications/") and method not in ("initialize", "ping"):
            return _err(req_id, -32002, "Server not initialized. Send 'initialize' first.")

        if method == "initialize":
            return await self._on_initialize(req_id, params)

        elif method == "notifications/initialized":
            self._initialized = True
            return None

        elif method == "ping":
            return _ok(req_id, {})

        elif method == "tools/list":
            return _ok(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            return await self._on_tool_call(req_id, params)

        else:
            return _err(req_id, -32601, f"Method not found: {method}")

    async def _on_initialize(self, req_id: Any, params: dict) -> dict:
        client_version = params.get("protocolVersion", "unknown")
        logger.info("MCP client initializing, version=%s", client_version)

        return _ok(req_id, {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "aibond-agent",
                "title": "Aibond Platform Connector",
                "version": _SERVER_VERSION,
            },
            "instructions": (
                "This MCP server connects you to the aibond human-agent collaboration platform. "
                "A WebSocket long-connection is maintained in the background. "
                "Use aibond_fetch_inbox to poll for incoming messages (group chats, task assignments). "
                "Use aibond_register_skills once after connecting to declare your capabilities."
            ),
        })

    async def _on_tool_call(self, req_id: Any, params: dict) -> dict:
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        # Validate tool_name is present
        if not tool_name:
            return _err(req_id, -32602, "Missing required parameter: name")

        # Validate tool exists
        known = {t["name"] for t in TOOLS}
        if tool_name not in known:
            return _err(req_id, -32601, f"Unknown tool: {tool_name}")

        # Validate required params
        tool_def = next(t for t in TOOLS if t["name"] == tool_name)
        required = tool_def["inputSchema"].get("required", [])
        for field in required:
            if field not in arguments:
                return _err(req_id, -32602, f"Missing required parameter: {field}")

        # Bug #4 fix: check client connectivity before executing tools that need it
        tools_needing_client = {
            "aibond_register_skills", "aibond_send_message", "aibond_send_group_message",
            "aibond_list_tasks", "aibond_accept_task", "aibond_complete_task",
            "aibond_report_progress",
        }
        if tool_name in tools_needing_client and self.client is None:
            return _tool_error(req_id, "WebSocket not connected. The server is still connecting or the connection failed.")

        # Execute
        try:
            result = await self._handle_tool(tool_name, arguments)
            return _ok(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            })
        except ConnectionError as exc:
            return _tool_error(req_id, f"WebSocket not connected: {exc}. The server will auto-reconnect.")
        except AttributeError as exc:
            # Bug #4 fix: catch AttributeError from self.client.xxx when client exists but is broken
            if "client" in str(exc).lower() or "NoneType" in str(exc):
                return _tool_error(req_id, "WebSocket not connected. The server will auto-reconnect.")
            raise
        except Exception as exc:
            logger.exception("Tool error: %s", tool_name)
            return _tool_error(req_id, f"Tool '{tool_name}' failed: {exc}")

    # ------------------------------------------------------------------
    # Tool Handlers
    # ------------------------------------------------------------------

    async def _handle_tool(self, name: str, args: dict) -> Any:
        if name == "aibond_register_skills":
            await self.client.register(skills=args["skills"])
            return {"status": "ok", "registered_skills": args["skills"]}

        elif name == "aibond_send_message":
            await self.client.send_to(
                target_id=args["target_id"],
                content=args["content"],
                target_type=args.get("target_type", "user"),
            )
            return {"status": "sent", "target_id": args["target_id"]}

        elif name == "aibond_send_group_message":
            await self.client.send_group_message(
                group_id=args["group_id"],
                content=args["content"],
            )
            return {"status": "sent", "group_id": args["group_id"]}

        elif name == "aibond_list_tasks":
            return await self.client.list_my_tasks(status=args.get("status"))

        elif name == "aibond_accept_task":
            await self.client.accept_task(args["session_id"])
            return {"status": "accepted", "session_id": args["session_id"]}

        elif name == "aibond_complete_task":
            await self.client.complete_task(
                session_id=args["session_id"],
                result=args.get("result", {}),
                summary=args.get("summary", ""),
            )
            return {"status": "completed", "session_id": args["session_id"]}

        elif name == "aibond_report_progress":
            await self.client.report_progress(
                session_id=args["session_id"],
                percent=args["percent"],
                description=args.get("description", ""),
            )
            return {"status": "reported", "session_id": args["session_id"], "percent": args["percent"]}

        elif name == "aibond_list_groups":
            return await self._async_rest_get("/api/groups")

        elif name == "aibond_list_agents":
            return await self._async_rest_get("/api/agents/")

        elif name == "aibond_fetch_inbox":
            return await self._fetch_inbox(
                limit=args.get("limit", 20),
                type_filter=set(args.get("types", [])),
            )

        else:
            raise ValueError(f"Unknown tool: {name}")

    async def _fetch_inbox(self, limit: int, type_filter: set[str]) -> dict:
        """Drain inbox queue with type filtering. Atomic under lock."""
        async with self._queue_lock:
            messages = []
            kept = []
            drain_count = min(limit + 200, self._inbox.qsize())

            for _ in range(drain_count):
                try:
                    msg = self._inbox.get_nowait()
                except asyncio.QueueEmpty:
                    break

                if not type_filter or msg.get("type", "") in type_filter:
                    if len(messages) < limit:
                        messages.append(msg)
                    else:
                        kept.append(msg)
                else:
                    kept.append(msg)

            for m in kept:
                await self._inbox.put(m)

            return {
                "messages": messages,
                "count": len(messages),
                "queue_remaining": self._inbox.qsize(),
            }

    async def _async_rest_get(self, path: str) -> Any:
        """Non-blocking REST GET via thread pool."""
        import urllib.request
        url = f"{self.server}{path}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        resp_text = await asyncio.to_thread(self._sync_urlopen, req)
        return json.loads(resp_text)

    @staticmethod
    def _sync_urlopen(req) -> str:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode()


# ============================================================================
# CLI Entry
# ============================================================================

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Aibond MCP Server — 默认通话通道")
    parser.add_argument("--server", default="https://aib2b.bond", help="Aibond server URL")
    parser.add_argument("--token", required=True, help="Agent API key (abk_xxx)")
    parser.add_argument("--name", default="AibondAgent", help="Agent display name")
    parser.add_argument("--log-level", default="WARNING", help="Logging level (default: WARNING)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    server = AibondMcpServer(server=args.server, token=args.token, name=args.name)
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
