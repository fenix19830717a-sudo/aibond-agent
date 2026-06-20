import asyncio
import os
import re
import subprocess
from typing import Optional


class TunnelManager:
    """管理 cloudflared 隧道的生命周期。

    启动 cloudflared 临时隧道，将本地 WebSocket 服务暴露到公网。
    如果 cloudflared 不可用，会打印警告并降级为仅本地访问。
    """

    def __init__(self, local_port: int = 8000):
        self._local_port = local_port
        self._process: Optional[subprocess.Popen] = None
        self._public_url: Optional[str] = None
        self._ready_event = asyncio.Event()

    def _find_cloudflared(self) -> Optional[str]:
        """查找 cloudflared 可执行文件。"""
        import shutil
        # 1. PATH 中查找
        path = shutil.which("cloudflared")
        if path:
            return path
        # 2. 项目目录下的 cloudflared.exe
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        local_path = os.path.join(project_root, "cloudflared.exe")
        if os.path.isfile(local_path):
            return local_path
        # 3. 常见安装路径
        common_paths = [
            r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
            r"C:\Program Files\cloudflared\cloudflared.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\cloudflared\cloudflared.exe"),
        ]
        for p in common_paths:
            if os.path.isfile(p):
                return p
        return None

    async def start(self) -> None:
        """启动 cloudflared 隧道子进程，并等待获取公网 URL。"""
        cloudflared_path = self._find_cloudflared()
        if cloudflared_path is None:
            print(
                "WARNING: cloudflared not found. "
                "Tunnel is disabled. Server will run in local-only mode. "
                "Download cloudflared: https://github.com/cloudflare/cloudflared/releases"
            )
            self._ready_event.set()
            return

        cmd = [
            cloudflared_path,
            "tunnel",
            "--url",
            f"http://localhost:{self._local_port}",
        ]

        print(f"Starting cloudflared tunnel for port {self._local_port}...")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            print(f"WARNING: Failed to start cloudflared: {e}")
            self._ready_event.set()
            return

        # 在后台线程中读取 cloudflared 输出，解析公网 URL
        asyncio.get_event_loop().run_in_executor(None, self._read_output)

        # 等待 URL 被解析出来，最多等 30 秒
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            print("WARNING: Timed out waiting for cloudflared tunnel URL (30s).")
            self._ready_event.set()

    def _read_output(self) -> None:
        """读取 cloudflared 子进程的 stdout，解析公网 URL。"""
        if self._process is None or self._process.stdout is None:
            return

        url_pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")

        for line in self._process.stdout:
            line = line.strip()
            if not line:
                continue

            # 打印 cloudflared 的输出以便调试
            print(f"[cloudflared] {line}")

            match = url_pattern.search(line)
            if match:
                self._public_url = match.group(0)
                print(f"Cloudflared tunnel established: {self._public_url}")
                self._ready_event.set()

    def get_public_url(self) -> Optional[str]:
        """返回隧道公网 URL，如果尚未获取到则返回 None。"""
        return self._public_url

    def stop(self) -> None:
        """终止 cloudflared 子进程。"""
        if self._process is not None:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=5)
            except Exception as e:
                print(f"WARNING: Error stopping cloudflared: {e}")
            finally:
                self._process = None
                self._public_url = None
                print("Cloudflared tunnel stopped.")
