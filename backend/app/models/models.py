from sqlalchemy import Column, String, Integer, Boolean, DateTime, Float, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=True)
    hashed_password = Column(String(128), nullable=False)
    display_name = Column(String(100), default="")
    avatar = Column(String(255), default="")
    role = Column(String(20), default="user")  # user, admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    group_memberships = relationship("GroupMember", back_populates="user")
    messages = relationship("Message", back_populates="sender_user")

class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    api_key = Column(String(128), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Capabilities
    skills = Column(JSON, default=list)  # ["code_review", "git_operations"]
    mcp_endpoints = Column(JSON, default=list)
    callback_url = Column(String(255), default="")

    capabilities = Column(JSON, default=lambda: {
        "accepts_websocket": True,
        "accepts_webhook": False,
        "accepts_polling": False
    })

    # Status
    status = Column(String(20), default="offline")  # online, offline, busy
    last_heartbeat = Column(DateTime, default=None)
    current_address = Column(String(255), default="")  # current reachable address

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    group_memberships = relationship("GroupMember", back_populates="agent")
    messages = relationship("Message", back_populates="sender_agent")

class Group(Base):
    __tablename__ = "groups"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    avatar = Column(String(255), default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    members = relationship("GroupMember", back_populates="group")
    messages = relationship("Message", back_populates="group")
    sessions = relationship("Session", back_populates="group")

class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(String(36), primary_key=True)
    group_id = Column(String(36), ForeignKey("groups.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=True)
    role = Column(String(20), default="member")  # owner, lead, member, viewer
    can_auto_reply = Column(Boolean, default=False)  # Agent: can reply without being @mentioned
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    group = relationship("Group", back_populates="members")
    user = relationship("User", back_populates="group_memberships")
    agent = relationship("Agent", back_populates="group_memberships")

class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)
    group_id = Column(String(36), ForeignKey("groups.id"), nullable=False)
    title = Column(String(200), default="")
    description = Column(Text, default="")
    status = Column(String(20), default="active")  # active, paused, completed, cancelled
    priority = Column(String(10), default="normal")  # low, normal, high, urgent

    assigner_id = Column(String(36), default="")      # 分配者 ID
    assigner_type = Column(String(10), default="")    # "user" or "agent"
    assignee_ids = Column(JSON, default=list)           # 被分配者 ID 列表

    context = Column(JSON, default=dict)                # 任务上下文
    parent_session_id = Column(String(36), default="")  # 父会话 ID（子任务）

    progress = Column(Integer, default=0)  # 0-100
    progress_description = Column(Text, default="")
    assigned_at = Column(DateTime, default=None)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, default=None)

    # Relationships
    group = relationship("Group", back_populates="sessions")
    messages = relationship("Message", back_populates="session")
    members = relationship("SessionMember", back_populates="session")


class SessionMember(Base):
    __tablename__ = "session_members"

    id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    member_type = Column(String(10), nullable=False)  # "user" or "agent"
    member_id = Column(String(36), nullable=False)
    role = Column(String(20), default="participant")  # participant, observer, lead
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    session = relationship("Session", back_populates="members")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True)
    group_id = Column(String(36), ForeignKey("groups.id"), nullable=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)  # 新增：关联会话
    sender_type = Column(String(10), nullable=False)  # "user" or "agent"
    sender_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    sender_agent_id = Column(String(36), ForeignKey("agents.id"), nullable=True)

    msg_type = Column(String(20), default="text")  # text, file, system, workflow_trigger, task_assign, task_complete
    content = Column(Text, default="")
    msg_metadata = Column("metadata", JSON, default=dict)  # mentions, files, etc.

    mentions = Column(JSON, default=list)  # 被提及的 agent/user ID 列表
    is_read = Column(Boolean, default=False)

    status = Column(String(20), default="sent")  # sent, delivered, read

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    group = relationship("Group", back_populates="messages")
    session = relationship("Session", back_populates="messages")
    sender_user = relationship("User", back_populates="messages", foreign_keys=[sender_user_id])
    sender_agent = relationship("Agent", back_populates="messages", foreign_keys=[sender_agent_id])

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    group_id = Column(String(36), ForeignKey("groups.id"), nullable=True)

    # Workflow definition (nodes and edges as JSON)
    definition = Column(JSON, default=dict)

    trigger_type = Column(String(20), default="manual")  # manual, message, schedule
    trigger_config = Column(JSON, default=dict)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"

    id = Column(String(36), primary_key=True)
    workflow_id = Column(String(36), ForeignKey("workflows.id"), nullable=False)
    status = Column(String(20), default="running")  # running, paused, completed, failed
    current_node_id = Column(String(36), default="")
    context = Column(JSON, default=dict)  # shared data across nodes
    node_results = Column(JSON, default=list)  # execution history

    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, default=None)


class File(Base):
    __tablename__ = "files"

    id = Column(String(36), primary_key=True)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_size = Column(Integer, default=0)
    mime_type = Column(String(100), default="")
    uploader_type = Column(String(10), nullable=False)  # user or agent
    uploader_id = Column(String(36), nullable=False)
    group_id = Column(String(36), ForeignKey("groups.id"), nullable=True)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=True)
    storage_path = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class OfflineMessage(Base):
    __tablename__ = "offline_messages"

    id = Column(String(36), primary_key=True)
    target_type = Column(String(10), nullable=False)  # user or agent
    target_id = Column(String(36), nullable=False)
    message_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    delivered_at = Column(DateTime, default=None)
