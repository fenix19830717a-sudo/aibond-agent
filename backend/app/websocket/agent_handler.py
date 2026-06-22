"""Agent WebSocket handler - extracted from main.py."""

import re
import uuid
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.models import (
    Agent,
    Message,
    GroupMember,
    OfflineMessage,
    Session as SessionModel,
    SessionMember,
)
from app.websocket.manager import ws_manager


async def _notify_session_members(session_id: str, payload: dict):
    """Broadcast a message to all members of a session."""
    async with async_session() as db:
        members_result = await db.execute(
            select(SessionMember).where(SessionMember.session_id == session_id)
        )
        members = members_result.scalars().all()

    for m in members:
        if m.member_type == "user":
            await ws_manager.send_to_user(m.member_id, payload)
        elif m.member_type == "agent":
            await ws_manager.send_to_agent(m.member_id, payload)


async def _parse_mentions(content: str, db: AsyncSession, group_id: str | None = None, session_id: str | None = None) -> list[str]:
    """Parse @mentions from message content and return list of mentioned IDs."""
    mention_ids: list[str] = []
    mention_names = re.findall(r"@(\S+)", content)
    if not mention_names:
        return mention_ids

    for name in mention_names:
        if name.lower() == "all":
            if session_id:
                members_result = await db.execute(
                    select(SessionMember).where(SessionMember.session_id == session_id)
                )
                all_members = members_result.scalars().all()
                for sm in all_members:
                    if sm.member_id not in mention_ids:
                        mention_ids.append(sm.member_id)
            elif group_id:
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
            agent_result = await db.execute(
                select(Agent).where(Agent.name == name)
            )
            matched_agent = agent_result.scalar_one_or_none()
            if matched_agent and matched_agent.id not in mention_ids:
                mention_ids.append(matched_agent.id)

    return mention_ids


async def _send_mention_notifications(mention_ids: list[str], notification: dict):
    """Send mention notifications to each mentioned user/agent."""
    for mid in mention_ids:
        async with async_session() as db:
            check_agent = await db.execute(select(Agent).where(Agent.id == mid))
            if check_agent.scalar_one_or_none():
                await ws_manager.send_to_agent(mid, notification)
            else:
                await ws_manager.send_to_user(mid, notification)


async def handle_agent_websocket(websocket: WebSocket, agent_id: str, api_key: str = Query(...)):
    """Handle all Agent WebSocket communication lifecycle.

    Validates credentials, manages connection, processes all message types,
    and handles disconnection cleanup.
    """
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

    # Send welcome message with agent info and skills
    welcome = {
        "type": "welcome",
        "agent_id": agent_id,
        "agent_name": agent.name,
        "skills": agent.skills or [],
    }
    await websocket.send_json(welcome)

    # Push backlogged offline messages
    async with async_session() as db:
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
                await _handle_heartbeat(websocket, agent_id, data)

            elif msg_type == "register":
                await _handle_register(websocket, agent_id, data)

            elif msg_type == "send_message":
                await _handle_send_message(websocket, agent_id, agent, data)

            elif msg_type == "send_group_message":
                await _handle_send_group_message(websocket, agent_id, agent, data)

            elif msg_type == "task_assign":
                await _handle_task_assign(websocket, agent_id, agent, data)

            elif msg_type == "send_session_message":
                await _handle_send_session_message(websocket, agent_id, agent, data)

            elif msg_type == "task_complete":
                await _handle_task_complete(websocket, agent_id, data)

            elif msg_type == "task_accept":
                await _handle_task_accept(websocket, agent_id, agent, data)

            elif msg_type == "task_reject":
                await _handle_task_reject(websocket, agent_id, agent, data)

            elif msg_type == "task_progress":
                await _handle_task_progress(websocket, agent_id, agent, data)

            elif msg_type == "message":
                # Backward compatibility
                await ws_manager.broadcast_to_group(
                    data.get("target_user_ids", []),
                    data.get("target_agent_ids", []),
                    {"type": "message", "sender_type": "agent", "sender_id": agent_id, "data": data},
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


# ── Individual message type handlers ──

async def _handle_heartbeat(websocket: WebSocket, agent_id: str, data: dict):
    """Process heartbeat and update agent status."""
    async with async_session() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if agent:
            agent.last_heartbeat = datetime.now(timezone.utc)
            if data.get("address"):
                addr = str(data["address"])[:255]
                agent.current_address = addr
            await db.commit()
    await websocket.send_json({"type": "heartbeat_ack"})


async def _handle_register(websocket: WebSocket, agent_id: str, data: dict):
    """Process capability registration."""
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


async def _handle_send_message(websocket: WebSocket, agent_id: str, agent: Agent, data: dict):
    """Agent sends a direct message to a user or another agent."""
    target_id = data.get("target_id")
    target_type = data.get("target_type", "user")
    content = data.get("content", "")

    # Persist message to database
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

    # Push via WebSocket to target
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


async def _handle_send_group_message(websocket: WebSocket, agent_id: str, agent: Agent, data: dict):
    """Agent sends a message to a group."""
    group_id = data.get("group_id")
    content = data.get("content", "")

    # Verify agent is a group member
    async with async_session() as db:
        member_check = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.agent_id == agent_id,
            )
        )
        if not member_check.scalar_one_or_none():
            await websocket.send_json({"type": "error", "message": "Not a member of this group"})
            return

        # Parse @mentions
        mention_ids = await _parse_mentions(content, db, group_id=group_id)

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

    # Broadcast to group members
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

    # Send @mention notifications
    if mention_ids:
        mention_notification = {
            "type": "mention",
            "message_id": msg.id,
            "group_id": group_id,
            "sender_id": agent_id,
            "sender_name": agent.name,
            "content": content,
        }
        await _send_mention_notifications(mention_ids, mention_notification)


async def _handle_task_assign(websocket: WebSocket, agent_id: str, agent: Agent, data: dict):
    """Agent assigns a task to another agent, creating a session."""
    target_agent_id = data.get("target_agent_id")
    group_id = data.get("group_id")
    title = data.get("title", "unnamed task")
    description = data.get("description", "")
    priority = data.get("priority", "normal")
    context = data.get("context", {})

    async with async_session() as db:
        # Create session
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

        # Add members
        db.add(SessionMember(id=str(uuid.uuid4()), session_id=session.id, member_type="agent", member_id=agent_id, role="lead"))
        db.add(SessionMember(id=str(uuid.uuid4()), session_id=session.id, member_type="agent", member_id=target_agent_id, role="participant"))

        # System message
        sys_msg = Message(
            id=str(uuid.uuid4()),
            group_id=group_id,
            session_id=session.id,
            sender_type="system",
            msg_type="system",
            content=f"Task assigned: {title}",
            msg_metadata={"event": "task_assigned", "from_agent": agent_id, "to_agent": target_agent_id},
        )
        db.add(sys_msg)
        await db.commit()

    # Notify both parties
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


async def _handle_send_session_message(websocket: WebSocket, agent_id: str, agent: Agent, data: dict):
    """Agent sends a message within a session."""
    session_id = data.get("session_id")
    content = data.get("content", "")
    msg_type_inner = data.get("msg_type", "text")

    async with async_session() as db:
        session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
        session = session_result.scalar_one_or_none()
        if not session or session.status not in ("active", "paused"):
            await websocket.send_json({"type": "error", "message": "Session not found or not active"})
            return

        # Verify membership
        member_result = await db.execute(
            select(SessionMember).where(
                SessionMember.session_id == session_id,
                SessionMember.member_type == "agent",
                SessionMember.member_id == agent_id,
            )
        )
        if not member_result.scalar_one_or_none():
            await websocket.send_json({"type": "error", "message": "Not a member of this session"})
            return

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

        # Query session members for @mentions and broadcast
        members_result = await db.execute(select(SessionMember).where(SessionMember.session_id == session_id))
        members = members_result.scalars().all()

        # Parse @mentions
        mention_ids = await _parse_mentions(content, db, session_id=session_id)
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

    # Send @mention notifications
    if mention_ids:
        mention_notification = {
            "type": "mention",
            "message_id": msg.id,
            "session_id": session_id,
            "sender_id": agent_id,
            "sender_name": agent.name,
            "content": content,
        }
        await _send_mention_notifications(mention_ids, mention_notification)


async def _handle_task_complete(websocket: WebSocket, agent_id: str, data: dict):
    """Agent completes a task."""
    session_id = data.get("session_id")
    result_data = data.get("result", {})
    summary = data.get("summary", "")

    async with async_session() as db:
        session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
        session = session_result.scalar_one_or_none()
        if session:
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)
            await db.commit()

            # System message
            sys_msg = Message(
                id=str(uuid.uuid4()),
                group_id=session.group_id,
                session_id=session_id,
                sender_type="system",
                msg_type="system",
                content=f"Task completed: {session.title}",
                msg_metadata={"event": "task_completed", "result": result_data, "summary": summary},
            )
            db.add(sys_msg)
            await db.commit()

    complete_msg = {
        "type": "task_completed",
        "session_id": session_id,
        "result": result_data,
        "summary": summary,
        "completed_by": agent_id,
    }
    await _notify_session_members(session_id, complete_msg)


async def _handle_task_accept(websocket: WebSocket, agent_id: str, agent: Agent, data: dict):
    """Agent accepts a task assignment."""
    session_id = data.get("session_id")
    async with async_session() as db:
        session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
        session = session_result.scalar_one_or_none()
        if session:
            # Verify this agent is an assignee
            if agent_id in (session.assignee_ids or []):
                session.status = "active"
                session.assigned_at = datetime.now(timezone.utc)
                await db.commit()
                accept_msg = {
                    "type": "task_accepted",
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "agent_name": agent.name,
                }
                await _notify_session_members(session_id, accept_msg)


async def _handle_task_reject(websocket: WebSocket, agent_id: str, agent: Agent, data: dict):
    """Agent rejects a task assignment."""
    session_id = data.get("session_id")
    reason = data.get("reason", "")
    async with async_session() as db:
        session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
        session = session_result.scalar_one_or_none()
        if session:
            session.status = "cancelled"
            await db.commit()
            reject_msg = {
                "type": "task_rejected",
                "session_id": session_id,
                "agent_id": agent_id,
                "agent_name": agent.name,
                "reason": reason,
            }
            await _notify_session_members(session_id, reject_msg)


async def _handle_task_progress(websocket: WebSocket, agent_id: str, agent: Agent, data: dict):
    """Agent reports task progress."""
    session_id = data.get("session_id")
    percent = data.get("percent", 0)
    description = data.get("description", "")
    async with async_session() as db:
        session_result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
        session = session_result.scalar_one_or_none()
        if session:
            session.progress = percent
            session.progress_description = description
            await db.commit()
            progress_msg = {
                "type": "task_progress",
                "session_id": session_id,
                "agent_id": agent_id,
                "agent_name": agent.name,
                "percent": percent,
                "description": description,
            }
            await _notify_session_members(session_id, progress_msg)
