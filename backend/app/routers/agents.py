from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import uuid

from app.database import get_db
from app.models.models import Agent
from app.security import rate_limit, sanitize_command_arg
from app.config import settings

bearer_scheme = HTTPBearer(auto_error=False)

async def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str | None:
    """Extract user_id from JWT token. Returns None if not authenticated."""
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except (JWTError, Exception):
        return None

router = APIRouter(prefix="/api/agents", tags=["agents"])

class AgentRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    api_key: str | None = Field(None, max_length=128)
    skills: list[str] | None = None
    mcp_endpoints: list[str] | None = None
    callback_url: str = Field("", max_length=255)

class MeByTokenRequest(BaseModel):
    token: str = Field(..., min_length=10)

class HeartbeatRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    address: str = Field("", max_length=255)

class CreateTokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

@router.post("/create-token")
async def create_agent_token(req: CreateTokenRequest, request: Request, db: AsyncSession = Depends(get_db), user_id: str | None = Depends(get_current_user_id)):
    # Rate limit: 10 token creations per minute per IP
    await rate_limit(request, limit=10, window=60)

    # Require user authentication
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required to create agent")

    agent_id = str(uuid.uuid4())
    api_key = f"abk_{uuid.uuid4().hex[:32]}"

    agent = Agent(
        id=agent_id,
        name=req.name,
        api_key=api_key,
        owner_id=user_id,
        status="pending",
        skills=[],
        mcp_endpoints=[],
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    # 安全地转义名称，防止命令注入
    safe_name = sanitize_command_arg(req.name)
    server_url = settings.PUBLIC_URL.replace("https://", "wss://") if settings.PUBLIC_URL else "ws://localhost:8000"
    http_server_url = settings.PUBLIC_URL if settings.PUBLIC_URL else "http://localhost:8000"

    register_command = f'aibond-agent connect --server {server_url} --token {api_key} --name "{safe_name}"'
    register_command_fallback = f'python -m aibond_agent.cli connect --server {server_url} --token {api_key} --name "{safe_name}"'
    mcp_config = f'{{"mcpServers":{{"aibond":{{"command":"aibond-agent","args":["mcp","--server","{server_url}","--token","{api_key}"]}}}}}}'

    connection_guide = (
        f"=== aibond Agent 连接指南 ===\n\n"
        f"1. 安装 SDK（三选一）：\n"
        f"   pip install aibond-agent\n"
        f"   或从服务器下载:\n"
        f"   wget {http_server_url}/api/sdk/download\n"
        f"   pip install ./aibond_agent-0.1.0-py3-none-any.whl\n"
        f"   或远程安装：pip install {http_server_url}/api/sdk/download\n\n"
        f"2. 连接平台：\n"
        f"   {register_command}\n"
        f"   如果 CLI 不在 PATH 中:\n"
        f"   {register_command_fallback}\n\n"
        f"3. MCP 客户端（Claude/Trae）配置：\n"
        f"   {mcp_config}\n\n"
        f"Agent ID: {agent.id}\n"
        f"API Key: {api_key}\n"
        f"Server: {server_url}"
    )

    return {
        "id": agent.id,
        "name": agent.name,
        "api_key": agent.api_key,
        "status": "pending",
        "server_url": server_url,
        "http_server_url": http_server_url,
        "register_command": register_command,
        "register_command_fallback": register_command_fallback,
        "mcp_config": mcp_config,
        "connection_guide": connection_guide,
    }

@router.post("/register")
async def register_agent(req: AgentRegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, limit=10, window=60)

    api_key = req.api_key or f"abk_{uuid.uuid4().hex[:32]}"

    agent = Agent(
        id=str(uuid.uuid4()),
        name=req.name,
        api_key=api_key,
        skills=req.skills or [],
        mcp_endpoints=req.mcp_endpoints or [],
        callback_url=req.callback_url,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    return {
        "id": agent.id,
        "name": agent.name,
        "api_key": agent.api_key,
        "status": agent.status,
        "skills": agent.skills,
    }

@router.get("/")
async def list_agents(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user_id: str | None = Depends(get_current_user_id),
):
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")
    query = select(Agent).where(Agent.is_active == True, Agent.owner_id == user_id)
    if status:
        # Validate status to prevent injection
        if status not in ("online", "offline", "busy", "pending"):
            raise HTTPException(status_code=400, detail="Invalid status filter")
        query = query.where(Agent.status == status)
    result = await db.execute(query)
    agents = result.scalars().all()

    return [{
        "id": a.id,
        "name": a.name,
        "status": a.status,
        "skills": a.skills,
        "last_heartbeat": str(a.last_heartbeat) if a.last_heartbeat else None,
        "current_address": a.current_address,
    } for a in agents]

@router.get("/available")
async def list_available_agents(db: AsyncSession = Depends(get_db)):
    """列出所有活跃的Agent，供下拉选择使用（不返回敏感信息）"""
    result = await db.execute(
        select(Agent).where(Agent.is_active == True)
    )
    agents = result.scalars().all()
    sorted_agents = sorted(agents, key=lambda a: (a.status != "online", a.name))
    return [{
        "id": a.id,
        "name": a.name,
        "status": a.status,
        "skills": a.skills or [],
    } for a in sorted_agents]

@router.post("/me")
async def get_agent_by_token(req: MeByTokenRequest, db: AsyncSession = Depends(get_db)):
    """Agent 通过 API Key 查询自己的 ID（SDK 连接时使用）"""
    result = await db.execute(select(Agent).where(Agent.api_key == req.token, Agent.is_active == True))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found with this token")
    return {
        "id": agent.id,
        "name": agent.name,
        "status": agent.status,
    }

@router.get("/{agent_id}")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "id": agent.id,
        "name": agent.name,
        "status": agent.status,
        "skills": agent.skills,
        "mcp_endpoints": agent.mcp_endpoints,
        "callback_url": agent.callback_url,
        "capabilities": agent.capabilities,
        "last_heartbeat": str(agent.last_heartbeat) if agent.last_heartbeat else None,
        "current_address": agent.current_address,
    }

@router.post("/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str, req: HeartbeatRequest, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.api_key == req.api_key))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid agent credentials")

    agent.status = "online"
    agent.last_heartbeat = datetime.now(timezone.utc)
    if req.address:
        agent.current_address = req.address
    await db.commit()

    return {"status": "ok", "agent_status": agent.status}
