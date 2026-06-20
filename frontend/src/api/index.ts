const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

function getToken(): string | null {
  return localStorage.getItem('aibond_token');
}

async function request(url: string, options: RequestInit = {}) {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${url}`, { ...options, headers });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Request failed' }));
    // Handle rate limiting
    if (res.status === 429) {
      throw new Error(error.detail || '请求过于频繁，请稍后再试');
    }
    // Handle auth errors
    if (res.status === 401) {
      // Clear invalid token
      localStorage.removeItem('aibond_token');
      localStorage.removeItem('aibond_user');
      window.location.href = '/login';
      throw new Error('登录已过期，请重新登录');
    }
    throw new Error(error.detail || 'Request failed');
  }
  return res.json();
}

export const api = {
  // Auth
  register: (username: string, password: string, email?: string) =>
    request('/api/auth/register', { method: 'POST', body: JSON.stringify({ username, password, email }) }),
  login: (username: string, password: string) =>
    request('/api/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  getMe: (token: string) =>
    request('/api/auth/me', { method: 'POST', body: JSON.stringify({ token }) }),

  // Agents
  registerAgent: (name: string, skills?: string[], callbackUrl?: string) =>
    request('/api/agents/register', { method: 'POST', body: JSON.stringify({ name, skills, callback_url: callbackUrl }) }),
  listAgents: (status?: string) =>
    request(`/api/agents/${status ? `?status=${status}` : ''}`),
  getAgent: (id: string) =>
    request(`/api/agents/${id}`),
  // Agent 一键注册
  createAgentToken: (name: string) =>
    request('/api/agents/create-token', { method: 'POST', body: JSON.stringify({ name }) }),
  // 获取可用Agent列表（下拉选择用）
  listAvailableAgents: () =>
    request('/api/agents/available'),

  // Groups
  createGroup: (name: string, description: string, ownerId: string) =>
    request('/api/groups/', { method: 'POST', body: JSON.stringify({ name, description, owner_id: ownerId }) }),
  listGroups: () =>
    request('/api/groups/'),
  getGroup: (id: string) =>
    request(`/api/groups/${id}`),
  addMember: (groupId: string, memberType: string, memberId: string, role?: string) =>
    request(`/api/groups/${groupId}/members`, { method: 'POST', body: JSON.stringify({ member_type: memberType, member_id: memberId, role }) }),
  getMessages: (groupId: string, limit?: number, offset?: number) =>
    request(`/api/groups/${groupId}/messages?limit=${limit || 50}&offset=${offset || 0}`),

  // Messages
  sendMessage: (groupId: string, senderType: string, senderId: string, content: string, msgType?: string, metadata?: any) =>
    request('/api/messages/', { method: 'POST', body: JSON.stringify({ group_id: groupId, sender_type: senderType, sender_id: senderId, content, msg_type: msgType || 'text', metadata }) }),

  // Sessions
  createSession: (groupId: string, title: string, description: string, assignedTo: string, priority?: string) =>
    request('/api/sessions/', { method: 'POST', body: JSON.stringify({ group_id: groupId, title, description, assigned_to: assignedTo, priority: priority || 'medium' }) }),
  listSessions: (groupId: string) =>
    request(`/api/sessions/?group_id=${groupId}`),
  getSession: (id: string) =>
    request(`/api/sessions/${id}`),
  sendSessionMessage: (sessionId: string, senderType: string, senderId: string, content: string, msgType?: string) =>
    request(`/api/sessions/${sessionId}/messages`, { method: 'POST', body: JSON.stringify({ sender_type: senderType, sender_id: senderId, content, msg_type: msgType || 'text' }) }),
  updateSessionStatus: (sessionId: string, status: string, result?: any, summary?: string) =>
    request(`/api/sessions/${sessionId}/status`, { method: 'PUT', body: JSON.stringify({ status, result, summary }) }),

  // Files
  uploadFile: (formData: FormData) =>
    fetch(`${API_BASE}/api/files/upload`, { method: 'POST', body: formData, headers: { 'Authorization': `Bearer ${getToken()}` } }).then(r => r.json()),
  listFiles: (groupId?: string, sessionId?: string) =>
    request(`/api/files/?${groupId ? 'group_id=' + groupId : ''}${sessionId ? '&session_id=' + sessionId : ''}`),
  downloadFile: (fileId: string) =>
    `${API_BASE}/api/files/${fileId}/download`,

  // Agent tasks
  getAgentTasks: (agentId: string) =>
    request(`/api/agents/${agentId}/tasks`),

  // Workflows
  createWorkflow: (name: string, description: string, ownerId: string, definition?: any, triggerType?: string) =>
    request('/api/workflows/', { method: 'POST', body: JSON.stringify({ name, description, owner_id: ownerId, definition, trigger_type: triggerType }) }),
  listWorkflows: () =>
    request('/api/workflows/'),
  getWorkflow: (id: string) =>
    request(`/api/workflows/${id}`),
  updateWorkflowDefinition: (id: string, definition: any) =>
    request(`/api/workflows/${id}/definition`, { method: 'PUT', body: JSON.stringify({ definition }) }),
  runWorkflow: (id: string) =>
    request(`/api/workflows/${id}/run`, { method: 'POST' }),
};
