import { useState, useCallback } from 'react';
import { Chat, ChatDetail, User } from '../types';

const API_BASE = '/api';

export interface AuthResult {
  ok: boolean;
  error?: string;
  user?: User;
}

/**
 * All requests carry the HttpOnly session cookie (credentials: 'include').
 * Identity is derived server-side from the cookie; the client never sends
 * user ids or auth headers.
 */
export function useApi() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const request = useCallback(async (path: string, options?: RequestInit): Promise<Response> => {
    setLoading(true);
    setError(null);
    try {
      return await fetch(`${API_BASE}${path}`, {
        credentials: 'include',
        headers: {
          'Accept': 'application/json',
          ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
          ...options?.headers,
        },
        ...options,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error');
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const errorDetail = useCallback(async (response: Response): Promise<string> => {
    try {
      const data = await response.json();
      if (data && typeof data.detail === 'string') return data.detail;
    } catch {
      // fall through to status text
    }
    return `Request failed (${response.status})`;
  }, []);

  // GET /api/chats - the user id comes from the session cookie
  const fetchUserChats = useCallback(async (): Promise<Chat[]> => {
    try {
      const response = await request('/chats');
      if (!response.ok) throw new Error(await errorDetail(response));
      const data = await response.json();
      return data.items || [];
    } catch {
      return [];
    }
  }, [request, errorDetail]);

  // GET /api/chats/{chat_id}
  const fetchChat = useCallback(async (chatId: string): Promise<ChatDetail | null> => {
    try {
      const response = await request(`/chats/${chatId}`);
      if (!response.ok) throw new Error(await errorDetail(response));
      return await response.json();
    } catch {
      return null;
    }
  }, [request, errorDetail]);

  // GET /api/auth/me
  const fetchMe = useCallback(async (): Promise<User | null> => {
    try {
      const response = await request('/auth/me');
      if (response.status === 401) return null;
      if (!response.ok) throw new Error(await errorDetail(response));
      const data = await response.json();
      return data.user || null;
    } catch {
      return null;
    }
  }, [request, errorDetail]);

  const postAuth = useCallback(async (path: string, body: object): Promise<AuthResult> => {
    try {
      const response = await request(path, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        return { ok: false, error: await errorDetail(response) };
      }
      const data = await response.json();
      return { ok: true, user: data.user };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : 'Network error' };
    }
  }, [request, errorDetail]);

  const login = useCallback((username: string, password: string) =>
    postAuth('/auth/login', { username, password }), [postAuth]);

  const signup = useCallback((username: string, email: string, password: string) =>
    postAuth('/auth/signup', { username, email: email || null, password }), [postAuth]);

  const logout = useCallback(async (): Promise<void> => {
    try {
      await request('/auth/logout', { method: 'POST' });
    } catch {
      // best-effort: the local state is cleared regardless
    }
  }, [request]);

  return {
    loading,
    error,
    fetchUserChats,
    fetchChat,
    fetchMe,
    login,
    signup,
    logout,
  };
}