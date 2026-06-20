import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Layout, List, Input, Button, Avatar, Tag, Empty, Typography, Space,
  Tabs, Progress, Badge, Modal, Form, Select, Upload, message,
  Divider,
} from 'antd';
import {
  SendOutlined, RobotOutlined, UserOutlined, PlusOutlined,
  PaperClipOutlined, DownloadOutlined,
  ClockCircleOutlined,
  CloseOutlined, TeamOutlined, FileOutlined,
  InfoCircleOutlined, RightOutlined, BellOutlined,
} from '@ant-design/icons';
import { useAuthStore } from '../store/authStore';
import { useChatStore } from '../store/chatStore';
import type { Message, Session } from '../store/chatStore';
import { api } from '../api';

const { Sider, Content } = Layout;
const { Text } = Typography;

// ─── Role color maps ────────────────────────────────────────────
const roleColorMap: Record<string, string> = {
  owner: 'gold',
  lead: 'blue',
  admin: 'purple',
  member: 'default',
  viewer: 'default',
};

const roleLabelMap: Record<string, string> = {
  owner: '群主',
  lead: '队长',
  admin: '管理员',
  member: '成员',
  viewer: '观察者',
};

const statusColorMap: Record<string, string> = {
  pending: 'default',
  assigned: 'processing',
  in_progress: 'processing',
  completed: 'success',
  failed: 'error',
  cancelled: 'warning',
};

const statusLabelMap: Record<string, string> = {
  pending: '待处理',
  assigned: '已分配',
  in_progress: '进行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const priorityColorMap: Record<string, string> = {
  low: 'default',
  medium: 'blue',
  high: 'orange',
  critical: 'red',
};

const priorityLabelMap: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '紧急',
};

// ─── Mention highlight renderer ─────────────────────────────────
const renderContentWithMentions = (content: string, currentUserName?: string) => {
  const parts = content.split(/(@\S+)/g);
  return parts.map((part, idx) => {
    if (part.startsWith('@')) {
      const isMe = currentUserName && part.toLowerCase() === `@${currentUserName.toLowerCase()}`;
      return (
        <span
          key={idx}
          style={{
            color: isMe ? '#1677ff' : '#52c41a',
            fontWeight: isMe ? 600 : 500,
            cursor: 'pointer',
          }}
        >
          {part}
        </span>
      );
    }
    return <span key={idx}>{part}</span>;
  });
};

// ─── File message card ───────────────────────────────────────────
const FileMessageCard: React.FC<{ metadata: any }> = ({ metadata }) => {
  const file = metadata?.file || metadata;
  if (!file) return null;
  return (
    <div
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 8,
        padding: '10px 12px',
        minWidth: 220,
        maxWidth: 320,
        cursor: 'pointer',
      }}
      onClick={() => {
        if (file.id) {
          window.open(api.downloadFile(file.id), '_blank');
        }
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <FileOutlined style={{ fontSize: 20, color: '#1677ff' }} />
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <Text ellipsis style={{ display: 'block', fontSize: 13, maxWidth: 200 }}>
            {file.filename || file.name || '未知文件'}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {file.size ? `${(file.size / 1024).toFixed(1)} KB` : ''}
          </Text>
        </div>
        <DownloadOutlined style={{ color: '#1677ff' }} />
      </div>
    </div>
  );
};

// ─── Task message card ───────────────────────────────────────────
const TaskMessageCard: React.FC<{ metadata: any }> = ({ metadata }) => {
  const task = metadata?.task || metadata;
  if (!task) return null;
  return (
    <div
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.08)',
        borderRadius: 8,
        padding: '10px 12px',
        minWidth: 240,
        maxWidth: 360,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <Text strong style={{ fontSize: 13 }}>{task.title || '任务'}</Text>
        <Tag color={statusColorMap[task.status]} style={{ fontSize: 10 }}>
          {statusLabelMap[task.status] || task.status}
        </Tag>
      </div>
      {task.progress !== undefined && (
        <Progress
          percent={task.progress}
          size="small"
          status={task.status === 'failed' ? 'exception' : task.status === 'completed' ? 'success' : 'active'}
        />
      )}
      {task.description && (
        <Text type="secondary" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
          {task.description}
        </Text>
      )}
    </div>
  );
};

// ─── Session list item ───────────────────────────────────────────
const SessionListItem: React.FC<{
  session: Session;
  isActive: boolean;
  onClick: () => void;
}> = ({ session, isActive, onClick }) => (
  <div
    onClick={onClick}
    style={{
      padding: '10px 12px',
      cursor: 'pointer',
      background: isActive ? 'rgba(22,119,255,0.1)' : 'transparent',
      borderRadius: 6,
      marginBottom: 2,
      borderLeft: isActive ? '3px solid #1677ff' : '3px solid transparent',
      transition: 'all 0.2s',
    }}
  >
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Text ellipsis style={{ fontSize: 13, maxWidth: 140, fontWeight: isActive ? 600 : 400 }}>
        {session.title}
      </Text>
      <Tag color={statusColorMap[session.status]} style={{ fontSize: 10, marginLeft: 4 }}>
        {statusLabelMap[session.status] || session.status}
      </Tag>
    </div>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
      <Text type="secondary" style={{ fontSize: 11 }}>
        {session.assigned_to_name || session.assigned_to?.slice(0, 8)}
      </Text>
      <Tag color={priorityColorMap[session.priority]} style={{ fontSize: 10 }}>
        {priorityLabelMap[session.priority] || session.priority}
      </Tag>
    </div>
    {session.status === 'in_progress' && (
      <Progress percent={session.progress || 0} size="small" style={{ marginTop: 4 }} />
    )}
  </div>
);

// ─── Create session modal ───────────────────────────────────────
const CreateSessionModal: React.FC<{
  open: boolean;
  onClose: () => void;
  groupId: string;
  agents: any[];
  onSuccess: () => void;
}> = ({ open, onClose, groupId, agents, onSuccess }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleCreate = async (values: any) => {
    setLoading(true);
    try {
      await api.createSession(
        groupId,
        values.title,
        values.description || '',
        values.assigned_to,
        values.priority || 'medium'
      );
      message.success('Session 创建成功');
      form.resetFields();
      onClose();
      onSuccess();
    } catch (err: any) {
      message.error(err.message || '创建失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="创建 Session"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnClose
    >
      <Form form={form} onFinish={handleCreate} layout="vertical">
        <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
          <Input placeholder="输入 Session 标题" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea placeholder="输入描述" rows={3} />
        </Form.Item>
        <Form.Item name="assigned_to" label="分配给" rules={[{ required: true, message: '请选择分配对象' }]}>
          <Select
            placeholder="选择 Agent 或用户"
            showSearch
            optionFilterProp="children"
            options={agents.map((a: any) => ({
              value: a.id,
              label: `${a.name || a.username || a.id.slice(0, 8)}`,
            }))}
          />
        </Form.Item>
        <Form.Item name="priority" label="优先级" initialValue="medium">
          <Select
            options={[
              { value: 'low', label: '低' },
              { value: 'medium', label: '中' },
              { value: 'high', label: '高' },
              { value: 'critical', label: '紧急' },
            ]}
          />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            创建
          </Button>
        </Form.Item>
      </Form>
    </Modal>
  );
};

// ─── Right panel: Group info ────────────────────────────────────
const GroupInfoPanel: React.FC<{
  group: any;
  onClose: () => void;
  sessions: Session[];
  onSelectSession: (id: string) => void;
}> = ({ group, onClose, sessions, onSelectSession }) => {
  const [files, setFiles] = useState<any[]>([]);

  useEffect(() => {
    if (group?.id) {
      api.listFiles(group.id).then(setFiles).catch(() => {});
    }
  }, [group?.id]);

  if (!group) return null;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <Text strong>群组信息</Text>
        <Button type="text" icon={<CloseOutlined />} size="small" onClick={onClose} />
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        {/* Group name & description */}
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ fontSize: 15 }}>{group.name}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>{group.description || '暂无描述'}</Text>
        </div>

        <Divider style={{ margin: '12px 0' }} />

        {/* Members */}
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>
            <TeamOutlined style={{ marginRight: 4 }} />
            成员 ({group.members?.length || 0})
          </Text>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {(group.members || []).map((member: any, idx: number) => (
              <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Avatar
                  size={28}
                  icon={member.type === 'agent' || member.member_type === 'agent' ? <RobotOutlined /> : <UserOutlined />}
                  style={{
                    background: member.type === 'agent' || member.member_type === 'agent' ? '#52c41a' : '#1677ff',
                    fontSize: 12,
                  }}
                />
                <div style={{ flex: 1 }}>
                  <Text style={{ fontSize: 12 }}>{member.name || member.member_name || member.id || member.member_id?.slice(0, 12)}</Text>
                </div>
                <Tag color={roleColorMap[member.role]} style={{ fontSize: 10 }}>
                  {roleLabelMap[member.role] || member.role || '成员'}
                </Tag>
              </div>
            ))}
          </div>
        </div>

        <Divider style={{ margin: '12px 0' }} />

        {/* Files */}
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>
            <PaperClipOutlined style={{ marginRight: 4 }} />
            文件 ({files.length})
          </Text>
          {files.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无文件</Text>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {files.map((file: any, idx: number) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 8px',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: 4,
                    cursor: 'pointer',
                  }}
                  onClick={() => window.open(api.downloadFile(file.id), '_blank')}
                >
                  <FileOutlined style={{ color: '#1677ff' }} />
                  <Text ellipsis style={{ flex: 1, fontSize: 12 }}>{file.filename || file.name}</Text>
                  <Text type="secondary" style={{ fontSize: 10 }}>
                    {file.size ? `${(file.size / 1024).toFixed(1)}KB` : ''}
                  </Text>
                </div>
              ))}
            </div>
          )}
        </div>

        <Divider style={{ margin: '12px 0' }} />

        {/* Sessions / Tasks */}
        <div>
          <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>
            <ClockCircleOutlined style={{ marginRight: 4 }} />
            Sessions / 任务 ({sessions.length})
          </Text>
          {sessions.length === 0 ? (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无 Session</Text>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {sessions.map((session) => (
                <div
                  key={session.id}
                  style={{
                    padding: '6px 8px',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: 4,
                    cursor: 'pointer',
                  }}
                  onClick={() => onSelectSession(session.id)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text ellipsis style={{ fontSize: 12, maxWidth: 120 }}>{session.title}</Text>
                    <Tag color={statusColorMap[session.status]} style={{ fontSize: 10 }}>
                      {statusLabelMap[session.status] || session.status}
                    </Tag>
                  </div>
                  {session.status === 'in_progress' && (
                    <Progress percent={session.progress || 0} size="small" style={{ marginTop: 4 }} />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ─── Main Chat component ───────────────────────────────────────
interface GroupInfo {
  id: string;
  name: string;
  description: string;
  members: any[];
}

const Chat: React.FC = () => {
  const { user } = useAuthStore();
  const {
    currentGroupId,
    currentSessionId,
    sessions,
    messages,
    unreadCounts,
    setGroupId,
    setSessionId,
    setSessions,
    updateSession,
    addMessage,
    setMessages,
    incrementUnread,
    clearUnread,
  } = useChatStore();

  const [groups, setGroups] = useState<GroupInfo[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [ws, setWs] = useState<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [currentGroupDetail, setCurrentGroupDetail] = useState<any>(null);
  const [availableAgents, setAvailableAgents] = useState<any[]>([]);
  const [createSessionOpen, setCreateSessionOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('group');

  // Load groups on mount
  useEffect(() => {
    loadGroups();
    loadAvailableAgents();
  }, []);

  // When group changes, load messages, sessions, connect WS
  useEffect(() => {
    if (currentGroupId) {
      loadMessages();
      loadSessions();
      loadGroupDetail();
      connectWebSocket();
      clearUnread(currentGroupId);
    }
    return () => {
      if (ws) ws.close();
    };
  }, [currentGroupId]);

  // When session changes, load session messages
  useEffect(() => {
    if (currentSessionId) {
      loadSessionMessages();
    }
  }, [currentSessionId]);

  // Auto scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadAvailableAgents = async () => {
    try {
      const data = await api.listAvailableAgents();
      setAvailableAgents(data);
    } catch (err) {
      console.error('Failed to load agents:', err);
    }
  };

  const loadGroups = async () => {
    try {
      const data = await api.listGroups();
      setGroups(data);
      if (data.length > 0 && !currentGroupId) {
        setGroupId(data[0].id);
      }
    } catch (err) {
      console.error('Failed to load groups:', err);
    }
  };

  const loadGroupDetail = async () => {
    if (!currentGroupId) return;
    try {
      const detail = await api.getGroup(currentGroupId);
      setCurrentGroupDetail(detail);
    } catch (err) {
      console.error('Failed to load group detail:', err);
    }
  };

  const loadMessages = async () => {
    if (!currentGroupId) return;
    try {
      const data = await api.getMessages(currentGroupId);
      setMessages(data.messages || data);
    } catch (err) {
      console.error('Failed to load messages:', err);
    }
  };

  const loadSessions = async () => {
    if (!currentGroupId) return;
    try {
      const data = await api.listSessions(currentGroupId);
      setSessions(data || []);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    }
  };

  const loadSessionMessages = async () => {
    if (!currentSessionId) return;
    try {
      const session = await api.getSession(currentSessionId);
      // If session has messages embedded
      if (session.messages) {
        setMessages(session.messages);
      }
    } catch (err) {
      console.error('Failed to load session messages:', err);
    }
  };

  const connectWebSocket = () => {
    if (!user || !currentGroupId) return;
    if (ws) ws.close();

    const wsBase = import.meta.env.VITE_WS_BASE || 'ws://localhost:8000';
    const socket = new WebSocket(`${wsBase}/ws/user/${user.id}`);
    socket.onopen = () => console.log('WebSocket connected');
    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWsMessage(data);
      } catch (e) {
        console.error('Failed to parse WS message:', e);
      }
    };
    socket.onclose = () => console.log('WebSocket disconnected');
    setWs(socket);
  };

  const handleWsMessage = useCallback((data: any) => {
    // 后端 WebSocket 消息是平铺格式 { type, id, sender_name, ... }，不是 { type, data: {...} }
    // 兼容两种格式：如果存在 data.data 则用 data.data，否则用 data 本身
    const payload = data.data && typeof data.data === 'object' ? data.data : data;

    switch (data.type) {
      case 'message':
        // Group message
        if (payload.group_id === currentGroupId && !currentSessionId) {
          addMessage(payload);
        } else if (payload.group_id && payload.group_id !== currentGroupId) {
          incrementUnread(payload.group_id);
        }
        break;

      case 'session_message':
        if (payload.session_id === currentSessionId) {
          addMessage(payload);
        }
        // Also update session progress if present
        if (payload.session) {
          updateSession(payload.session);
        }
        break;

      case 'task_assign':
        // Show task assignment notification as a message
        if (payload.group_id === currentGroupId) {
          addMessage({
            id: `task-assign-${Date.now()}`,
            sender_type: 'system',
            sender_name: '系统',
            msg_type: 'notification',
            content: `任务分配: ${payload.title || '新任务'} -> ${payload.assigned_to_name || payload.assigned_to || '未知'}`,
            metadata: { task: payload },
            created_at: new Date().toISOString(),
          });
        }
        break;

      case 'task_progress':
        // Update progress in session
        if (payload.session_id) {
          updateSession({
            id: payload.session_id,
            group_id: payload.group_id || '',
            title: '',
            description: '',
            status: payload.status || 'in_progress',
            priority: '',
            progress: payload.progress || 0,
            progress_description: payload.progress_description || '',
            assigned_to: payload.assigned_to || '',
            created_at: '',
          });
        }
        // Show progress notification
        if (payload.group_id === currentGroupId) {
          addMessage({
            id: `task-progress-${Date.now()}`,
            sender_type: 'system',
            sender_name: '系统',
            msg_type: 'notification',
            content: `任务进度更新: ${payload.title || ''} - ${payload.progress || 0}%`,
            metadata: { task: payload },
            created_at: new Date().toISOString(),
          });
        }
        break;

      case 'task_complete':
        if (payload.session_id) {
          updateSession({
            id: payload.session_id,
            group_id: payload.group_id || '',
            title: '',
            description: '',
            status: 'completed',
            priority: '',
            progress: 100,
            progress_description: payload.summary || '已完成',
            assigned_to: payload.assigned_to || '',
            created_at: '',
          });
        }
        if (payload.group_id === currentGroupId) {
          addMessage({
            id: `task-complete-${Date.now()}`,
            sender_type: 'system',
            sender_name: '系统',
            msg_type: 'notification',
            content: `任务完成: ${payload.title || '任务'}${payload.summary ? '\n' + payload.summary : ''}`,
            metadata: { task: payload },
            created_at: new Date().toISOString(),
          });
        }
        break;

      case 'mention':
        if (payload.group_id === currentGroupId) {
          addMessage({
            id: `mention-${Date.now()}`,
            sender_type: payload.sender_type || 'system',
            sender_name: payload.sender_name || '系统',
            msg_type: 'mention',
            content: payload.content || '',
            metadata: payload,
            created_at: new Date().toISOString(),
            mentions: payload.mentions || [],
          });
        }
        break;

      default:
        // Fallback: treat as regular message
        if (payload && payload.content) {
          addMessage(payload);
        }
        break;
    }
  }, [currentGroupId, currentSessionId, addMessage, incrementUnread, updateSession]);

  const handleSend = async () => {
    if (!inputValue.trim() || !currentGroupId || !user) return;

    const content = inputValue.trim();

    try {
      if (currentSessionId) {
        const msg = await api.sendSessionMessage(currentSessionId, 'user', user.id, content);
        addMessage(msg);
      } else {
        const msg = await api.sendMessage(currentGroupId, 'user', user.id, content);
        addMessage(msg);
      }
      setInputValue('');  // API 成功后再清空输入框
    } catch (err) {
      console.error('Failed to send message:', err);
      // 不清空输入框，让用户可以重试
    }
  };

  const handleFileUpload = async (file: File) => {
    if (!currentGroupId || !user) return false;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('group_id', currentGroupId);
    if (currentSessionId) {
      formData.append('session_id', currentSessionId);
    }

    try {
      const result = await api.uploadFile(formData);
      // Send a file message
      if (currentSessionId) {
        await api.sendSessionMessage(currentSessionId, 'user', user.id, `[文件] ${file.name}`, 'file');
      } else {
        await api.sendMessage(currentGroupId, 'user', user.id, `[文件] ${file.name}`, 'file', { file: result });
      }
      message.success('文件上传成功');
    } catch (err: any) {
      message.error(err.message || '文件上传失败');
    }
    return false; // prevent default upload
  };

  const handleGroupSelect = (groupId: string) => {
    setGroupId(groupId);
    setActiveTab('group');
  };

  const handleSessionSelect = (sessionId: string) => {
    setSessionId(sessionId);
    setActiveTab('session');
  };

  const handleBackToGroup = () => {
    setSessionId(null);
    setActiveTab('group');
    loadMessages();
  };

  const handleCreateSessionSuccess = () => {
    loadSessions();
  };

  const isOwnMessage = (msg: Message) => {
    return msg.sender_type === 'user' && msg.sender_id === user?.id;
  };

  const renderMessageBubble = (msg: Message) => {
    const own = isOwnMessage(msg);
    const isSystem = msg.sender_type === 'system';
    const isAgent = msg.sender_type === 'agent';

    // System/notification messages
    if (isSystem || msg.msg_type === 'notification') {
      return (
        <div key={msg.id} style={{ display: 'flex', justifyContent: 'center', marginBottom: 12, padding: '0 16px' }}>
          <div
            style={{
              background: 'rgba(255,255,255,0.04)',
              border: '1px solid rgba(255,255,255,0.06)',
              borderRadius: 12,
              padding: '6px 14px',
              maxWidth: '80%',
            }}
          >
            {msg.msg_type === 'notification' && msg.metadata?.task && (
              <TaskMessageCard metadata={msg.metadata} />
            )}
            <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {msg.content}
            </Text>
          </div>
        </div>
      );
    }

    return (
      <div
        key={msg.id}
        style={{
          display: 'flex',
          justifyContent: own ? 'flex-end' : 'flex-start',
          marginBottom: 16,
          padding: '0 16px',
        }}
      >
        {!own && (
          <Avatar
            icon={isAgent ? <RobotOutlined /> : <UserOutlined />}
            style={{
              marginRight: 8,
              background: isAgent ? '#52c41a' : '#1677ff',
              flexShrink: 0,
              marginTop: 2,
            }}
          />
        )}
        <div style={{ maxWidth: 500 }}>
          <div style={{ marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>{msg.sender_name}</Text>
            {isAgent && (
              <Tag color="green" style={{ marginLeft: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                AI
              </Tag>
            )}
            {msg.mentions?.includes(user?.username || user?.display_name || '') && (
              <BellOutlined style={{ color: '#faad14', fontSize: 12 }} />
            )}
          </div>
          <div
            style={{
              padding: '8px 12px',
              borderRadius: own ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
              background: own ? '#1677ff' : 'rgba(255,255,255,0.08)',
              color: own ? '#fff' : 'inherit',
            }}
          >
            {msg.msg_type === 'file' && msg.metadata?.file ? (
              <FileMessageCard metadata={msg.metadata} />
            ) : msg.msg_type === 'task' && msg.metadata?.task ? (
              <TaskMessageCard metadata={msg.metadata} />
            ) : (
              <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {renderContentWithMentions(msg.content, user?.display_name || user?.username)}
              </div>
            )}
          </div>
          <Text type="secondary" style={{ fontSize: 10, marginTop: 2, display: 'block' }}>
            {msg.created_at ? new Date(msg.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''}
          </Text>
        </div>
      </div>
    );
  };

  return (
    <Layout style={{ height: 'calc(100vh - 112px)', background: 'transparent' }}>
      {/* ─── Left sidebar: Group list ──────────────────────────── */}
      <Sider
        width={260}
        style={{
          background: 'transparent',
          borderRight: '1px solid rgba(255,255,255,0.06)',
          marginRight: 0,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text strong>对话列表</Text>
          <Button type="text" icon={<PlusOutlined />} size="small" />
        </div>
        <div style={{ flex: 1, overflow: 'auto' }}>
          <List
            dataSource={groups}
            renderItem={(group) => {
              const unread = unreadCounts[group.id] || 0;
              return (
                <List.Item
                  onClick={() => handleGroupSelect(group.id)}
                  style={{
                    padding: '12px 16px',
                    cursor: 'pointer',
                    background: currentGroupId === group.id && !currentSessionId ? 'rgba(22,119,255,0.1)' : 'transparent',
                    borderRadius: 8,
                    marginBottom: 2,
                  }}
                >
                  <List.Item.Meta
                    avatar={
                      <Badge count={unread} size="small" offset={[-4, 4]}>
                        <Avatar style={{ background: '#1677ff' }}>{group.name[0]}</Avatar>
                      </Badge>
                    }
                    title={
                      <Text style={{ color: currentGroupId === group.id && !currentSessionId ? '#1677ff' : 'inherit' }}>
                        {group.name}
                      </Text>
                    }
                    description={<Text type="secondary" style={{ fontSize: 12 }}>{group.description || '暂无描述'}</Text>}
                  />
                </List.Item>
              );
            }}
            locale={{ emptyText: <Empty description="暂无群组" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          />
        </div>
      </Sider>

      {/* ─── Middle: Message area ──────────────────────────────── */}
      <Content style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
        {currentGroupId ? (
          <>
            {/* Header bar */}
            <div
              style={{
                padding: '10px 16px',
                borderBottom: '1px solid rgba(255,255,255,0.06)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexShrink: 0,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {currentSessionId && (
                  <Button type="text" icon={<RightOutlined />} size="small" onClick={handleBackToGroup} style={{ transform: 'rotate(180deg)' }} />
                )}
                <Text strong>
                  {currentSessionId
                    ? sessions.find(s => s.id === currentSessionId)?.title || 'Session'
                    : groups.find(g => g.id === currentGroupId)?.name || '群组聊天'}
                </Text>
                {currentSessionId && (
                  <Tag color={statusColorMap[sessions.find(s => s.id === currentSessionId)?.status || 'pending']} style={{ fontSize: 10 }}>
                    {statusLabelMap[sessions.find(s => s.id === currentSessionId)?.status || 'pending']}
                  </Tag>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <Button
                  type="text"
                  icon={<PlusOutlined />}
                  size="small"
                  onClick={() => setCreateSessionOpen(true)}
                  title="创建 Session"
                />
                <Button
                  type="text"
                  icon={<InfoCircleOutlined />}
                  size="small"
                  onClick={() => setRightPanelOpen(!rightPanelOpen)}
                  title="群组信息"
                />
              </div>
            </div>

            {/* Sub-tabs: Group messages / Sessions */}
            {!currentSessionId && (
              <div style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', flexShrink: 0 }}>
                <Tabs
                  activeKey={activeTab}
                  onChange={(key) => {
                    if (key === 'group') {
                      handleBackToGroup();
                    }
                    // 'session' tab just shows the session list below messages
                    setActiveTab(key);
                  }}
                  size="small"
                  style={{ marginBottom: 0, paddingLeft: 16 }}
                  items={[
                    { key: 'group', label: '群组消息' },
                    {
                      key: 'session',
                      label: (
                        <Space size={4}>
                          Sessions
                          {sessions.length > 0 && (
                            <Tag style={{ fontSize: 10, marginLeft: 0 }}>{sessions.length}</Tag>
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              </div>
            )}

            {/* Content area: Messages + optional session list */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
              {/* Messages column */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <div style={{ flex: 1, overflow: 'auto', padding: '16px 0' }}>
                  {messages.length === 0 ? (
                    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
                      <Empty description={currentSessionId ? '暂无 Session 消息' : '暂无消息，发送一条开始对话'} />
                    </div>
                  ) : (
                    messages.map(renderMessageBubble)
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* Input area */}
                <div style={{ padding: '12px 16px 0', borderTop: '1px solid rgba(255,255,255,0.06)', flexShrink: 0 }}>
                  <Space.Compact style={{ width: '100%' }}>
                    <Input
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      onPressEnter={handleSend}
                      placeholder={currentSessionId ? '发送 Session 消息...' : '输入消息...'}
                      size="large"
                    />
                    <Upload
                      beforeUpload={handleFileUpload}
                      showUploadList={false}
                    >
                      <Button icon={<PaperClipOutlined />} size="large" />
                    </Upload>
                    <Button type="primary" icon={<SendOutlined />} size="large" onClick={handleSend} />
                  </Space.Compact>
                </div>
              </div>

              {/* Session list panel (when session tab is active) */}
              {activeTab === 'session' && !currentSessionId && (
                <div
                  style={{
                    width: 280,
                    borderLeft: '1px solid rgba(255,255,255,0.06)',
                    overflow: 'auto',
                    padding: '8px',
                    flexShrink: 0,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <Text strong style={{ fontSize: 13 }}>Session 列表</Text>
                    <Button
                      type="text"
                      icon={<PlusOutlined />}
                      size="small"
                      onClick={() => setCreateSessionOpen(true)}
                    />
                  </div>
                  {sessions.length === 0 ? (
                    <Empty description="暂无 Session" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  ) : (
                    sessions.map((session) => (
                      <SessionListItem
                        key={session.id}
                        session={session}
                        isActive={false}
                        onClick={() => handleSessionSelect(session.id)}
                      />
                    ))
                  )}
                </div>
              )}
            </div>
          </>
        ) : (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
            <Empty description="选择一个群组开始对话" />
          </div>
        )}
      </Content>

      {/* ─── Right panel: Group info (collapsible) ─────────────── */}
      {rightPanelOpen && currentGroupDetail && (
        <Sider
          width={300}
          style={{
            background: 'rgba(255,255,255,0.02)',
            borderLeft: '1px solid rgba(255,255,255,0.06)',
            flexShrink: 0,
          }}
        >
          <GroupInfoPanel
            group={currentGroupDetail}
            onClose={() => setRightPanelOpen(false)}
            sessions={sessions}
            onSelectSession={(id) => {
              handleSessionSelect(id);
              setRightPanelOpen(false);
            }}
          />
        </Sider>
      )}

      {/* ─── Create session modal ─────────────────────────────── */}
      <CreateSessionModal
        open={createSessionOpen}
        onClose={() => setCreateSessionOpen(false)}
        groupId={currentGroupId || ''}
        agents={availableAgents}
        onSuccess={handleCreateSessionSuccess}
      />
    </Layout>
  );
};

export default Chat;
