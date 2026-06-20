import { create } from 'zustand';

interface AuthState {
  token: string | null;
  user: { id: string; username: string; display_name: string; role: string } | null;
  setAuth: (token: string, user: any) => void;
  logout: () => void;
}

function safeJsonParse(value: string | null): any {
  if (!value || value === 'null' || value === 'undefined') return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('aibond_token') || null,
  user: safeJsonParse(localStorage.getItem('aibond_user')),
  setAuth: (token, user) => {
    localStorage.setItem('aibond_token', token);
    localStorage.setItem('aibond_user', JSON.stringify(user));
    set({ token, user });
  },
  logout: () => {
    localStorage.removeItem('aibond_token');
    localStorage.removeItem('aibond_user');
    set({ token: null, user: null });
  },
}));
