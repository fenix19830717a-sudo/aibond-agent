import os
import secrets
from datetime import timedelta

class Settings:
    # App
    APP_NAME: str = "aibond"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Database
    # Production: postgresql+asyncpg://user:pass@host:5432/aibond
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./aibond.db")

    # JWT - 强制从环境变量读取，不存在则生成随机密钥（每次重启失效，强制用户配置）
    _env_secret = os.getenv("SECRET_KEY")
    SECRET_KEY: str = _env_secret if _env_secret else secrets.token_urlsafe(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))  # 默认1小时，生产环境建议更短

    # Security
    MAX_LOGIN_ATTEMPTS: int = 5           # 登录失败锁定次数
    LOGIN_LOCKOUT_MINUTES: int = 15       # 锁定时间
    PASSWORD_MIN_LENGTH: int = 8          # 密码最小长度
    RATE_LIMIT_REQUESTS: int = 100        # 每窗口最大请求数
    RATE_LIMIT_WINDOW: int = 60           # 速率限制窗口（秒）

    # WebSocket
    HEARTBEAT_INTERVAL_MIN: int = 5
    HEARTBEAT_INTERVAL_MAX: int = 60
    HEARTBEAT_TIMEOUT_MULTIPLIER: int = 3

    # Agent
    AGENT_OFFLINE_MESSAGE_TTL: int = 7 * 24 * 3600

    # CORS - 生产环境严格限制
    CORS_ORIGINS: list = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173").split(",")

    # Tunnel
    TUNNEL_ENABLED: bool = os.getenv("TUNNEL_ENABLED", "true").lower() == "true"
    TUNNEL_PROVIDER: str = os.getenv("TUNNEL_PROVIDER", "cloudflare")
    PUBLIC_URL: str = os.getenv("PUBLIC_URL", "")  # 环境变量或由 TunnelManager 填充

settings = Settings()
