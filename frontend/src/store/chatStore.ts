import { create } from 'zustand';

interface Message {
  id: string;
  sender_type: string;
  sender_id?: string;
  sender_name: string;
  msg_type: string;
  content: string;
  metadata: any;
  created_at: string;
  session_id?: string;
  mentions?: string[];
  is_read?: boolean;
}

interface Session {
  id: string;
  group_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  progress: number;
  progress_description: string;
  assigned_to: string;
  assigned_to_name?: string;
  created_at: string;
}

interface ChatState {
  currentGroupId: string | null;
  currentSessionId: string | null;
  sessions: Session[];
  messages: Message[];
  unreadCounts: Record<string, number>;
  setGroupId: (id: string | null) => void;
  setSessionId: (id: string | null) => void;
  setSessions: (sessions: Session[]) => void;
  updateSession: (session: Session) => void;
  addMessage: (msg: Message) => void;
  setMessages: (msgs: Message[]) => void;
  clearMessages: () => void;
  incrementUnread: (groupId: string) => void;
  clearUnread: (groupId: string) => void;
}

export type { Message, Session };

export const useChatStore = create<ChatState>((set) => ({
  currentGroupId: null,
  currentSessionId: null,
  sessions: [],
  messages: [],
  unreadCounts: {},
  setGroupId: (id) => set({ currentGroupId: id, currentSessionId: null, messages: [], sessions: [] }),
  setSessionId: (id) => set({ currentSessionId: id, messages: [] }),
  setSessions: (sessions) => set({ sessions }),
  updateSession: (session) =>
    set((state) => ({
      sessions: state.sessions.map((s) => (s.id === session.id ? session : s)),
    })),
  addMessage: (msg) =>
    set((state) => {
      // 去重：如果相同 id 的消息已存在则不重复添加
      if (msg.id && state.messages.some((m) => m.id === msg.id)) {
        return state;
      }
      return { messages: [...state.messages, msg] };
    }),
  setMessages: (msgs) => set({ messages: msgs }),
  clearMessages: () => set({ messages: [] }),
  incrementUnread: (groupId) =>
    set((state) => ({
      unreadCounts: {
        ...state.unreadCounts,
        [groupId]: (state.unreadCounts[groupId] || 0) + 1,
      },
    })),
  clearUnread: (groupId) =>
    set((state) => ({
      unreadCounts: {
        ...state.unreadCounts,
        [groupId]: 0,
      },
    })),
}));
