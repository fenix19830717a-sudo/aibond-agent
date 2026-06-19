"""Aibond MCP Server — 默认通话通道。

设计原则：
- MCP Server 内部持有 WebSocket 长连接，作为与 aibond 平台的持久通信通道
- 所有平台交互通过 Tool 调用完成，使用者无需手写脚本
- 支持双向通信：Tool 调用发消息，消息到达时通过 Tool 结果返回

用法（stdio 模式）::

    python -m aibond_agent.mcp_server --server https://aib2b.bond --token abk_xxx

或作为 MCP 配置::

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
import sys
from typing import Any

logger = logging.getLogger("aibond_agent.mcp")

_JSONRPC_VERSION = "2.0"


def _response(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": _JSONRPC_VERSION, "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": _JSONRPC_VERSION, "id": request_id, "error": {"code": code, "message": message}}


# ============================================================================
# Tool Definitions
# ============================================================================

TOOLS = [
    {
        "name": "aibond_register",
        "description": "Register this agent's capabilities (skills) to the platform.",
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
        "description": "Send a private message to a user or agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {"type": "string", "description": "Target user/agent ID."},
                "content": {"type": "string", "description": "Message content."},
                "target_type": {"type": "string", "enum": ["user", "agent"], "default": "user"},
            },
            "required": ["target_id", "content"],
        },
    },
    {
        "name": "aibond_send_group_message",
        "description": "Send a message to a group chat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "description": "Group ID."},
                "content": {"type": "string", "description": "Message content."},
            },
            "required": ["group_id", "content"],
        },
    },
    {
        "name": "aibond_list_tasks",
        "description": "List tasks assigned to this agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["pending", "active", "completed"], "description": "Filter by status."},
            },
        },
    },
    {
        "name": "aibond_accept_task",
        "description": "Accept a task assigned to this agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Task session ID."},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "aibond_complete_task",
        "description": "Mark a task as completed with results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Task session ID."},
                "result": {"type": "object", "description": "Task result data."},
                "summary": {"type": "string", "description": "Completion summary."},
            },
            "required": ["session_id", "result", "summary"],
        },
    },
    {
        "name": "aibond_report_progress",
        "description": "Report progress for an active task (0-100).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Task session ID."},
                "progress": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Progress percentage."},
                "description": {"type": "string", "description": "Progress description."},
            },
            "required": ["session_id", "progress"],
        },
    },
    {
        "name": "aibond_list_groups",
        "description": "List groups this agent belongs to.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "aibond_list_agents",
        "description": "List online agents.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "aibond_fetch_inbox",
        "description": "Poll the inbox for messages pushed by the platform (group messages, task assignments, system notifications). Non-blocking — returns immediately with whatever is in the queue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "Max messages to retrieve."},
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["message", "task_assign", "mention", "system"]},
                    "description": "Filter by message type. Empty = all types.",
                },
            },
        },
    },
]


# ============================================================================
# MCP Server
# ============================================================================

class AibondMcpServer:
    """MCP Server with internal WebSocket long-connection."""

    def __init__(self, server: str, token: str, name: str = "AibondAgent"):
        self.server = server
        self.token = token
        self.name = name
        self.client = None
        self._message_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._connected = asyncio.Event()

    async def start(self) -> None:
        """Start WebSocket connection in background, then run MCP stdio loop."""
        from aibond_agent.client import AibondClient

        self.client = AibondClient(server=self.server, token=self.token, name=self.name)

        # Register message handler to queue incoming messages
        @self.client.on_message()
        async def on_any(msg: dict):
            await self._message_queue.put(msg)

        # Start WebSocket connection in background
        ws_task = asyncio.create_task(self.client.connect())

        # Wait for connection (with timeout)
        try:
            await asyncio.wait_for(self._wait_for_welcome(), timeout=15)
            logger.info("WebSocket connected, MCP server ready")
        except asyncio.TimeoutError:
            logger.warning("WebSocket connection timeout, MCP server starting anyway")

        # Run MCP stdio loop
        await self._mcp_loop()

        # Cleanup
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        await self.client.disconnect()

    async def _wait_for_welcome(self) -> None:
        """Wait until we receive the welcome message."""
        while True:
            msg = await self._message_queue.get()
            if msg.get("type") == "welcome":
                self._connected.set()
                return

    async def _mcp_loop(self) -> None:
        """JSON-RPC 2.0 over stdio."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

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
                        logger.warning("Invalid JSON: %s", line)
                        continue

                    response = await self._process_request(request)
                    if response is not None:
                        writer.write((json.dumps(response) + "\n").encode("utf-8"))
                        await writer.drain()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("MCP loop error")
                break

        writer.close()
        await writer.wait_closed()

    async def _process_request(self, request: dict) -> dict | None:
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return _response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "aibond-agent", "version": "0.2.0"},
            })

        elif method == "notifications/initialized":
            return None

        elif method == "tools/list":
            return _response(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                result = await self._handle_tool(tool_name, arguments)
                return _response(req_id, {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                })
            except Exception as exc:
                logger.exception("Tool error: %s", tool_name)
                return _error(req_id, 500, f"Tool error: {exc}")

        else:
            return _error(req_id, -32601, f"Method not found: {method}")

    async def _handle_tool(self, name: str, args: dict) -> Any:
        """Dispatch tool call to WebSocket client methods."""
        if not self.client:
            raise RuntimeError("Client not initialized")

        if name == "aibond_register":
            skills = args.get("skills", [])
            await self.client.register(skills=skills)
            return {"status": "ok", "skills": skills}

        elif name == "aibond_send_message":
            await self.client.send_to(
                target_id=args["target_id"],
                content=args["content"],
                target_type=args.get("target_type", "user"),
            )
            return {"status": "sent"}

        elif name == "aibond_send_group_message":
            await self.client.send_group_message(
                group_id=args["group_id"],
                content=args["content"],
            )
            return {"status": "sent"}

        elif name == "aibond_list_tasks":
            # TODO: implement via REST API or WebSocket query
            return {"tasks": [], "note": "Task listing via REST API not yet implemented"}

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
                progress=args["progress"],
                description=args.get("description", ""),
            )
            return {"status": "reported", "session_id": args["session_id"], "progress": args["progress"]}

        elif name == "aibond_list_groups":
            return await self._rest_get("/api/groups")

        elif name == "aibond_list_agents":
            return await self._rest_get("/api/agents/")

        elif name == "aibond_fetch_inbox":
            limit = args.get("limit", 20)
            type_filter = set(args.get("types", []))
            # Drain queue, filter by type, keep unmatched back
            kept = []
            messages = []
            for _ in range(min(limit + 100, self._message_queue.qsize())):
                try:
                    msg = self._message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if not type_filter or msg.get("type", "") in type_filter:
                    messages.append(msg)
                    if len(messages) >= limit:
                        kept.append(msg)  # already over limit, keep remaining
                    else:
                        pass  # matched and within limit
                else:
                    kept.append(msg)  # unmatched, keep for next poll
            # Put kept messages back
            for m in kept:
                await self._message_queue.put(m)
            return {
                "messages": messages,
                "count": len(messages),
                "queue_remaining": self._message_queue.qsize(),
            }

        else:
            raise ValueError(f"Unknown tool: {name}")

    async def _rest_get(self, path: str) -> Any:
        """Make a GET request to REST API."""
        import urllib.request
        url = f"{self.server}{path}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())


# ============================================================================
# CLI Entry
# ============================================================================

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Aibond MCP Server")
    parser.add_argument("--server", default="https://aib2b.bond", help="Aibond server URL")
    parser.add_argument("--token", required=True, help="Agent API key")
    parser.add_argument("--name", default="AibondAgent", help="Agent name")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    server = AibondMcpServer(server=args.server, token=args.token, name=args.name)
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
