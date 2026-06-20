"""Session (Task Conversation) Router"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import uuid
from datetime import datetime, timezone

from app.database import get_db
from app.models.models import Session, SessionMember, Message, Group, GroupMember, Agent, User
from app.security import rate_limit
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    group_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=500)
    assigner_type: str = Field(..., pattern=r"^(user|agent)$")
    assigner_id: str = Field(..., min_length=1)
    assignee_ids: list[str] = Field(default_factory=list)
    priority: str = Field("normal", pattern=r"^(low|normal|high|urgent)$")
    context: dict | None = None
    parent_session_id: str = Field("", max_length=36)


class SessionMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    sender_type: str = Field(..., pattern=r"^(user|agent)$")
    sender_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=10000)
    msg_type: str = Field("text", pattern=r"^(text|file|system|task_assign|task_complete|task_cancel|task_update)$")
    metadata: dict | None = None


class UpdateSessionStatusRequest(BaseModel):
    status: str = Field(..., pattern=r"^(active|paused|completed|cancelled)$")


@router.post("/")
async def create_session(req: CreateSessionRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, limit=20, window=60)

    # Verify group exists
    group_result = await db.execute(select(Group).where(Group.id == req.group_id))
    if not group_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Group not found")

    session = Session(
        id=str(uuid.uuid4()),
        group_id=req.group_id,
        title=req.title,
        description=req.description,
        status="active",
        priority=req.priority,
        assigner_id=req.assigner_id,
        assigner_type=req.assigner_type,
        assignee_ids=req.assignee_ids,
        context=req.context or {},
        parent_session_id=req.parent_session_id or "",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # Add members: assigner + assignees
    members_to_add = [(req.assigner_type, req.assigner_id, "lead")]
    for aid in req.assignee_ids:
        members_to_add.append(("agent", aid, "participant"))

    for mtype, mid, role in members_to_add:
        member = SessionMember(
            id=str(uuid.uuid4()),
            session_id=session.id,
            member_type=mtype,
            member_id=mid,
            role=role,
        )
        db.add(member)

    # Add a system message marking session creation
    sys_msg = Message(
        id=str(uuid.uuid4()),
        group_id=req.group_id,
        session_id=session.id,
        sender_type="system",
        msg_type="system",
        content=f"任务会话已创建: {req.title}",
        msg_metadata={"event": "session_created", "assigner": req.assigner_id, "assignees": req.assignee_ids},
    )
    db.add(sys_msg)
    await db.commit()

    return {
        "id": session.id,
        "group_id": session.group_id,
        "title": session.title,
        "description": session.description,
        "status": session.status,
        "priority": session.priority,
        "assigner_id": session.assigner_id,
        "assigner_type": session.assigner_type,
        "assignee_ids": session.assignee_ids,
        "context": session.context,
        "created_at": str(session.created_at),
    }


@router.get("/")
async def list_sessions(
    group_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(Session).where(Session.status != "cancelled")
    if group_id:
        query = query.where(Session.group_id == group_id)
    if status:
        if status not in ("active", "paused", "completed", "cancelled"):
            raise HTTPException(status_code=400, detail="Invalid status filter")
        query = query.where(Session.status == status)
    query = query.order_by(Session.created_at.desc())
    result = await db.execute(query)
    sessions = result.scalars().all()

    return [{
        "id": s.id,
        "group_id": s.group_id,
        "title": s.title,
        "description": s.description,
        "status": s.status,
        "priority": s.priority,
        "assigner_id": s.assigner_id,
        "assigner_type": s.assigner_type,
        "assignee_ids": s.assignee_ids,
        "context": s.context,
        "created_at": str(s.created_at),
        "updated_at": str(s.updated_at),
        "completed_at": str(s.completed_at) if s.completed_at else None,
    } for s in sessions]


@router.get("/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get members
    members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == session_id))
    members = members_result.scalars().all()

    member_list = []
    for m in members:
        name = ""
        if m.member_type == "user":
            user_result = await db.execute(select(User).where(User.id == m.member_id))
            user = user_result.scalar_one_or_none()
            name = user.display_name or user.username if user else "Unknown"
        else:
            agent_result = await db.execute(select(Agent).where(Agent.id == m.member_id))
            agent = agent_result.scalar_one_or_none()
            name = agent.name if agent else "Unknown"
        member_list.append({"id": m.member_id, "type": m.member_type, "name": name, "role": m.role})

    # Get messages
    msgs_result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    )
    messages = msgs_result.scalars().all()

    msg_list = []
    for msg in messages:
        sender_name = ""
        if msg.sender_user_id:
            user_result = await db.execute(select(User).where(User.id == msg.sender_user_id))
            user = user_result.scalar_one_or_none()
            sender_name = user.display_name or user.username if user else "Unknown"
        elif msg.sender_agent_id:
            agent_result = await db.execute(select(Agent).where(Agent.id == msg.sender_agent_id))
            agent = agent_result.scalar_one_or_none()
            sender_name = agent.name if agent else "Unknown"
        else:
            sender_name = "System"

        msg_list.append({
            "id": msg.id,
            "sender_type": msg.sender_type,
            "sender_name": sender_name,
            "msg_type": msg.msg_type,
            "content": msg.content,
            "metadata": msg.msg_metadata,
            "created_at": str(msg.created_at),
        })

    return {
        "id": session.id,
        "group_id": session.group_id,
        "title": session.title,
        "description": session.description,
        "status": session.status,
        "priority": session.priority,
        "assigner_id": session.assigner_id,
        "assigner_type": session.assigner_type,
        "assignee_ids": session.assignee_ids,
        "context": session.context,
        "members": member_list,
        "messages": msg_list,
        "created_at": str(session.created_at),
        "updated_at": str(session.updated_at),
        "completed_at": str(session.completed_at) if session.completed_at else None,
    }


@router.post("/{session_id}/messages")
async def send_session_message(req: SessionMessageRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, limit=60, window=60)

    # Verify session exists and is active
    session_result = await db.execute(select(Session).where(Session.id == req.session_id))
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status not in ("active", "paused"):
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, cannot send messages")

    # Verify sender is a member
    member_result = await db.execute(
        select(SessionMember).where(
            SessionMember.session_id == req.session_id,
            SessionMember.member_type == req.sender_type,
            SessionMember.member_id == req.sender_id,
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Sender is not a member of this session")

    message = Message(
        id=str(uuid.uuid4()),
        group_id=session.group_id,
        session_id=req.session_id,
        sender_type=req.sender_type,
        sender_user_id=req.sender_id if req.sender_type == "user" else None,
        sender_agent_id=req.sender_id if req.sender_type == "agent" else None,
        msg_type=req.msg_type,
        content=req.content,
        msg_metadata=req.metadata or {},
        status="sent",
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    # Get sender name
    sender_name = ""
    if req.sender_type == "user":
        user_result = await db.execute(select(User).where(User.id == req.sender_id))
        user = user_result.scalar_one_or_none()
        sender_name = user.display_name or user.username if user else "Unknown"
    else:
        agent_result = await db.execute(select(Agent).where(Agent.id == req.sender_id))
        agent = agent_result.scalar_one_or_none()
        sender_name = agent.name if agent else "Unknown"

    # WebSocket broadcast to session members
    broadcast_msg = {
        "type": "session_message",
        "id": message.id,
        "session_id": req.session_id,
        "sender_type": message.sender_type,
        "sender_id": req.sender_id,
        "sender_name": sender_name,
        "msg_type": message.msg_type,
        "content": message.content,
        "metadata": message.msg_metadata,
        "created_at": str(message.created_at),
    }

    members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == req.session_id))
    members = members_result.scalars().all()
    for m in members:
        if m.member_type == "user":
            await ws_manager.send_to_user(m.member_id, broadcast_msg)
        elif m.member_type == "agent":
            await ws_manager.send_to_agent(m.member_id, broadcast_msg)

    return {
        "id": message.id,
        "session_id": req.session_id,
        "sender_type": message.sender_type,
        "sender_name": sender_name,
        "msg_type": message.msg_type,
        "content": message.content,
        "created_at": str(message.created_at),
    }


@router.post("/{session_id}/status")
async def update_session_status(session_id: str, req: UpdateSessionStatusRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.status = req.status
    if req.status == "completed":
        session.completed_at = datetime.now(timezone.utc)
    await db.commit()

    # Notify members
    members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == session_id))
    members = members_result.scalars().all()
    for m in members:
        status_msg = {
            "type": "session_status_changed",
            "session_id": session_id,
            "status": req.status,
        }
        if m.member_type == "user":
            await ws_manager.send_to_user(m.member_id, status_msg)
        elif m.member_type == "agent":
            await ws_manager.send_to_agent(m.member_id, status_msg)

    return {"status": "ok", "session_id": session_id, "new_status": req.status}
