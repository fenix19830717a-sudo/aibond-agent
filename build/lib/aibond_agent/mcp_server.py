"""MCP Server implementation using JSON-RPC 2.0 over stdio.

This module provides a minimal MCP (Model Context Protocol) server that
communicates via JSON-RPC 2.0 on stdin/stdout. No external MCP library
is required.

Exposed tools:
    - aibond_send_message(target_id, content, target_type)
    - aibond_list_groups()
    - aibond_list_agents()
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

logger = logging.getLogger("aibond_agent.mcp_server")

# JSON-RPC 2.0 helpers
_JSONRPC_VERSION = "2.0"


def _make_response(request_id: Any, result: Any) -> dict:
    return {
        "jsonrpc": _JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def _make_error(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": _JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


# Tool definitions for MCP
TOOLS = [
    {
        "name": "aibond_send_message",
        "description": "Send a message to a user or agent on the Aibond platform.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_id": {
                    "type": "string",
                    "description": "ID of the target user or agent.",
                },
                "content": {
                    "type": "string",
                    "description": "Message content to send.",
                },
                "target_type": {
                    "type": "string",
                    "description": 'Type of target: "user" or "agent". Default: "user".',
                    "default": "user",
                },
            },
            "required": ["target_id", "content"],
        },
    },
    {
        "name": "aibond_list_groups",
        "description": "List all groups the agent belongs to.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "aibond_list_agents",
        "description": "List all online agents on the Aibond platform.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


async def run_mcp_server(server: str, token: str) -> None:
    """Run the MCP server, reading JSON-RPC from stdin and writing to stdout.

    Args:
        server: Aibond server base URL.
        token: API key token.
    """
    # We maintain a lazy client connection; it connects on first tool use.
    client = None

    async def _ensure_client():
        """Lazily create and connect the AibondClient."""
        nonlocal client
        if client is None:
            from aibond_agent.client import AibondClient

            client = AibondClient(server=server, token=token)
            # Connect in background so we don't block the MCP loop
            connect_task = asyncio.create_task(client.connect())
            # Wait briefly for the connection to establish
            try:
                await asyncio.wait_for(connect_task, timeout=10)
            except asyncio.TimeoutError:
                logger.warning("Client connection timed out, proceeding anyway")
        return client

    async def _call_rest_api(method: str, path: str, body: dict | None = None) -> Any:
        """Make a REST API call to the Aibond server.

        Uses aiohttp directly to avoid depending on the client's WebSocket
        for REST operations.
        """
        import aiohttp

        url = f"{server}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            if method.upper() == "GET":
                async with session.get(url) as resp:
                    return await resp.json()
            elif method.upper() == "POST":
                async with session.post(url, json=body) as resp:
                    return await resp.json()
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

    async def handle_tool_call(
        tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Dispatch a tool call to the appropriate handler."""
        if tool_name == "aibond_send_message":
            target_id = arguments["target_id"]
            content = arguments["content"]
            target_type = arguments.get("target_type", "user")

            # Use REST API to send the message
            return await _call_rest_api(
                "POST",
                "/api/messages/send",
                {
                    "target_id": target_id,
                    "content": content,
                    "target_type": target_type,
                },
            )

        elif tool_name == "aibond_list_groups":
            return await _call_rest_api("GET", "/api/groups")

        elif tool_name == "aibond_list_agents":
            return await _call_rest_api("GET", "/api/agents")

        else:
            raise ValueError(f"Unknown tool: {tool_name}")

    async def process_request(request: dict) -> dict | None:
        """Process a single JSON-RPC request and return a response dict (or None)."""
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return _make_response(request_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "aibond-agent",
                    "version": "0.1.0",
                },
            })

        elif method == "notifications/initialized":
            # Notification, no response needed
            return None

        elif method == "tools/list":
            return _make_response(request_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                result = await handle_tool_call(tool_name, arguments)
                return _make_response(request_id, {
                    "content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                    ],
                })
            except Exception as exc:
                logger.exception("Tool call error: %s", tool_name)
                return _make_error(
                    request_id,
                    code=500,
                    message=f"Tool error: {exc}",
                )

        else:
            return _make_error(
                request_id,
                code=-32601,
                message=f"Method not found: {method}",
            )

    # Main read loop
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
                # EOF
                break
            buf += chunk

            # Process complete lines (JSON-RPC messages are newline-delimited)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from stdin: %s", line)
                    continue

                response = await process_request(request)
                if response is not None:
                    writer.write((json.dumps(response) + "\n").encode("utf-8"))
                    await writer.drain()

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in MCP server loop")
            break

    # Cleanup
    if client:
        await client.disconnect()
    writer.close()
    await writer.wait_closed()
