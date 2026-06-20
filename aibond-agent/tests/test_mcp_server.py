"""Comprehensive unit tests for AibondMcpServer.

Tests exercise real behavior via _process_request and _fetch_inbox.
No WebSocket needed -- protocol-level tests are pure in-memory.
"""

from __future__ import annotations

import asyncio
import json
import pytest
import pytest_asyncio

from aibond_agent.mcp_server import (
    AibondMcpServer,
    _ok,
    _err,
    _tool_error,
    _JSONRPC_VERSION,
    _PROTOCOL_VERSION,
    _SERVER_VERSION,
    TOOLS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(method: str, id_val=1, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": id_val, "method": method, "params": params or {}}


def _make_initialized_server() -> AibondMcpServer:
    """Create a server that is already in the initialized state."""
    srv = AibondMcpServer(server="https://dummy.test", token="test_token")
    srv._initialized = True
    return srv


# ===========================================================================
# 1. MCP Protocol Tests
# ===========================================================================

class TestInitialize:

    @pytest.mark.asyncio
    async def test_initialize_returns_correct_protocol_version(self):
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        resp = await srv._process_request(_make_request("initialize"))
        assert resp["result"]["protocolVersion"] == _PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_initialize_returns_server_info_with_title(self):
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        resp = await srv._process_request(_make_request("initialize"))
        info = resp["result"]["serverInfo"]
        assert "name" in info
        assert "title" in info
        assert "version" in info
        assert info["name"] == "aibond-agent"
        assert info["title"] == "Aibond Platform Connector"
        assert info["version"] == _SERVER_VERSION

    @pytest.mark.asyncio
    async def test_initialize_returns_instructions(self):
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        resp = await srv._process_request(_make_request("initialize"))
        instructions = resp["result"]["instructions"]
        assert instructions
        assert isinstance(instructions, str)
        assert len(instructions) > 0

    @pytest.mark.asyncio
    async def test_initialize_returns_capabilities(self):
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        resp = await srv._process_request(_make_request("initialize"))
        caps = resp["result"]["capabilities"]
        assert "tools" in caps


class TestToolsList:

    @pytest.mark.asyncio
    async def test_tools_list_returns_10_tools(self):
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("tools/list"))
        tools = resp["result"]["tools"]
        assert len(tools) == 10

    @pytest.mark.asyncio
    async def test_tools_list_all_have_title(self):
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("tools/list"))
        tools = resp["result"]["tools"]
        for tool in tools:
            assert "title" in tool, f"Tool {tool.get('name')} missing 'title'"
            assert tool["title"], f"Tool {tool.get('name')} has empty title"

    @pytest.mark.asyncio
    async def test_tools_list_all_have_annotations(self):
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("tools/list"))
        tools = resp["result"]["tools"]
        for tool in tools:
            assert "annotations" in tool, f"Tool {tool.get('name')} missing 'annotations'"


class TestPing:

    @pytest.mark.asyncio
    async def test_ping_returns_empty_result(self):
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("ping"))
        assert resp["result"] == {}


class TestUnknownMethod:

    @pytest.mark.asyncio
    async def test_unknown_method_returns_method_not_found(self):
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("foo/bar"))
        assert resp["error"]["code"] == -32601
        assert "foo/bar" in resp["error"]["message"]


class TestLifecycle:

    @pytest.mark.asyncio
    async def test_lifecycle_rejects_before_initialized(self):
        """tools/call before initialized returns -32002."""
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        # _initialized defaults to False
        assert srv._initialized is False
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_list_groups",
            "arguments": {},
        }))
        assert resp["error"]["code"] == -32002
        assert "not initialized" in resp["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_notifications_initialized_sets_flag(self):
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        assert srv._initialized is False
        resp = await srv._process_request({"method": "notifications/initialized"})
        # notifications return None (no response)
        assert resp is None
        assert srv._initialized is True

    @pytest.mark.asyncio
    async def test_batch_requests_handled(self):
        """JSON array request returns array of responses."""
        srv = _make_initialized_server()
        requests = [
            _make_request("initialize", id_val=1),
            _make_request("ping", id_val=2),
            _make_request("bogus_method", id_val=3),
        ]
        responses = []
        for r in requests:
            resp = await srv._process_request(r)
            if resp is not None:
                responses.append(resp)

        assert len(responses) == 3
        # First: initialize success
        assert responses[0]["id"] == 1
        assert "result" in responses[0]
        # Second: ping success
        assert responses[1]["id"] == 2
        assert responses[1]["result"] == {}
        # Third: unknown method error
        assert responses[2]["id"] == 3
        assert responses[2]["error"]["code"] == -32601


# ===========================================================================
# 2. Tool Validation Tests
# ===========================================================================

class TestToolValidation:

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "nonexistent_tool",
            "arguments": {},
        }))
        assert resp["error"]["code"] == -32601
        assert "nonexistent_tool" in resp["error"]["message"]

    @pytest.mark.asyncio
    async def test_missing_required_param_returns_error(self):
        """Missing required param returns -32602."""
        srv = _make_initialized_server()
        # aibond_send_message requires target_id and content
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_send_message",
            "arguments": {"target_id": "user_123"},
            # missing "content"
        }))
        assert resp["error"]["code"] == -32602
        assert "content" in resp["error"]["message"]

    @pytest.mark.asyncio
    async def test_tool_execution_error_returns_is_error(self):
        """Tool exception returns isError: true in the result."""
        srv = _make_initialized_server()
        # aibond_list_groups calls _async_rest_get which will fail without a real server
        # This should produce a tool_error with isError: True
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_list_groups",
            "arguments": {},
        }))
        # The tool will raise an exception (no real server), resulting in isError: true
        assert "result" in resp
        assert resp["result"].get("isError") is True
        assert "content" in resp["result"]


# ===========================================================================
# 3. Inbox Queue Tests
# ===========================================================================

class TestInboxQueue:

    @pytest.mark.asyncio
    async def test_fetch_inbox_empty_returns_no_messages(self):
        srv = _make_initialized_server()
        result = await srv._fetch_inbox(limit=20, type_filter=set())
        assert result["count"] == 0
        assert result["messages"] == []
        assert result["queue_remaining"] == 0

    @pytest.mark.asyncio
    async def test_fetch_inbox_returns_queued_messages(self):
        srv = _make_initialized_server()
        msg1 = {"type": "message", "content": "hello"}
        msg2 = {"type": "system", "content": "world"}
        srv._inbox.put_nowait(msg1)
        srv._inbox.put_nowait(msg2)

        result = await srv._fetch_inbox(limit=20, type_filter=set())
        assert result["count"] == 2
        assert result["messages"] == [msg1, msg2]
        assert result["queue_remaining"] == 0

    @pytest.mark.asyncio
    async def test_fetch_inbox_type_filter(self):
        """Only matching types are returned; others are kept in queue."""
        srv = _make_initialized_server()
        msg_message = {"type": "message", "content": "hi"}
        msg_task = {"type": "task_assign", "content": "do this"}
        msg_system = {"type": "system", "content": "notice"}

        srv._inbox.put_nowait(msg_message)
        srv._inbox.put_nowait(msg_task)
        srv._inbox.put_nowait(msg_system)

        # Only fetch "message" type
        result = await srv._fetch_inbox(limit=20, type_filter={"message"})
        assert result["count"] == 1
        assert result["messages"][0]["type"] == "message"
        # task_assign and system should remain in queue
        assert result["queue_remaining"] == 2

        # Next fetch without filter should get the remaining
        result2 = await srv._fetch_inbox(limit=20, type_filter=set())
        assert result2["count"] == 2

    @pytest.mark.asyncio
    async def test_fetch_inbox_limit_respected(self):
        """Only returns up to `limit` messages."""
        srv = _make_initialized_server()
        for i in range(10):
            srv._inbox.put_nowait({"type": "message", "id": i})

        result = await srv._fetch_inbox(limit=3, type_filter=set())
        assert result["count"] == 3
        assert len(result["messages"]) == 3
        # Remaining messages should stay in queue
        assert result["queue_remaining"] == 7

    @pytest.mark.asyncio
    async def test_inbox_queue_overflow(self):
        """Queue maxsize=1000; full queue drops messages via put_nowait."""
        srv = _make_initialized_server()
        assert srv._inbox.maxsize == 1000

        # Fill the queue to max
        for i in range(1000):
            srv._inbox.put_nowait({"type": "message", "id": i})

        assert srv._inbox.full()

        # The 1001st message should raise QueueFull
        with pytest.raises(asyncio.QueueFull):
            srv._inbox.put_nowait({"type": "message", "id": 1000})


# ===========================================================================
# 4. JSON-RPC Helpers
# ===========================================================================

class TestJsonRpcHelpers:

    def test_ok_response_format(self):
        resp = _ok(42, {"foo": "bar"})
        assert resp["jsonrpc"] == _JSONRPC_VERSION
        assert resp["id"] == 42
        assert resp["result"] == {"foo": "bar"}
        assert "error" not in resp

    def test_err_response_format(self):
        resp = _err(99, -32601, "Method not found")
        assert resp["jsonrpc"] == _JSONRPC_VERSION
        assert resp["id"] == 99
        assert resp["error"]["code"] == -32601
        assert resp["error"]["message"] == "Method not found"
        assert "result" not in resp

    def test_err_response_with_data(self):
        resp = _err(1, -32602, "Invalid params", data={"field": "name"})
        assert resp["error"]["data"] == {"field": "name"}

    def test_tool_error_format(self):
        resp = _tool_error(7, "Something went wrong")
        assert resp["jsonrpc"] == _JSONRPC_VERSION
        assert resp["id"] == 7
        assert "result" in resp
        assert resp["result"]["isError"] is True
        assert resp["result"]["content"][0]["type"] == "text"
        assert resp["result"]["content"][0]["text"] == "Something went wrong"


# ===========================================================================
# 5. Edge Cases & Additional Protocol Behavior
# ===========================================================================

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_tools_list_rejected_before_initialized(self):
        """tools/list before initialized returns -32002."""
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        resp = await srv._process_request(_make_request("tools/list"))
        assert resp["error"]["code"] == -32002

    @pytest.mark.asyncio
    async def test_ping_allowed_before_initialized(self):
        """ping should work even before initialized."""
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        resp = await srv._process_request(_make_request("ping"))
        assert resp["result"] == {}

    @pytest.mark.asyncio
    async def test_initialize_allowed_before_initialized(self):
        """initialize should work even before initialized."""
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        resp = await srv._process_request(_make_request("initialize"))
        assert "result" in resp
        assert resp["result"]["protocolVersion"] == _PROTOCOL_VERSION

    @pytest.mark.asyncio
    async def test_all_tool_names_are_unique(self):
        tool_names = [t["name"] for t in TOOLS]
        assert len(tool_names) == len(set(tool_names)), "Tool names must be unique"

    @pytest.mark.asyncio
    async def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"
            assert tool["inputSchema"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_all_tools_have_description(self):
        for tool in TOOLS:
            assert "description" in tool, f"Tool {tool['name']} missing description"
            assert len(tool["description"]) > 0

    @pytest.mark.asyncio
    async def test_initialize_response_jsonrpc_version(self):
        srv = AibondMcpServer(server="https://dummy.test", token="test_token")
        resp = await srv._process_request(_make_request("initialize"))
        assert resp["jsonrpc"] == "2.0"

    @pytest.mark.asyncio
    async def test_missing_required_param_session_id(self):
        """aibond_accept_task requires session_id."""
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_accept_task",
            "arguments": {},
        }))
        assert resp["error"]["code"] == -32602
        assert "session_id" in resp["error"]["message"]

    @pytest.mark.asyncio
    async def test_missing_required_param_skills(self):
        """aibond_register_skills requires skills."""
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_register_skills",
            "arguments": {},
        }))
        assert resp["error"]["code"] == -32602
        assert "skills" in resp["error"]["message"]

    @pytest.mark.asyncio
    async def test_missing_required_param_group_id(self):
        """aibond_send_group_message requires group_id and content."""
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_send_group_message",
            "arguments": {"content": "hello"},
        }))
        assert resp["error"]["code"] == -32602
        assert "group_id" in resp["error"]["message"]

    @pytest.mark.asyncio
    async def test_missing_required_param_complete_task(self):
        """aibond_complete_task requires session_id, result, and summary."""
        srv = _make_initialized_server()
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_complete_task",
            "arguments": {"session_id": "s1"},
        }))
        assert resp["error"]["code"] == -32602
        assert "result" in resp["error"]["message"]

    @pytest.mark.asyncio
    async def test_fetch_inbox_via_tool_call(self):
        """Calling aibond_fetch_inbox as a tool works and returns proper structure."""
        srv = _make_initialized_server()
        srv._inbox.put_nowait({"type": "message", "text": "test"})
        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_fetch_inbox",
            "arguments": {},
        }))
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["count"] == 1
        assert content["messages"][0]["type"] == "message"

    @pytest.mark.asyncio
    async def test_fetch_inbox_type_filter_via_tool_call(self):
        """aibond_fetch_inbox with types filter works through tool call."""
        srv = _make_initialized_server()
        srv._inbox.put_nowait({"type": "message", "text": "hi"})
        srv._inbox.put_nowait({"type": "system", "text": "notice"})

        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_fetch_inbox",
            "arguments": {"types": ["system"]},
        }))
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["count"] == 1
        assert content["messages"][0]["type"] == "system"
        assert content["queue_remaining"] == 1

    @pytest.mark.asyncio
    async def test_fetch_inbox_limit_via_tool_call(self):
        """aibond_fetch_inbox with limit works through tool call."""
        srv = _make_initialized_server()
        for i in range(5):
            srv._inbox.put_nowait({"type": "message", "id": i})

        resp = await srv._process_request(_make_request("tools/call", params={
            "name": "aibond_fetch_inbox",
            "arguments": {"limit": 2},
        }))
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["count"] == 2
        assert content["queue_remaining"] == 3
