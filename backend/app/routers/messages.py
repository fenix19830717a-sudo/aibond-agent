from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
from datetime import datetime, timezone

from app.database import get_db
from app.models.models import Message, Group, User, Agent
from app.security import rate_limit, sanitize_text

router = APIRouter(prefix="/api/messages", tags=["messages"])

class SendMessageRequest(BaseModel):
    group_id: str = Field(..., min_length=1)
    sender_type: str = Field(..., pattern=r"^(user|agent)$")
    sender_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=10000)
    msg_type: str = Field("text", pattern=r"^(text|file|system|workflow_trigger)$")
    metadata: dict | None = None

@router.post("/")
async def send_message(req: SendMessageRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Rate limit: 60 messages per minute per IP
    await rate_limit(request, limit=60, window=60)

    # Verify group exists
    group_result = await db.execute(select(Group).where(Group.id == req.group_id))
    if not group_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Group not found")

    # Verify sender exists
    if req.sender_type == "user":
        sender_result = await db.execute(select(User).where(User.id == req.sender_id))
        if not sender_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Sender user not found")
    else:
        sender_result = await db.execute(select(Agent).where(Agent.id == req.sender_id))
        if not sender_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Sender agent not found")

    # Sanitize content
    safe_content = sanitize_text(req.content, max_length=10000)

    message = Message(
        id=str(uuid.uuid4()),
        group_id=req.group_id,
        sender_type=req.sender_type,
        sender_user_id=req.sender_id if req.sender_type == "user" else None,
        sender_agent_id=req.sender_id if req.sender_type == "agent" else None,
        msg_type=req.msg_type,
        content=safe_content,
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

    # WebSocket 推送给群组成员
    from app.websocket.manager import ws_manager
    await ws_manager.broadcast_to_group_message(req.group_id, {
        "type": "message",
        "id": message.id,
        "sender_type": message.sender_type,
        "sender_id": req.sender_id,
        "sender_name": sender_name,
        "content": safe_content,
        "msg_type": message.msg_type,
        "group_id": req.group_id,
    })

    return {
        "id": message.id,
        "sender_type": message.sender_type,
        "sender_name": sender_name,
        "msg_type": message.msg_type,
        "content": message.content,
        "metadata": message.msg_metadata,
        "created_at": str(message.created_at),
    }
