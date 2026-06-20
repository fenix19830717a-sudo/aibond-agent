#!/usr/bin/env python3
"""Aibond Agent SDK 一键配置脚本。

用法:
    python setup.py --token abk_your_api_key

功能:
    1. 验证 API Key 有效性
    2. 配置 .mcp.json
    3. 配置环境变量
    4. 验证 MCP Server 启动
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

SERVER = "https://aib2b.bond"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def validate_token(token: str) -> dict:
    """验证 API Key 并返回 agent 信息。"""
    url = f"{SERVER}/api/agents/me"
    data = json.dumps({"token": token}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Token validation failed ({e.code}): {body}")


def configure_mcp_json(token: str) -> None:
    """写入 .mcp.json 配置。"""
    mcp_path = os.path.join(SCRIPT_DIR, ".mcp.json")
    config = {
        "mcpServers": {
            "aibond": {
                "type": "stdio",
                "command": sys.executable,
                "args": [
                    "-m", "aibond_agent.mcp_server",
                    "--server", SERVER,
                    "--token", token,
                ],
                "timeout": 300000,
            }
        }
    }
    with open(mcp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"  [OK] {mcp_path}")


def configure_env(token: str) -> None:
    """写入 .env 文件。"""
    env_path = os.path.join(SCRIPT_DIR, ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"AIBOND_API_KEY={token}\n")
    print(f"  [OK] {env_path}")


def test_mcp_server(token: str) -> bool:
    """测试 MCP Server 能否启动。"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "aibond_agent.mcp_server", "--server", SERVER, "--token", token, "--log-level", "ERROR"],
            capture_output=True, text=True, timeout=15,
            cwd=SCRIPT_DIR,
            input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
        )
        if result.stdout:
            resp = json.loads(result.stdout.strip().split("\n")[0])
            if "result" in resp:
                info = resp["result"]["serverInfo"]
                print(f"  [OK] MCP Server v{info['version']}, {len(resp['result'].get('capabilities', {}))} capabilities")
                return True
        print(f"  [WARN] Unexpected output: {result.stdout[:100]}")
        return False
    except subprocess.TimeoutExpired:
        print("  [WARN] MCP Server timeout (may still work)")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Aibond Agent SDK Setup")
    parser.add_argument("--token", required=True, help="Your API Key (abk_xxx)")
    parser.add_argument("--server", default=SERVER, help="Aibond server URL")
    parser.add_argument("--skip-test", action="store_true", help="Skip MCP Server test")
    args = parser.parse_args()

    print(f"Aibond Agent SDK Setup")
    print(f"Server: {args.server}")
    print()

    # Step 1: Validate token
    print("1. Validating API Key...")
    try:
        agent_info = validate_token(args.token)
        print(f"  [OK] Agent: {agent_info.get('name', '?')} (id={agent_info.get('id', '?')[:8]}...)")
    except Exception as e:
        print(f"  [FAIL] {e}")
        sys.exit(1)

    # Step 2: Configure .mcp.json
    print("2. Configuring .mcp.json...")
    configure_mcp_json(args.token)

    # Step 3: Configure .env
    print("3. Configuring .env...")
    configure_env(args.token)

    # Step 4: Test MCP Server
    if not args.skip_test:
        print("4. Testing MCP Server...")
        test_mcp_server(args.token)
    else:
        print("4. Skipping MCP Server test")

    print()
    print("Setup complete! Next steps:")
    print("  - Open this project in Claude Code or Trae")
    print("  - The aibond MCP Server will auto-start")
    print("  - Use /aibond-connector skill to interact with the platform")


if __name__ == "__main__":
    main()
