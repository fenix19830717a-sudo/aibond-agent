"""Tests for CLI entry point.

TDD RED phase: Tests argument parsing and subcommand routing.
"""

from __future__ import annotations

import pytest

from aibond_agent.cli import _build_parser


# ---------------------------------------------------------------------------
# 1. Parser Structure Tests
# ---------------------------------------------------------------------------


class TestParserStructure:

    def test_parser_has_subcommands(self):
        """Parser should require a subcommand."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_connect_subcommand_exists(self):
        """'connect' should be a valid subcommand."""
        parser = _build_parser()
        args = parser.parse_args(["connect", "--server", "https://test.com", "--token", "tok"])
        assert args.command == "connect"
        assert args.server == "https://test.com"
        assert args.token == "tok"

    def test_connect_optional_name(self):
        """'connect --name' should be optional with default empty string."""
        parser = _build_parser()
        args = parser.parse_args(["connect", "--server", "https://test.com", "--token", "tok"])
        assert args.name == ""

        args2 = parser.parse_args(["connect", "--server", "https://test.com", "--token", "tok", "--name", "MyAgent"])
        assert args2.name == "MyAgent"

    def test_connect_requires_server(self):
        """'connect' without --server should fail."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["connect", "--token", "tok"])

    def test_connect_requires_token(self):
        """'connect' without --token should fail."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["connect", "--server", "https://test.com"])

    def test_mcp_subcommand_exists(self):
        """'mcp' should be a valid subcommand."""
        parser = _build_parser()
        args = parser.parse_args(["mcp", "--server", "https://test.com", "--token", "tok"])
        assert args.command == "mcp"
        assert args.server == "https://test.com"
        assert args.token == "tok"

    def test_mcp_requires_server(self):
        """'mcp' without --server should fail."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["mcp", "--token", "tok"])

    def test_mcp_requires_token(self):
        """'mcp' without --token should fail."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["mcp", "--server", "https://test.com"])

    def test_invalid_subcommand_fails(self):
        """Invalid subcommand should fail."""
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["invalid_command"])
