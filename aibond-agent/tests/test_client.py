"""Tests for AibondClient — WebSocket client.

TDD RED phase: These tests cover behavior that is NOT yet tested.
Focus: URL building, on_message decorator, message dispatch, error handling.
"""

from __future__ import annotations

import asyncio
import json
import pytest

from aibond_agent.client import AibondClient, HEARTBEAT_INTERVAL, RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY


# ---------------------------------------------------------------------------
# 1. URL Building Tests
# ---------------------------------------------------------------------------


class TestBuildWsUrl:

    def test_https_server_builds_wss_url(self):
        """HTTPS server URL should produce wss:// WebSocket URL."""
        client = AibondClient(server="https://aib2b.bond", token="test_token")
        client._agent_id = "agent-123"
        url = client._build_ws_url()
        assert url.startswith("wss://")
        assert "aib2b.bond" in url
        assert "/ws/agent/agent-123" in url
        assert "api_key=test_token" in url

    def test_http_server_builds_ws_url(self):
        """HTTP server URL should produce ws:// WebSocket URL."""
        client = AibondClient(server="http://localhost:8000", token="test_token")
        client._agent_id = "agent-456"
        url = client._build_ws_url()
        assert url.startswith("ws://")
        assert "localhost:8000" in url
        assert "/ws/agent/agent-456" in url

    def test_wss_server_builds_wss_url(self):
        """Direct wss:// URL should also produce wss://."""
        client = AibondClient(server="wss://aib2b.bond/ws", token="test_token")
        client._agent_id = "agent-789"
        url = client._build_ws_url()
        assert url.startswith("wss://")

    def test_server_url_trailing_slash_stripped(self):
        """Trailing slash in server URL should be stripped."""
        client = AibondClient(server="https://aib2b.bond/", token="test_token")
        assert client.server == "https://aib2b.bond"

    def test_token_is_url_encoded(self):
        """Token with special characters should be properly URL-encoded."""
        client = AibondClient(server="https://aib2b.bond", token="abk_abc+def=ghi")
        client._agent_id = "agent-123"
        url = client._build_ws_url()
        # The token should appear in the query string
        assert "api_key=" in url
        # Parse and verify
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert qs["api_key"][0] == "abk_abc+def=ghi"


# ---------------------------------------------------------------------------
# 2. on_message Decorator Tests
# ---------------------------------------------------------------------------


class TestOnMessageDecorator:

    def test_direct_call_mode_registers_callback(self):
        """on_message(callback) should register callback in _message_callbacks."""
        client = AibondClient(server="https://dummy.test", token="test_token")
        cb = lambda msg: None
        result = client.on_message(cb)
        assert cb in client._message_callbacks
        assert result is cb  # should return the callback

    def test_decorator_with_type_registers_handler(self):
        """@client.on_message('task_assign') should register in _type_handlers."""
        client = AibondClient(server="https://dummy.test", token="test_token")
        handler_called = []

        @client.on_message("task_assign")
        async def handle_task(msg):
            handler_called.append(msg)

        assert "task_assign" in client._type_handlers
        assert client._type_handlers["task_assign"] is handle_task

    def test_decorator_without_type_registers_generic_callback(self):
        """@client.on_message() should register as _message_callback."""
        client = AibondClient(server="https://dummy.test", token="test_token")

        @client.on_message()
        async def handle_any(msg):
            pass

        assert client._message_callback is handle_any

    def test_multiple_type_handlers(self):
        """Multiple message types should each have their own handler."""
        client = AibondClient(server="https://dummy.test", token="test_token")

        @client.on_message("task_assign")
        async def handle_task(msg):
            pass

        @client.on_message("mention")
        async def handle_mention(msg):
            pass

        assert len(client._type_handlers) == 2
        assert "task_assign" in client._type_handlers
        assert "mention" in client._type_handlers


# ---------------------------------------------------------------------------
# 3. on_connected Callback Tests
# ---------------------------------------------------------------------------


class TestOnConnected:

    @pytest.mark.asyncio
    async def test_on_connected_sync_callback(self):
        """Sync on_connected callback should be registered and callable."""
        client = AibondClient(server="https://dummy.test", token="test_token")
        called = []

        def on_conn():
            called.append(True)

        client.on_connected(on_conn)
        assert client._on_connected_callback is on_conn

        # Simulate calling it
        result = client._on_connected_callback()
        assert not asyncio.iscoroutine(result)
        assert called == [True]

    @pytest.mark.asyncio
    async def test_on_connected_async_callback(self):
        """Async on_connected callback should return a coroutine."""
        client = AibondClient(server="https://dummy.test", token="test_token")
        called = []

        async def on_conn():
            called.append(True)

        client.on_connected(on_conn)
        result = client._on_connected_callback()
        assert asyncio.iscoroutine(result)
        await result
        assert called == [True]


# ---------------------------------------------------------------------------
# 4. Send Methods Tests (without real WebSocket)
# ---------------------------------------------------------------------------


class TestSendMethods:

    @pytest.mark.asyncio
    async def test_send_to_raises_when_not_connected(self):
        """send_to should raise RuntimeError when WebSocket is None."""
        client = AibondClient(server="https://dummy.test", token="test_token")
        assert client._ws is None
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.send_to(target_id="user_1", content="hello")

    @pytest.mark.asyncio
    async def test_send_group_message_raises_when_not_connected(self):
        """send_group_message should raise RuntimeError when WebSocket is None."""
        client = AibondClient(server="https://dummy.test", token="test_token")
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.send_group_message(group_id="g1", content="hello")

    @pytest.mark.asyncio
    async def test_register_raises_when_not_connected(self):
        """register should raise RuntimeError when WebSocket is None."""
        client = AibondClient(server="https://dummy.test", token="test_token")
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.register(skills=["code_review"])

    @pytest.mark.asyncio
    async def test_send_to_payload_format(self):
        """send_to should send correct JSON payload."""
        client = AibondClient(server="https://dummy.test", token="test_token")
        sent_messages = []

        # Mock the WebSocket send
        class MockWs:
            async def send(self, data):
                sent_messages.append(json.loads(data))

        client._ws = MockWs()
        await client.send_to(target_id="user_42", content="hello world", target_type="agent")

        assert len(sent_messages) == 1
        msg = sent_messages[0]
        assert msg["type"] == "send_message"
        assert msg["target_id"] == "user_42"
        assert msg["content"] == "hello world"
        assert msg["target_type"] == "agent"

    @pytest.mark.asyncio
    async def test_send_group_message_payload_format(self):
        """send_group_message should send correct JSON payload."""
        client = AibondClient(server="https://dummy.test", token="test_token")

        sent_messages = []

        class MockWs:
            async def send(self, data):
                sent_messages.append(json.loads(data))

        client._ws = MockWs()
        await client.send_group_message(group_id="group_99", content="@Agent1 help")

        assert len(sent_messages) == 1
        msg = sent_messages[0]
        assert msg["type"] == "send_group_message"
        assert msg["group_id"] == "group_99"
        assert msg["content"] == "@Agent1 help"


# ---------------------------------------------------------------------------
# 5. Constants Tests
# ---------------------------------------------------------------------------


class TestConstants:

    def test_heartbeat_interval_is_positive(self):
        assert HEARTBEAT_INTERVAL > 0

    def test_reconnect_delays_are_sensible(self):
        assert RECONNECT_BASE_DELAY > 0
        assert RECONNECT_MAX_DELAY >= RECONNECT_BASE_DELAY
        assert RECONNECT_MAX_DELAY <= 300  # cap at 5 minutes

    def test_reconnect_backoff_doubles(self):
        """Backoff should double each iteration until capped."""
        backoff = RECONNECT_BASE_DELAY
        for _ in range(10):
            backoff = min(backoff * 2, RECONNECT_MAX_DELAY)
        assert backoff == RECONNECT_MAX_DELAY
