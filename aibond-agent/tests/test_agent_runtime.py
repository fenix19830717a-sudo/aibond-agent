"""Tests for AgentRuntime and SkillRegistry.

TDD RED phase: These tests cover behavior that is NOT yet tested.
Focus: SkillRegistry CRUD, AgentRuntime rule-based processing, LLM response parsing.
"""

from __future__ import annotations

import json
import pytest

from aibond_agent.agent_runtime import SkillRegistry, AgentRuntime


# ---------------------------------------------------------------------------
# 1. SkillRegistry Tests
# ---------------------------------------------------------------------------


class TestSkillRegistry:

    def test_register_skill_via_decorator(self):
        """@skills.register('name') should register function."""
        skills = SkillRegistry()

        @skills.register("write_file", description="Write a file")
        def write_file(path: str, content: str):
            return {"status": "ok"}

        assert skills.get("write_file") is write_file
        assert callable(skills.get("write_file"))

    def test_register_skill_with_schema(self):
        """Schema should be stored alongside the skill."""
        skills = SkillRegistry()
        schema = {"type": "object", "properties": {"path": {"type": "string"}}}

        @skills.register("read_file", description="Read a file", schema=schema)
        def read_file(path: str):
            pass

        assert skills._schemas["read_file"] == schema

    def test_get_nonexistent_skill_returns_none(self):
        """Getting an unregistered skill should return None."""
        skills = SkillRegistry()
        assert skills.get("nonexistent") is None

    def test_list_skills_returns_metadata(self):
        """list_skills should return name, description, schema for each skill."""
        skills = SkillRegistry()

        @skills.register("skill_a", description="Skill A")
        def skill_a():
            pass

        @skills.register("skill_b", description="Skill B", schema={"type": "object"})
        def skill_b():
            pass

        result = skills.list_skills()
        assert len(result) == 2
        names = {s["name"] for s in result}
        assert "skill_a" in names
        assert "skill_b" in names

        skill_a_info = next(s for s in result if s["name"] == "skill_a")
        assert skill_a_info["description"] == "Skill A"
        assert skill_a_info["schema"] == {}

        skill_b_info = next(s for s in result if s["name"] == "skill_b")
        assert skill_b_info["schema"] == {"type": "object"}

    def test_execute_skill_with_correct_args(self):
        """execute should call the skill function with provided arguments."""
        skills = SkillRegistry()
        calls = []

        @skills.register("echo", description="Echo input")
        def echo(text: str):
            calls.append(text)
            return {"echoed": text}

        result = skills.execute("echo", {"text": "hello"})
        assert result == {"echoed": "hello"}
        assert calls == ["hello"]

    def test_execute_nonexistent_skill_raises(self):
        """Executing an unregistered skill should raise ValueError."""
        skills = SkillRegistry()
        with pytest.raises(ValueError, match="Skill not found"):
            skills.execute("nonexistent", {})

    def test_execute_skill_with_wrong_args_raises(self):
        """Executing with wrong arguments should raise TypeError."""
        skills = SkillRegistry()

        @skills.register("greet", description="Greet")
        def greet(name: str):
            return f"Hello, {name}"

        with pytest.raises(TypeError):
            skills.execute("greet", {"wrong_arg": "value"})

    def test_list_skills_empty_registry(self):
        """Empty registry should return empty list."""
        skills = SkillRegistry()
        assert skills.list_skills() == []

    def test_register_overwrites_existing(self):
        """Registering the same name twice should overwrite."""
        skills = SkillRegistry()

        @skills.register("do_thing", description="First version")
        def v1():
            return "v1"

        @skills.register("do_thing", description="Second version")
        def v2():
            return "v2"

        assert skills.get("do_thing") is v2
        assert len(skills.list_skills()) == 1
        assert skills.list_skills()[0]["description"] == "Second version"


# ---------------------------------------------------------------------------
# 2. AgentRuntime Rule-Based Processing Tests
# ---------------------------------------------------------------------------


class TestRuleBasedProcess:

    def _make_runtime(self, skills=None):
        """Create an AgentRuntime with no LLM (rule-based mode)."""
        skills = skills or SkillRegistry()
        return AgentRuntime(
            server="https://dummy.test",
            token="test_token",
            name="TestAgent",
            skills=skills,
            llm_client=None,  # Force rule-based mode
        )

    def test_greeting_message_returns_hello(self):
        """Greeting keywords should trigger a hello response."""
        runtime = self._make_runtime()
        response = runtime._rule_based_process({
            "type": "group_message",
            "content": "你好",
        })
        assert "reply" in response
        assert "TestAgent" in response["reply"]
        assert "在线" in response["reply"]

    def test_hello_message_returns_hello(self):
        """English 'hello' should trigger a hello response."""
        runtime = self._make_runtime()
        response = runtime._rule_based_process({
            "type": "group_message",
            "content": "hello agent",
        })
        assert "reply" in response
        assert "TestAgent" in response["reply"]

    def test_skill_query_returns_skill_list(self):
        """Asking about skills should list available skills."""
        skills = SkillRegistry()

        @skills.register("code_review", description="Review code")
        def cr():
            pass

        runtime = self._make_runtime(skills=skills)
        response = runtime._rule_based_process({
            "type": "group_message",
            "content": "你有什么技能？",
        })
        assert "reply" in response
        assert "code_review" in response["reply"]

    def test_status_query_returns_online(self):
        """Asking about status should return online status."""
        runtime = self._make_runtime()
        response = runtime._rule_based_process({
            "type": "group_message",
            "content": "状态",
        })
        assert "reply" in response
        assert "在线" in response["reply"]

    def test_help_query_returns_help_text(self):
        """Asking for help should return help text."""
        runtime = self._make_runtime()
        response = runtime._rule_based_process({
            "type": "group_message",
            "content": "帮助",
        })
        assert "reply" in response
        assert "TestAgent" in response["reply"]

    def test_unknown_message_returns_echo(self):
        """Unknown message should echo back with agent name."""
        runtime = self._make_runtime()
        response = runtime._rule_based_process({
            "type": "group_message",
            "content": "random text xyz",
        })
        assert "reply" in response
        assert "收到" in response["reply"]
        assert "random text xyz" in response["reply"]

    def test_task_type_returns_accepted(self):
        """Task context should return accepted status."""
        runtime = self._make_runtime()
        response = runtime._rule_based_process({
            "type": "task",
            "title": "Test Task",
            "description": "Do something",
        })
        assert "reply" in response
        assert "Test Task" in response["reply"]
        assert "接受" in response["reply"]
        assert response["result"]["status"] == "accepted"

    def test_no_skills_shows_empty_list(self):
        """Agent with no skills should show empty skill list."""
        runtime = self._make_runtime()
        response = runtime._rule_based_process({
            "type": "group_message",
            "content": "技能",
        })
        assert "reply" in response
        assert "暂无" in response["reply"]


# ---------------------------------------------------------------------------
# 3. LLM Response Parsing Tests
# ---------------------------------------------------------------------------


class TestParseLlmResponse:

    def _make_runtime(self):
        return AgentRuntime(
            server="https://dummy.test",
            token="test_token",
            name="TestAgent",
            skills=SkillRegistry(),
            llm_client=None,
        )

    def test_parse_dict_response(self):
        """Dict response should pass through."""
        runtime = self._make_runtime()
        result = runtime._parse_llm_response({"reply": "hello", "result": {}})
        assert result["reply"] == "hello"

    def test_parse_json_string_response(self):
        """JSON string response should be parsed."""
        runtime = self._make_runtime()
        result = runtime._parse_llm_response('{"reply": "parsed"}')
        assert result["reply"] == "parsed"

    def test_parse_plain_string_response(self):
        """Plain string response should become reply."""
        runtime = self._make_runtime()
        result = runtime._parse_llm_response("just a string")
        assert result["reply"] == "just a string"

    def test_parse_non_string_non_dict_response(self):
        """Non-string, non-dict response should be stringified."""
        runtime = self._make_runtime()
        result = runtime._parse_llm_response(42)
        assert result["reply"] == "42"

    def test_parse_invalid_json_string(self):
        """Invalid JSON string should become reply."""
        runtime = self._make_runtime()
        result = runtime._parse_llm_response("{not valid json")
        assert result["reply"] == "{not valid json"


# ---------------------------------------------------------------------------
# 4. System Prompt Tests
# ---------------------------------------------------------------------------


class TestSystemPrompt:

    def test_system_prompt_includes_skill_names(self):
        """System prompt should include registered skill names."""
        skills = SkillRegistry()

        @skills.register("translate", description="Translate text")
        def translate():
            pass

        runtime = AgentRuntime(
            server="https://dummy.test",
            token="test_token",
            name="TestAgent",
            skills=skills,
            llm_client=None,
        )
        prompt = runtime.system_prompt
        assert "translate" in prompt

    def test_system_prompt_includes_agent_name(self):
        """System prompt should mention it's connected to aibond."""
        runtime = AgentRuntime(
            server="https://dummy.test",
            token="test_token",
            name="MyAgent",
            skills=SkillRegistry(),
            llm_client=None,
        )
        prompt = runtime.system_prompt
        assert "aibond" in prompt

    def test_custom_system_prompt_overrides_default(self):
        """Custom system_prompt should override the default."""
        runtime = AgentRuntime(
            server="https://dummy.test",
            token="test_token",
            name="TestAgent",
            skills=SkillRegistry(),
            llm_client=None,
            system_prompt="You are a helpful assistant.",
        )
        assert runtime.system_prompt == "You are a helpful assistant."
