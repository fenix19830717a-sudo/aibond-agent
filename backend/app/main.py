from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.config import settings
from app.database import init_db
from app.routers import auth, agents, groups, messages, workflows, sessions, files, offline
from app.websocket.manager import ws_manager
from app.tunnel import TunnelManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()

    # Ensure uploads directory exists
    _uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    os.makedirs(_uploads_dir, exist_ok=True)

    tunnel_manager = None
    if settings.TUNNEL_ENABLED:
        tunnel_manager = TunnelManager(local_port=8000)
        await tunnel_manager.start()
        public_url = tunnel_manager.get_public_url()
        if public_url:
            settings.PUBLIC_URL = public_url

    print("aibond server started")
    print(f"DEBUG mode: {settings.DEBUG}")
    if settings.PUBLIC_URL:
        # 将 https 转换为 wss 用于 WebSocket 连接
        wss_url = settings.PUBLIC_URL.replace("https://", "wss://")
        print(f"aibond server started, public URL: {wss_url}")
    else:
        print("aibond server started, public URL: (tunnel not available, local only)")
    if not settings._env_secret:
        print("WARNING: SECRET_KEY not set in environment. Using random key (sessions will not survive restart).")
    yield
    # Shutdown
    if tunnel_manager is not None:
        tunnel_manager.stop()
    print("aibond server stopped")

app = FastAPI(
    title=settings.APP_NAME,
    description="Enterprise Human-AI Collaboration Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Security headers middleware
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # In production, add CSP: response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response

# CORS - strict origin validation
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

# Global exception handler (don't leak internal errors)
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    if settings.DEBUG:
        raise exc
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )

# Static files - SDK packages download
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Routers
app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(groups.router)
app.include_router(messages.router)
app.include_router(workflows.router)
app.include_router(sessions.router)
app.include_router(files.router)
app.include_router(offline.router)

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "aibond"}

@app.get("/api/sdk/download")
async def download_sdk():
    """Download the aibond-agent SDK wheel package."""
    whl_path = os.path.join(_static_dir, "packages", "aibond_agent-0.1.0-py3-none-any.whl")
    if not os.path.isfile(whl_path):
        return JSONResponse(status_code=404, content={"detail": "SDK package not found"})
    return FileResponse(
        path=whl_path,
        filename="aibond_agent-0.1.0-py3-none-any.whl",
        media_type="application/octet-stream",
    )

@app.get("/api/sdk/info")
async def sdk_info():
    """Return SDK installation info and current server URL."""
    server_url = settings.PUBLIC_URL.replace("https://", "wss://") if settings.PUBLIC_URL else "ws://localhost:8000"
    http_url = settings.PUBLIC_URL if settings.PUBLIC_URL else "http://localhost:8000"
    return {
        "package": "aibond_agent-0.1.0-py3-none-any.whl",
        "download_url": f"{http_url}/api/sdk/download",
        "install_command": f"pip install {http_url}/api/sdk/download",
        "server_url": server_url,
        "http_server_url": http_url,
    }

@app.websocket("/ws/user/{user_id}")
async def user_websocket(websocket: WebSocket, user_id: str):
    # User WebSocket currently accepts any connection with user_id in path
    # In production, validate JWT token during handshake
    await ws_manager.connect_user(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")
            if msg_type == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack"})
            elif msg_type == "register":
                # Agent self-registration via user websocket (if needed)
                pass
            elif msg_type == "message":
                await ws_manager.broadcast_to_group(
                    data.get("target_user_ids", []),
                    data.get("target_agent_ids", []),
                    {"type": "message", "data": data}
                )
    except WebSocketDisconnect:
        ws_manager.disconnect_user(user_id, websocket)

@app.websocket("/ws/agent/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str, api_key: str = Query(...)):
    from app.database import async_session
    from app.models.models import Agent, Message
    from sqlalchemy import select
    from datetime import datetime, timezone
    import uuid

    # Validate api_key format
    if not api_key or not api_key.startswith("abk_") or len(api_key) < 20:
        await websocket.close(code=4001, reason="Invalid API key format")
        return

    # Verify agent
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.api_key == api_key))
        agent = result.scalar_one_or_none()
        if not agent:
            await websocket.close(code=4001, reason="Invalid agent credentials")
            return

        # Update agent status
        agent.status = "online"
        agent.last_heartbeat = datetime.now(timezone.utc)
        await db.commit()

    await ws_manager.connect_agent(agent_id, websocket)

    # 发送欢迎消息：包含 Agent 信息、skills
    welcome = {
        "type": "welcome",
        "agent_id": agent_id,
        "agent_name": agent.name,
        "skills": agent.skills or [],
    }
    await websocket.send_json(welcome)

    # 推送积压的离线消息
    async with async_session() as db:
        from app.models.models import OfflineMessage
        offline_result = await db.execute(
            select(OfflineMessage).where(
                OfflineMessage.target_type == "agent",
                OfflineMessage.target_id == agent_id,
                OfflineMessage.delivered_at == None,
            ).order_by(OfflineMessage.created_at.asc())
        )
        offline_messages = offline_result.scalars().all()
        for om in offline_messages:
            try:
                await websocket.send_json(om.message_json)
                om.delivered_at = datetime.now(timezone.utc)
            except Exception:
                break
        await db.commit()

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "heartbeat":
                async with async_session() as db:
                    result = await db.execute(select(Agent).where(Agent.id == agent_id))
                    agent = result.scalar_one_or_none()
                    if agent:
                        agent.last_heartbeat = datetime.now(timezone.utc)
                        if data.get("address"):
                            # Validate address length
                            addr = str(data["address"])[:255]
                            agent.current_address = addr
                        await db.commit()
                await websocket.send_json({"type": "heartbeat_ack"})

            elif msg_type == "register":
                # 处理能力上报
                async with async_session() as db:
                    result = await db.execute(select(Agent).where(Agent.id == agent_id))
                    agent = result.scalar_one_or_none()
                    if agent:
                        if data.get("skills"):
                            agent.skills = data["skills"]
                        if data.get("mcp_endpoints"):
                            agent.mcp_endpoints = data["mcp_endpoints"]
                        if data.get("capabilities"):
                            agent.capabilities = data["capabilities"]
                        await db.commit()
                await websocket.send_json({"type": "register_ack", "status": "ok"})

            elif msg_type == "send_message":
                # Agent 发送定向消息
                target_id = data.get("target_id")
                target_type = data.get("target_type", "user")
                content = data.get("content", "")

                # 持久化消息到数据库
                async with async_session() as db:
                    msg = Message(
                        id=str(uuid.uuid4()),
                        sender_type="agent",
                        sender_agent_id=agent_id,
                        msg_type="text",
                        content=content,
                        status="sent",
                    )
                    db.add(msg)
                    await db.commit()

                # WebSocket 推送给目标
                message_payload = {
                    "type": "message",
                    "id": msg.id,
                    "sender_type": "agent",
                    "sender_id": agent_id,
                    "sender_name": agent.name,
                    "content": content,
                    "msg_type": "text",
                }
                if target_type == "user":
                    await ws_manager.send_to_user(target_id, message_payload)
                elif target_type == "agent":
                    await ws_manager.send_to_agent(target_id, message_payload)

            elif msg_type == "send_group_message":
                # Agent 发送群组消息
                group_id = data.get("group_id")
                content = data.get("content", "")

                # 验证 Agent 是群组成员
                async with async_session() as db:
                    from app.models.models import GroupMember
                    member_check = await db.execute(
                        select(GroupMember).where(
                            GroupMember.group_id == group_id,
                            GroupMember.agent_id == agent_id,
                        )
                    )
                    if not member_check.scalar_one_or_none():
                        await websocket.send_json({"type": "error", "message": "Not a member of this group"})
                        continue

                # 解析 @提及
                import re
                mention_ids = []
                async with async_session() as db:
                    from app.models.models import Agent as AgentModel, GroupMember
                    # 提取 @name 模式
                    mention_names = re.findall(r'@(\S+)', content)
                    if mention_names:
                        for name in mention_names:
                            if name.lower() == "all":
                                # @all: 通知所有群组成员
                                members_result = await db.execute(
                                    select(GroupMember).where(GroupMember.group_id == group_id)
                                )
                                all_members = members_result.scalars().all()
                                for gm in all_members:
                                    if gm.agent_id and gm.agent_id not in mention_ids:
                                        mention_ids.append(gm.agent_id)
                                    if gm.user_id and gm.user_id not in mention_ids:
                                        mention_ids.append(gm.user_id)
                            else:
                                # 查找匹配的 Agent
                                agent_result = await db.execute(
                                    select(AgentModel).where(AgentModel.name == name)
                                )
                                matched_agent = agent_result.scalar_one_or_none()
                                if matched_agent and matched_agent.id not in mention_ids:
                                    mention_ids.append(matched_agent.id)

                    msg = Message(
                        id=str(uuid.uuid4()),
                        group_id=group_id,
                        sender_type="agent",
                        sender_agent_id=agent_id,
                        msg_type="text",
                        content=content,
                        mentions=mention_ids,
                        status="sent",
                    )
                    db.add(msg)
                    await db.commit()

                # 广播给群组成员
                broadcast_payload = {
                    "type": "message",
                    "id": msg.id,
                    "sender_type": "agent",
                    "sender_id": agent_id,
                    "sender_name": agent.name,
                    "content": content,
                    "msg_type": "text",
                    "group_id": group_id,
                    "mentions": mention_ids,
                }
                await ws_manager.broadcast_to_group_message(group_id, broadcast_payload)

                # 额外推送 @提及通知
                for mid in mention_ids:
                    mention_notification = {
                        "type": "mention",
                        "message_id": msg.id,
                        "group_id": group_id,
                        "sender_id": agent_id,
                        "sender_name": agent.name,
                        "content": content,
                    }
                    # 判断是 agent 还是 user
                    async with async_session() as db:
                        from app.models.models import Agent as AgentModel
                        check_agent = await db.execute(select(AgentModel).where(AgentModel.id == mid))
                        if check_agent.scalar_one_or_none():
                            await ws_manager.send_to_agent(mid, mention_notification)
                        else:
                            await ws_manager.send_to_user(mid, mention_notification)

            elif msg_type == "task_assign":
                # Agent 分配任务给另一个 Agent → 自动创建 Session
                target_agent_id = data.get("target_agent_id")
                group_id = data.get("group_id")
                title = data.get("title", "未命名任务")
                description = data.get("description", "")
                priority = data.get("priority", "normal")
                context = data.get("context", {})

                async with async_session() as db:
                    # 创建 Session
                    from app.models.models import Session as SessionModel, SessionMember
                    session = SessionModel(
                        id=str(uuid.uuid4()),
                        group_id=group_id,
                        title=title,
                        description=description,
                        status="active",
                        priority=priority,
                        assigner_id=agent_id,
                        assigner_type="agent",
                        assignee_ids=[target_agent_id],
                        context=context,
                    )
                    db.add(session)
                    await db.commit()
                    await db.refresh(session)

                    # 添加成员
                    db.add(SessionMember(id=str(uuid.uuid4()), session_id=session.id, member_type="agent", member_id=agent_id, role="lead"))
                    db.add(SessionMember(id=str(uuid.uuid4()), session_id=session.id, member_type="agent", member_id=target_agent_id, role="participant"))

                    # 系统消息
                    sys_msg = Message(
                        id=str(uuid.uuid4()),
                        group_id=group_id,
                        session_id=session.id,
                        sender_type="system",
                        msg_type="system",
                        content=f"任务已分配: {title}",
                        msg_metadata={"event": "task_assigned", "from_agent": agent_id, "to_agent": target_agent_id},
                    )
                    db.add(sys_msg)
                    await db.commit()

                # 通知双方
                assign_payload = {
                    "type": "task_assign",
                    "session_id": session.id,
                    "title": title,
                    "description": description,
                    "priority": priority,
                    "context": context,
                    "from_agent_id": agent_id,
                    "from_agent_name": agent.name,
                }
                await ws_manager.send_to_agent(target_agent_id, assign_payload)
                await ws_manager.send_to_agent(agent_id, {**assign_payload, "type": "task_assign_ack"})

            elif msg_type == "send_session_message":
                # Agent 在 Session 内发送消息
                session_id = data.get("session_id")
                content = data.get("content", "")
                msg_type_inner = data.get("msg_type", "text")

                async with async_session() as db:
                    from app.models.models import Session as SessionModel, SessionMember
                    session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
                    session = session_result.scalar_one_or_none()
                    if not session or session.status not in ("active", "paused"):
                        await websocket.send_json({"type": "error", "message": "Session not found or not active"})
                        continue

                    # 验证成员
                    member_result = await db.execute(
                        select(SessionMember).where(
                            SessionMember.session_id == session_id,
                            SessionMember.member_type == "agent",
                            SessionMember.member_id == agent_id,
                        )
                    )
                    if not member_result.scalar_one_or_none():
                        await websocket.send_json({"type": "error", "message": "Not a member of this session"})
                        continue

                    msg = Message(
                        id=str(uuid.uuid4()),
                        group_id=session.group_id,
                        session_id=session_id,
                        sender_type="agent",
                        sender_agent_id=agent_id,
                        msg_type=msg_type_inner,
                        content=content,
                        status="sent",
                    )

                    # 先查询 Session 成员（用于 @提及 和广播）
                    members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == session_id))
                    members = members_result.scalars().all()

                    # 解析 @提及
                    import re
                    mention_ids = []
                    mention_names = re.findall(r'@(\S+)', content)
                    if mention_names:
                        from app.models.models import Agent as AgentModel
                        for name in mention_names:
                            if name.lower() == "all":
                                for sm in members:
                                    if sm.member_id not in mention_ids:
                                        mention_ids.append(sm.member_id)
                            else:
                                agent_result = await db.execute(
                                    select(AgentModel).where(AgentModel.name == name)
                                )
                                matched_agent = agent_result.scalar_one_or_none()
                                if matched_agent and matched_agent.id not in mention_ids:
                                    mention_ids.append(matched_agent.id)
                    msg.mentions = mention_ids

                    db.add(msg)
                    await db.commit()

                broadcast_msg = {
                    "type": "session_message",
                    "id": msg.id,
                    "session_id": session_id,
                    "sender_type": "agent",
                    "sender_id": agent_id,
                    "sender_name": agent.name,
                    "msg_type": msg_type_inner,
                    "content": content,
                    "mentions": mention_ids,
                    "created_at": str(datetime.now(timezone.utc)),
                }
                for m in members:
                    if m.member_type == "user":
                        await ws_manager.send_to_user(m.member_id, broadcast_msg)
                    elif m.member_type == "agent":
                        await ws_manager.send_to_agent(m.member_id, broadcast_msg)

                # 额外推送 @提及通知
                for mid in mention_ids:
                    mention_notification = {
                        "type": "mention",
                        "message_id": msg.id,
                        "session_id": session_id,
                        "sender_id": agent_id,
                        "sender_name": agent.name,
                        "content": content,
                    }
                    async with async_session() as db:
                        from app.models.models import Agent as AgentModel
                        check_agent = await db.execute(select(AgentModel).where(AgentModel.id == mid))
                        if check_agent.scalar_one_or_none():
                            await ws_manager.send_to_agent(mid, mention_notification)
                        else:
                            await ws_manager.send_to_user(mid, mention_notification)

            elif msg_type == "task_complete":
                # Agent 完成任务
                session_id = data.get("session_id")
                result_data = data.get("result", {})
                summary = data.get("summary", "")

                async with async_session() as db:
                    from app.models.models import Session as SessionModel, SessionMember
                    session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
                    session = session_result.scalar_one_or_none()
                    if session:
                        session.status = "completed"
                        session.completed_at = datetime.now(timezone.utc)
                        await db.commit()

                        # 系统消息
                        sys_msg = Message(
                            id=str(uuid.uuid4()),
                            group_id=session.group_id,
                            session_id=session_id,
                            sender_type="system",
                            msg_type="system",
                            content=f"任务已完成: {session.title}",
                            msg_metadata={"event": "task_completed", "result": result_data, "summary": summary},
                        )
                        db.add(sys_msg)
                        await db.commit()

                        # 通知成员
                        members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == session_id))
                        members = members_result.scalars().all()

                complete_msg = {
                    "type": "task_completed",
                    "session_id": session_id,
                    "result": result_data,
                    "summary": summary,
                    "completed_by": agent_id,
                }
                for m in members:
                    if m.member_type == "user":
                        await ws_manager.send_to_user(m.member_id, complete_msg)
                    elif m.member_type == "agent":
                        await ws_manager.send_to_agent(m.member_id, complete_msg)

            elif msg_type == "task_accept":
                # 队员接受任务
                session_id = data.get("session_id")
                async with async_session() as db:
                    from app.models.models import Session as SessionModel
                    session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
                    session = session_result.scalar_one_or_none()
                    if session:
                        # 验证该 Agent 是 assignee
                        if agent_id in (session.assignee_ids or []):
                            session.status = "active"
                            session.assigned_at = datetime.now(timezone.utc)
                            await db.commit()
                            # 通知所有成员
                            from app.models.models import SessionMember
                            members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == session_id))
                            members = members_result.scalars().all()
                            accept_msg = {"type": "task_accepted", "session_id": session_id, "agent_id": agent_id, "agent_name": agent.name}
                            for m in members:
                                if m.member_type == "user":
                                    await ws_manager.send_to_user(m.member_id, accept_msg)
                                elif m.member_type == "agent":
                                    await ws_manager.send_to_agent(m.member_id, accept_msg)

            elif msg_type == "task_reject":
                # 队员拒绝任务
                session_id = data.get("session_id")
                reason = data.get("reason", "")
                async with async_session() as db:
                    from app.models.models import Session as SessionModel
                    session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
                    session = session_result.scalar_one_or_none()
                    if session:
                        session.status = "cancelled"
                        await db.commit()
                        from app.models.models import SessionMember
                        members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == session_id))
                        members = members_result.scalars().all()
                        reject_msg = {"type": "task_rejected", "session_id": session_id, "agent_id": agent_id, "agent_name": agent.name, "reason": reason}
                        for m in members:
                            if m.member_type == "user":
                                await ws_manager.send_to_user(m.member_id, reject_msg)
                            elif m.member_type == "agent":
                                await ws_manager.send_to_agent(m.member_id, reject_msg)

            elif msg_type == "task_progress":
                # 进度上报
                session_id = data.get("session_id")
                percent = data.get("percent", 0)
                description = data.get("description", "")
                async with async_session() as db:
                    from app.models.models import Session as SessionModel
                    session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
                    session = session_result.scalar_one_or_none()
                    if session:
                        session.progress = percent
                        session.progress_description = description
                        await db.commit()
                        from app.models.models import SessionMember
                        members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == session_id))
                        members = members_result.scalars().all()
                        progress_msg = {"type": "task_progress", "session_id": session_id, "agent_id": agent_id, "agent_name": agent.name, "percent": percent, "description": description}
                        for m in members:
                            if m.member_type == "user":
                                await ws_manager.send_to_user(m.member_id, progress_msg)
                            elif m.member_type == "agent":
                                await ws_manager.send_to_agent(m.member_id, progress_msg)

            elif msg_type == "message":
                # 保持向后兼容
                await ws_manager.broadcast_to_group(
                    data.get("target_user_ids", []),
                    data.get("target_agent_ids", []),
                    {"type": "message", "sender_type": "agent", "sender_id": agent_id, "data": data}
                )
    except WebSocketDisconnect:
        ws_manager.disconnect_agent(agent_id, websocket)
        # Mark agent as offline
        async with async_session() as db:
            result = await db.execute(select(Agent).where(Agent.id == agent_id))
            agent = result.scalar_one_or_none()
            if agent:
                agent.status = "offline"
                await db.commit()
