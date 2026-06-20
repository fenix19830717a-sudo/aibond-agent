from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import bcrypt
from jose import jwt, JWTError
import uuid

from app.database import get_db
from app.config import settings
from app.models.models import User
from app.security import (
    rate_limit, check_login_lockout, record_login_failure, record_login_success,
    validate_username, validate_password
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_\-\.]+$")
    password: str = Field(..., min_length=8)
    email: str | None = Field(None, max_length=100)

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenRequest(BaseModel):
    token: str

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc), "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')

@router.post("/register")
async def register(req: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Rate limit
    await rate_limit(request, limit=5, window=300)  # 5 registrations per 5 minutes

    # Validate username format
    if not validate_username(req.username):
        raise HTTPException(status_code=400, detail="Username must be 3-50 characters, alphanumeric with _-. only")

    # Validate password strength
    pwd_valid, pwd_error = validate_password(req.password)
    if not pwd_valid:
        raise HTTPException(status_code=400, detail=pwd_error)

    # Check if user exists
    result = await db.execute(select(User).where(User.username == req.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already registered")

    # Check email uniqueness if provided
    if req.email:
        email_result = await db.execute(select(User).where(User.email == req.email))
        if email_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        username=req.username,
        email=req.email,
        hashed_password=get_password_hash(req.password),
        display_name=req.username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": user.id, "username": user.username})
    return {"token": token, "user": {"id": user.id, "username": user.username, "display_name": user.display_name}}

@router.post("/login")
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Rate limit login attempts
    await rate_limit(request, limit=10, window=60)

    # Check lockout
    lockout = check_login_lockout(req.username)
    if lockout:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account locked. Try again in {int(lockout)} seconds."
        )

    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        record_login_failure(req.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is disabled")

    record_login_success(req.username)
    token = create_access_token({"sub": user.id, "username": user.username})
    return {"token": token, "user": {"id": user.id, "username": user.username, "display_name": user.display_name}}

@router.post("/me")
async def get_current_user(req: TokenRequest, db: AsyncSession = Depends(get_db)):
    """Get current user info from token (POST for security, token in body)."""
    try:
        payload = jwt.decode(req.token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        # Check token type
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        # Check expiration explicitly (jose should do this, but double-check)
        exp = payload.get("exp")
        if exp and datetime.now(timezone.utc).timestamp() > exp:
            raise HTTPException(status_code=401, detail="Token expired")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is disabled")

    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}
