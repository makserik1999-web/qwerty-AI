import { useState, useCallback } from 'react';
import { Chat, ChatDetail } from '../types';

const API_BASE = '/api';

export function useApi() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // GET: Fetch user chats (HTTP GET is kept for chat history per requirements)
  const fetchUserChats = useCallback(async (userId: string): Promise<Chat[]> => {
    setLoading(true);
    setError(null);
    try {
      console.log(`Fetching user chats from API: ${API_BASE}/users/${userId}/chats`);
      const response = await fetch(`${API_BASE}/users/${userId}/chats`, {
        headers: {
          'Accept': 'application/json',
          'x-user-id': userId,
        },
      });
      if (!response.ok) throw new Error('Failed to fetch chats');
      const data = await response.json();
      return data.items || [];
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  // GET: Fetch single chat with messages (HTTP GET is kept per requirements)
  const fetchChat = useCallback(async (chatId: string, userId: string = '1'): Promise<ChatDetail | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/users/${userId}/chats/${chatId}`, {
        headers: {
          'Accept': 'application/json',
          'x-user-id': userId,
        },
      });
      if (!response.ok) throw new Error('Failed to fetch chat');
      return await response.json();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    loading,
    error,
    fetchUserChats,
    fetchChat,
  };
}

