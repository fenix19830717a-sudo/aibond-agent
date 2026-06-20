from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models.models import OfflineMessage

router = APIRouter(prefix="/api/offline", tags=["offline"])


@router.get("/")
async def get_offline_messages(
    target_type: str,
    target_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OfflineMessage)
        .where(
            OfflineMessage.target_type == target_type,
            OfflineMessage.target_id == target_id,
            OfflineMessage.delivered_at == None,
        )
        .order_by(OfflineMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "message": m.message_json,
            "created_at": str(m.created_at),
        }
        for m in messages
    ]


@router.post("/{msg_id}/ack")
async def acknowledge_message(msg_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OfflineMessage).where(OfflineMessage.id == msg_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.delivered_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "ok"}
