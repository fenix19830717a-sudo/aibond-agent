from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import uuid

from app.database import get_db
from app.models.models import Group, GroupMember, User, Agent
from app.security import rate_limit

router = APIRouter(prefix="/api/groups", tags=["groups"])

class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=500)
    owner_id: str = Field(..., min_length=1)

class AddMemberRequest(BaseModel):
    member_type: str = Field(..., pattern=r"^(user|agent)$")
    member_id: str = Field(..., min_length=1)
    role: str = Field("member", pattern=r"^(owner|lead|admin|member|viewer)$")

@router.post("/")
async def create_group(req: CreateGroupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, limit=20, window=60)

    # Verify owner exists
    owner_result = await db.execute(select(User).where(User.id == req.owner_id))
    if not owner_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Owner not found")

    group = Group(
        id=str(uuid.uuid4()),
        name=req.name,
        description=req.description,
        owner_id=req.owner_id,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)

    # Add owner as admin
    member = GroupMember(
        id=str(uuid.uuid4()),
        group_id=group.id,
        user_id=req.owner_id,
        role="admin",
    )
    db.add(member)
    await db.commit()

    return {"id": group.id, "name": group.name, "description": group.description, "owner_id": group.owner_id}

@router.get("/")
async def list_groups(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Group).where(Group.is_active == True))
    groups = result.scalars().all()

    return [{
        "id": g.id,
        "name": g.name,
        "description": g.description,
        "owner_id": g.owner_id,
        "created_at": str(g.created_at),
    } for g in groups]

@router.get("/{group_id}")
async def get_group(group_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Get members
    members_result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id)
    )
    members = members_result.scalars().all()

    member_list = []
    for m in members:
        if m.user_id:
            user_result = await db.execute(select(User).where(User.id == m.user_id))
            user = user_result.scalar_one_or_none()
            if user:
                member_list.append({"id": user.id, "name": user.display_name or user.username, "type": "user", "role": m.role})
        elif m.agent_id:
            agent_result = await db.execute(select(Agent).where(Agent.id == m.agent_id))
            agent = agent_result.scalar_one_or_none()
            if agent:
                member_list.append({"id": agent.id, "name": agent.name, "type": "agent", "status": agent.status, "skills": agent.skills, "role": m.role})

    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "owner_id": group.owner_id,
        "members": member_list,
    }

@router.post("/{group_id}/members")
async def add_member(group_id: str, req: AddMemberRequest, request: Request, db: AsyncSession = Depends(get_db)):
    await rate_limit(request, limit=30, window=60)

    # Verify group exists
    group_result = await db.execute(select(Group).where(Group.id == group_id))
    if not group_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Group not found")

    # Verify member exists
    if req.member_type == "user":
        member_result = await db.execute(select(User).where(User.id == req.member_id))
        if not member_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="User not found")
    else:
        member_result = await db.execute(select(Agent).where(Agent.id == req.member_id))
        if not member_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Agent not found")

    member = GroupMember(
        id=str(uuid.uuid4()),
        group_id=group_id,
        user_id=req.member_id if req.member_type == "user" else None,
        agent_id=req.member_id if req.member_type == "agent" else None,
        role=req.role,
    )
    db.add(member)
    await db.commit()

    return {"status": "ok", "member_id": member.id}

@router.get("/{group_id}/messages")
async def get_messages(
    group_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    # Validate pagination params
    if limit < 1 or limit > 200:
        limit = 50
    if offset < 0:
        offset = 0

    from app.models.models import Message
    result = await db.execute(
        select(Message)
        .where(Message.group_id == group_id)
        .order_by(Message.created_at.desc())
        .limit(limit).offset(offset)
    )
    messages = result.scalars().all()

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

        msg_list.append({
            "id": msg.id,
            "sender_type": msg.sender_type,
            "sender_name": sender_name,
            "msg_type": msg.msg_type,
            "content": msg.content,
            "metadata": msg.msg_metadata,
            "status": msg.status,
            "created_at": str(msg.created_at),
        })

    return {"messages": list(reversed(msg_list)), "total": len(msg_list)}
