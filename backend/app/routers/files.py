from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid
import os
import shutil

from app.database import get_db
from app.models.models import File as FileModel, Group, Session as SessionModel

router = APIRouter(prefix="/api/files", tags=["files"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    group_id: str = "",
    session_id: str = "",
    uploader_type: str = "user",
    uploader_id: str = "",
    db: AsyncSession = Depends(get_db),
):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    storage_name = f"{file_id}{ext}"
    storage_path = os.path.join(UPLOAD_DIR, storage_name)

    with open(storage_path, "wb") as f:
        content = await file.read()
        f.write(content)

    file_record = FileModel(
        id=file_id,
        filename=storage_name,
        original_name=file.filename or "unnamed",
        file_size=len(content),
        mime_type=file.content_type or "",
        uploader_type=uploader_type,
        uploader_id=uploader_id,
        group_id=group_id or None,
        session_id=session_id or None,
        storage_path=storage_path,
    )
    db.add(file_record)
    await db.commit()

    return {
        "id": file_id,
        "filename": file.filename,
        "size": len(content),
        "mime_type": file.content_type,
    }


@router.get("/list")
async def list_files(
    group_id: str = None,
    session_id: str = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(FileModel)
    if group_id:
        query = query.where(FileModel.group_id == group_id)
    if session_id:
        query = query.where(FileModel.session_id == session_id)
    result = await db.execute(query)
    files = result.scalars().all()
    return [
        {
            "id": f.id,
            "filename": f.original_name,
            "size": f.file_size,
            "mime_type": f.mime_type,
            "uploader_type": f.uploader_type,
            "uploader_id": f.uploader_id,
            "created_at": str(f.created_at),
        }
        for f in files
    ]


@router.get("/{file_id}")
async def download_file(file_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FileModel).where(FileModel.id == file_id))
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=file_record.storage_path,
        filename=file_record.original_name,
        media_type=file_record.mime_type,
    )
