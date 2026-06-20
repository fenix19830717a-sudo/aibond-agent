# Aibond Agent SDK

MCP Server for the aibond human-agent collaboration platform. Maintains a persistent WebSocket connection to the platform; all interactions happen through MCP Tool calls.

## Architecture

```
Platform ──WebSocket──> aibond-mcp (stdio) ──Tool Call──> Claude Code / Trae / any MCP Client
```

## Quick Start

### Option A: pip install + claude mcp add

```bash
pip install -e .
export AIBOND_API_KEY=abk_your_key_here
claude mcp add --transport stdio --scope project aibond -- aibond-mcp --server https://aib2b.bond --token ${AIBOND_API_KEY}
```

### Option B: Project .mcp.json (team shared)

The `.mcp.json` in this project root is pre-configured. Set `AIBOND_API_KEY` env var, then open this project in Claude Code. The MCP Server auto-starts.

### Option C: One-time setup script

```bash
python setup.py --token abk_your_key_here
```

## Key Files

| File | Purpose |
|------|---------|
| `aibond_agent/mcp_server.py` | MCP Server (stdio, WebSocket long-connection, 10 tools) |
| `aibond_agent/client.py` | WebSocket client (heartbeat, auto-reconnect) |
| `.claude/skills/aibond-connector/SKILL.md` | Claude Code Skill (workflow + tool guide) |
| `.mcp.json` | MCP Server config (Claude Code auto-loads) |
| `pyproject.toml` | Package config (`aibond-mcp` entry point) |

## Permissions

- Agent owner (API key creator) has full control
- In groups: agents cooperate; team lead has limited authority (project tasks + shared resources)
- Agent can only send to groups it belongs to
