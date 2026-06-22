"""Aibond MCP Server — HTTP (Streamable HTTP) 传输模式。

MCP 协议版本: 2025-03-26
传输方式: Streamable HTTP (POST + SSE)

设计原则：
- 复用 AibondMcpServer 的 _process_request() 方法
- 通过 HTTP POST 接收 JSON-RPC 请求，返回 JSON 或 SSE 流
- 通过 HTTP GET 提供 SSE 流用于服务器主动通知
- 内部持有 WebSocket 长连接到 aibond 平台

用法::

    python -m aibond_agent.mcp_http --server https://aib2b.bond --token abk_xxx --port 8080

TRAE 配置::

    {
      "mcpServers": {
        "aibond": {
          "url": "https://aib2b.bond/mcp",
          "headers": {
            "Authorization": "Bearer abk_xxx"
          }
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
import time
import uuid
from typing import Any

from aiohttp import web

from aibond_agent.mcp_server import AibondMcpServer, _JSONRPC_VERSION

logger = logging.getLogger("aibond_agent.mcp_http")

# Session storage: session_id -> AibondMcpServer instance
_sessions: dict[str, AibondMcpServer] = {}

# SSE stream storage: session_id -> list of asyncio.Queue
_sse_streams: dict[str, list[asyncio.Queue]] = {}


def _create_server(server_url: str, token: str, name: str = "AibondAgent") -> AibondMcpServer:
    """Create and start an AibondMcpServer (with WebSocket background connection)."""
    srv = AibondMcpServer(server=server_url, token=token, name=name)
    return srv


async def _handle_mcp_post(request: web.Request) -> web.StreamResponse:
    """Handle HTTP POST to MCP endpoint.

    Streamable HTTP protocol:
    - POST body is a JSON-RPC request/notification/batch
    - If contains requests: return SSE stream with responses
    - If contains only responses/notifications: return 202 Accepted
    """
    session_id = request.headers.get("Mcp-Session-Id", "")
    auth_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()

    # Parse request body
    try:
        body = await request.text()
        if not body:
            return web.json_response(
                {"jsonrpc": _JSONRPC_VERSION, "id": None, "error": {"code": -32700, "message": "Empty request body"}},
                status=400,
            )
        data = json.loads(body)
    except json.JSONDecodeError:
        return web.json_response(
            {"jsonrpc": _JSONRPC_VERSION, "id": None, "error": {"code": -32700, "message": "Invalid JSON"}},
            status=400,
        )

    # Get or create session
    if not session_id:
        # New session — will be created after initialize
        pass

    # Check if this is an initialize request (to create session)
    is_initialize = False
    if isinstance(data, dict) and data.get("method") == "initialize":
        is_initialize = True

    if is_initialize and not session_id:
        session_id = str(uuid.uuid4())
        # Use token from Authorization header or from config
        token = auth_token or request.app["default_token"]
        server_url = request.app["server_url"]
        srv = _create_server(server_url, token)
        _sessions[session_id] = srv
        _sse_streams[session_id] = []
        logger.info("New MCP session: %s", session_id[:8])

    if not session_id or session_id not in _sessions:
        return web.json_response(
            {"jsonrpc": _JSONRPC_VERSION, "id": None, "error": {"code": -32000, "message": "Session not found. Send initialize first."}},
            status=400,
        )

    srv = _sessions[session_id]

    # Process the request(s)
    if isinstance(data, list):
        # Batch request
        has_request = any(isinstance(item, dict) and "id" in item and "method" in item for item in data)
        has_response_only = all(isinstance(item, dict) and "result" in item or "error" in item for item in data)

        if has_response_only:
            return web.Response(status=202)

        responses = []
        for item in data:
            resp = await srv._process_request(item)
            if resp is not None:
                responses.append(resp)

        if not responses:
            return web.Response(status=202)

        # Return as SSE stream
        return await _sse_response(request, session_id, responses)

    elif isinstance(data, dict):
        method = data.get("method")
        req_id = data.get("id")

        # Notification only (no id)
        if req_id is None and method:
            await srv._process_request(data)
            return web.Response(status=202)

        # Response only
        if "result" in data or "error" in data:
            return web.Response(status=202)

        # Regular request — process and return
        resp = await srv._process_request(data)

        if resp is None:
            return web.Response(status=202)

        # For initialize, include session ID in response header
        response = web.Response(
            body=json.dumps(resp, ensure_ascii=False) + "\n",
            content_type="application/json",
        )
        if is_initialize:
            response.headers["Mcp-Session-Id"] = session_id
        return response

    return web.json_response(
        {"jsonrpc": _JSONRPC_VERSION, "id": None, "error": {"code": -32700, "message": "Invalid request format"}},
        status=400,
    )


async def _sse_response(request: web.Request, session_id: str, responses: list) -> web.StreamResponse:
    """Return responses as SSE stream."""
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Mcp-Session-Id": session_id,
        },
    )
    await response.prepare(request)

    for resp in responses:
        event_id = str(uuid.uuid4())[:8]
        data_str = json.dumps(resp, ensure_ascii=False)
        await response.write(f"event: message\nid: {event_id}\ndata: {data_str}\n\n".encode())

    await response.write("event: end\ndata: {}\n\n".encode())
    return response


async def _handle_mcp_get(request: web.Request) -> web.StreamResponse:
    """Handle HTTP GET to MCP endpoint — open SSE stream for server-initiated messages."""
    session_id = request.headers.get("Mcp-Session-Id", "")

    if not session_id or session_id not in _sessions:
        return web.Response(status=405, text="Method Not Allowed")

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Mcp-Session-Id": session_id,
        },
    )
    await response.prepare(request)

    # Keep stream alive, send heartbeat
    try:
        while True:
            await asyncio.sleep(30)
            await response.write(": heartbeat\n\n".encode())
    except asyncio.CancelledError:
        pass

    return response


async def _handle_mcp_delete(request: web.Request) -> web.Response:
    """Handle HTTP DELETE to terminate session."""
    session_id = request.headers.get("Mcp-Session-Id", "")

    if session_id and session_id in _sessions:
        srv = _sessions.pop(session_id)
        _sse_streams.pop(session_id, None)
        # Disconnect the WebSocket
        if srv.client:
            try:
                await srv.client.disconnect()
            except Exception:
                pass
        logger.info("Session terminated: %s", session_id[:8])

    return web.Response(status=202)


async def _handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({
        "status": "ok",
        "service": "aibond-mcp-http",
        "version": "0.4.0",
        "protocol": "2025-03-26",
        "active_sessions": len(_sessions),
    })


async def create_app(server_url: str, token: str, host: str = "0.0.0.0", port: int = 8080) -> web.Application:
    """Create the aiohttp application."""
    app = web.Application()
    app["server_url"] = server_url
    app["default_token"] = token
    app["host"] = host
    app["port"] = port

    app.router.add_post("/mcp", _handle_mcp_post)
    app.router.add_get("/mcp", _handle_mcp_get)
    app.router.add_delete("/mcp", _handle_mcp_delete)
    app.router.add_get("/health", _handle_health)

    return app


async def main_async():
    """Entry point for HTTP MCP Server."""
    import argparse

    parser = argparse.ArgumentParser(description="Aibond MCP Server — HTTP (Streamable HTTP) mode")
    parser.add_argument("--server", default="https://aib2b.bond", help="Aibond server URL")
    parser.add_argument("--token", required=True, help="Default agent API key (abk_xxx)")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Listen port (default: 8080)")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    app = await create_app(
        server_url=args.server,
        token=args.token,
        host=args.host,
        port=args.port,
    )

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()

    logger.info("Aibond MCP HTTP Server listening on %s:%d/mcp", args.host, args.port)
    logger.info("Health check: http://%s:%d/health", args.host, args.port)

    # Wait forever
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
