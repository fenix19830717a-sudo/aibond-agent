"""CLI entry point for aibond-agent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aibond-agent",
        description="Aibond Agent SDK CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # connect sub-command
    connect_parser = sub.add_parser("connect", help="Connect to Aibond server (blocking)")
    connect_parser.add_argument("--server", required=True, help="Server base URL")
    connect_parser.add_argument("--token", required=True, help="API key token")
    connect_parser.add_argument("--name", default="", help="Agent display name")

    # mcp sub-command
    mcp_parser = sub.add_parser("mcp", help="Run as MCP Server (stdio)")
    mcp_parser.add_argument("--server", required=True, help="Server base URL")
    mcp_parser.add_argument("--token", required=True, help="API key token")

    return parser


async def _run_connect(args: argparse.Namespace) -> None:
    """Connect mode: establish WebSocket and run until interrupted."""
    from aibond_agent.client import AibondClient

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    client = AibondClient(server=args.server, token=args.token, name=args.name)

    def on_message(msg: dict) -> None:
        print(f"[message] {msg}", flush=True)

    client.on_message(on_message)

    # Handle Ctrl+C gracefully
    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    def _signal_handler() -> None:
        if not stop.done():
            stop.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows does not support add_signal_handler
            pass

    connect_task = asyncio.create_task(client.connect())

    try:
        await asyncio.wait(
            [connect_task, stop],
            return_when=asyncio.FIRST_COMPLETED,
        )
    except KeyboardInterrupt:
        pass
    finally:
        await client.disconnect()
        print("Disconnected.", flush=True)


async def _run_mcp(args: argparse.Namespace) -> None:
    """MCP Server mode: run JSON-RPC over stdio."""
    from aibond_agent.mcp_server import run_mcp_server

    await run_mcp_server(server=args.server, token=args.token)


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "connect":
        asyncio.run(_run_connect(args))
    elif args.command == "mcp":
        asyncio.run(_run_mcp(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
