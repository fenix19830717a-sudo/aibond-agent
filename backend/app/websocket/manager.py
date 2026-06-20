import json
import uuid
from typing import Dict, Set
from datetime import datetime, timezone
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # user_id -> set of websocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # agent_id -> set of websocket connections
        self.agent_connections: Dict[str, Set[WebSocket]] = {}

    async def connect_user(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)

    async def connect_agent(self, agent_id: str, websocket: WebSocket):
        await websocket.accept()
        if agent_id not in self.agent_connections:
            self.agent_connections[agent_id] = set()
        self.agent_connections[agent_id].add(websocket)

    def disconnect_user(self, user_id: str, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    def disconnect_agent(self, agent_id: str, websocket: WebSocket):
        if agent_id in self.agent_connections:
            self.agent_connections[agent_id].discard(websocket)
            if not self.agent_connections[agent_id]:
                del self.agent_connections[agent_id]

    async def send_to_user(self, user_id: str, data: dict):
        if user_id in self.active_connections:
            dead = []
            for ws in self.active_connections[user_id]:
                try:
                    await ws.send_json(data)
                except:
                    dead.append(ws)
            for ws in dead:
                self.disconnect_user(user_id, ws)
        else:
            # 目标不在线，存入离线消息
            await self._store_offline_message("user", user_id, data)

    async def send_to_agent(self, agent_id: str, data: dict):
        if agent_id in self.agent_connections:
            dead = []
            for ws in self.agent_connections[agent_id]:
                try:
                    await ws.send_json(data)
                except:
                    dead.append(ws)
            for ws in dead:
                self.disconnect_agent(agent_id, ws)
        else:
            # 目标不在线，存入离线消息
            await self._store_offline_message("agent", agent_id, data)

    async def _store_offline_message(self, target_type: str, target_id: str, data: dict):
        """将消息存入离线消息表，等待目标上线后投递"""
        try:
            from app.database import async_session
            from app.models.models import OfflineMessage

            async with async_session() as db:
                offline_msg = OfflineMessage(
                    id=str(uuid.uuid4()),
                    target_type=target_type,
                    target_id=target_id,
                    message_json=data,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(offline_msg)
                await db.commit()
        except Exception:
            # 离线存储失败不应影响主流程，静默忽略
            pass

    async def broadcast_to_group(self, user_ids: list, agent_ids: list, data: dict):
        for uid in user_ids:
            await self.send_to_user(uid, data)
        for aid in agent_ids:
            await self.send_to_agent(aid, data)

    async def broadcast_to_group_message(self, group_id: str, message: dict):
        """根据群组 ID 广播消息给所有群组成员"""
        from app.database import async_session
        from app.models.models import GroupMember
        from sqlalchemy import select

        async with async_session() as db:
            result = await db.execute(select(GroupMember).where(GroupMember.group_id == group_id))
            members = result.scalars().all()

        for member in members:
            if member.user_id:
                await self.send_to_user(member.user_id, message)
            elif member.agent_id:
                await self.send_to_agent(member.agent_id, message)

ws_manager = ConnectionManager()
