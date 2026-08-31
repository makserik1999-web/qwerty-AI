import { useState, useEffect, useCallback, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { LoginScreen } from './components/LoginScreen';
import { ChatSidebar } from './components/ChatSidebar';
import { ChatPanel } from './components/ChatPanel';
import { VideoPlayer } from './features/player/VideoPlayer';
import { useWebSocket } from './hooks/useWebSocket';
import { useApi, AuthResult } from './hooks/useApi';
import { Chat, ChatMessage, PendingScreenshot, User } from './types';

// Generous loading timeout - a full LLM + render pipeline can take minutes,
// but the spinner must never hang forever.
const LOADING_TIMEOUT_MS = 25 * 60 * 1000;

interface PendingMessage {
  prompt: string;
  screenshots: PendingScreenshot[];
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [chats, setChats] = useState<Chat[]>([]);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  // Messages and videos are kept per chat - never mixed across chats.
  const [messagesByChat, setMessagesByChat] = useState<Record<string, ChatMessage[]>>({});
  const [videoByChat, setVideoByChat] = useState<Record<string, string | null>>({});
  const [pendingScreenshots, setPendingScreenshots] = useState<PendingScreenshot[]>([]);
  // The chat that is currently awaiting an AI response (drives the spinner).
  const [pendingRequestChatId, setPendingRequestChatId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // Queue of messages waiting for a chat to be created (one or more).
  const pendingChatMessagesRef = useRef<PendingMessage[]>([]);
  const loadingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectedChatIdRef = useRef<string | null>(null);
  // The question each chat is waiting on, so "generate a fresh one"
  // can re-send it with the cache bypassed.
  const lastPromptByChatRef = useRef<Record<string, string>>({});

  const { fetchUserChats, fetchChat, fetchMe, login, signup, logout } = useApi();

  // Restore the session from the HttpOnly cookie on mount.
  useEffect(() => {
    let cancelled = false;
    fetchMe().then((u) => {
      if (!cancelled) {
        setUser(u);
        setAuthChecking(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [fetchMe]);

  useEffect(() => {
    selectedChatIdRef.current = selectedChatId;
  }, [selectedChatId]);

  // ============== auth ==============
  const handleLogin = useCallback(async (username: string, password: string): Promise<AuthResult> => {
    const result = await login(username, password);
    if (result.ok && result.user) {
      setUser(result.user);
    }
    return result;
  }, [login]);

  const handleSignup = useCallback(async (username: string, email: string, password: string): Promise<AuthResult> => {
    const result = await signup(username, email, password);
    if (result.ok && result.user) {
      setUser(result.user);
    }
    return result;
  }, [signup]);

  const handleLogout = useCallback(() => {
    logout();
    // Clear everything: chats, messages, videos, selection.
    setUser(null);
    setChats([]);
    setSelectedChatId(null);
    setMessagesByChat({});
    setVideoByChat({});
    setPendingScreenshots([]);
    setPendingRequestChatId(null);
    pendingChatMessagesRef.current = [];
    if (loadingTimeoutRef.current) {
      clearTimeout(loadingTimeoutRef.current);
      loadingTimeoutRef.current = null;
    }
  }, [logout]);

  // ============== per-chat helpers ==============
  const appendMessage = useCallback((chatId: string, message: ChatMessage) => {
    setMessagesByChat((prev) => ({
      ...prev,
      [chatId]: [...(prev[chatId] || []), message],
    }));
  }, []);

  const addErrorBubble = useCallback((chatId: string | null, text: string) => {
    const target = chatId || selectedChatIdRef.current;
    if (!target) return;
    appendMessage(target, {
      id: uuidv4(),
      role: 'assistant',
      content: `⚠️ ${text}`,
      isError: true,
      screenshots: [],
      timestamp: new Date().toISOString(),
    });
  }, [appendMessage]);

  const clearPendingRequest = useCallback((chatId: string | null) => {
    setPendingRequestChatId((prev) => (prev === chatId ? null : prev));
    if (loadingTimeoutRef.current) {
      clearTimeout(loadingTimeoutRef.current);
      loadingTimeoutRef.current = null;
    }
  }, []);

  const armLoadingTimeout = useCallback((chatId: string) => {
    if (loadingTimeoutRef.current) {
      clearTimeout(loadingTimeoutRef.current);
    }
    loadingTimeoutRef.current = setTimeout(() => {
      loadingTimeoutRef.current = null;
      setPendingRequestChatId((prev) => (prev === chatId ? null : prev));
      addErrorBubble(chatId, 'Processing timed out. Please try again.');
    }, LOADING_TIMEOUT_MS);
  }, [addErrorBubble]);

  const incrementChatCount = useCallback((chatId: string, delta: number = 1) => {
    setChats((prev) =>
      prev.map((c) => (c.id === chatId ? { ...c, message_count: c.message_count + delta } : c)),
    );
  }, []);

  // ============== sending ==============
  const sendMessageToChat = useCallback((
    chatId: string,
    prompt: string,
    screenshots: PendingScreenshot[],
    sendMessageFn: (type: string, data: Record<string, unknown>) => boolean,
    forceRegenerate = false,
  ) => {
    const userMessage: ChatMessage = {
      id: uuidv4(),
      role: 'user',
      content: prompt,
      screenshots: screenshots.map((ss) => ({
        id: ss.id,
        image_base64: ss.dataUrl,
      })),
      timestamp: new Date().toISOString(),
    };

    appendMessage(chatId, userMessage);
    lastPromptByChatRef.current[chatId] = prompt;
    setPendingScreenshots([]);
    setPendingRequestChatId(chatId);
    armLoadingTimeout(chatId);

    const ok = sendMessageFn('user_message', {
      chat_id: chatId,
      prompt,
      screenshots: screenshots.map((ss) => ({
        id: ss.id,
        image_base64: ss.dataUrl,
      })),
      force_regenerate: forceRegenerate,
    });
    if (!ok) {
      // Message is queued by the hook and will be flushed on reconnect.
      addErrorBubble(chatId, 'No connection right now - the message will be sent when the connection returns.');
    }
  }, [appendMessage, armLoadingTimeout, addErrorBubble]);

  // ============== WebSocket message handler ==============
  const handleWebSocketMessage = useCallback((data: Record<string, unknown>, sendMessageFn: (type: string, data: Record<string, unknown>) => boolean) => {
    const messageType = data.type as string;

    switch (messageType) {
      case 'message_received':
        console.log('Message received by server');
        break;

      case 'chat_created': {
        const chatData = data.data as Chat;
        setChats((prev) => [chatData, ...prev]);
        setSelectedChatId(chatData.id);
        setMessagesByChat((prev) => ({ ...prev, [chatData.id]: prev[chatData.id] || [] }));

        // Flush any messages that were waiting for a chat to exist.
        const queued = pendingChatMessagesRef.current;
        pendingChatMessagesRef.current = [];
        for (const item of queued) {
          sendMessageToChat(chatData.id, item.prompt, item.screenshots, sendMessageFn);
        }
        if (queued.length === 0) {
          setPendingScreenshots([]);
        }
        break;
      }

      case 'chat_deleted': {
        const deleteData = data.data as { chat_id: string; success: boolean };
        if (deleteData.success) {
          setChats((prev) => prev.filter((c) => c.id !== deleteData.chat_id));
          setMessagesByChat((prev) => {
            const next = { ...prev };
            delete next[deleteData.chat_id];
            return next;
          });
          setVideoByChat((prev) => {
            const next = { ...prev };
            delete next[deleteData.chat_id];
            return next;
          });
        }
        break;
      }

      case 'ai_response': {
        const responseData = data.data as {
          message_id: string;
          chat_id: string;
          content: string;
          video_url?: string;
          timestamp: string;
          from_cache?: boolean;
          cache_tier?: string;
        };

        const assistantMessage: ChatMessage = {
          id: responseData.message_id,
          role: 'assistant',
          content: responseData.content,
          screenshots: [],
          video_url: responseData.video_url,
          timestamp: responseData.timestamp,
          fromCache: Boolean(responseData.from_cache),
          cacheTier: responseData.cache_tier,
          // Remembered so "generate a fresh one" can re-ask the same thing.
          sourcePrompt: lastPromptByChatRef.current[responseData.chat_id],
        };

        // Only ever append to the chat the response belongs to.
        appendMessage(responseData.chat_id, assistantMessage);

        if (responseData.video_url) {
          setVideoByChat((prev) => ({ ...prev, [responseData.chat_id]: responseData.video_url || null }));
        }

        if (pendingRequestChatId === responseData.chat_id) {
          clearPendingRequest(responseData.chat_id);
        }
        // The server stores both the user message and this assistant reply.
        incrementChatCount(responseData.chat_id, 2);
        break;
      }

      case 'error': {
        const errorData = data.data as { message: string; chat_id?: string };
        console.error('WebSocket error:', errorData.message);
        const chatId = errorData.chat_id || selectedChatIdRef.current;
        if (chatId) {
          addErrorBubble(chatId, errorData.message);
          clearPendingRequest(chatId);
        }
        break;
      }

      default:
        break;
    }
  }, [appendMessage, addErrorBubble, clearPendingRequest, incrementChatCount, pendingRequestChatId, sendMessageToChat]);

  const handleWsConnect = useCallback(() => {
    console.log('WebSocket connected');
  }, []);

  const handleWsDisconnect = useCallback(() => {
    console.log('WebSocket disconnected');
  }, []);

  const wsMessageHandler = useCallback((data: Record<string, unknown>) => {
    handleWebSocketMessage(data, sendMessage);
  }, [handleWebSocketMessage]);

  const { isConnected, sendMessage } = useWebSocket({
    enabled: !!user,
    onMessage: wsMessageHandler,
    onConnect: handleWsConnect,
    onDisconnect: handleWsDisconnect,
  });

  // ============== chat list / selection ==============
  // Load chats after auth.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    fetchUserChats().then((userChats) => {
      if (cancelled) return;
      setChats(userChats);
    });
    return () => {
      cancelled = true;
    };
  }, [user, fetchUserChats]);

  const handleSelectChat = useCallback(async (chatId: string) => {
    setSelectedChatId(chatId);
    setPendingScreenshots([]);

    const chatDetail = await fetchChat(chatId);
    // Stale guard: an old response must not overwrite a newer selection.
    if (selectedChatIdRef.current !== chatId) return;
    if (chatDetail) {
      setMessagesByChat((prev) => ({ ...prev, [chatId]: chatDetail.messages }));
      setVideoByChat((prev) => ({ ...prev, [chatId]: chatDetail.current_video_url }));
    } else {
      addErrorBubble(chatId, 'Failed to load this chat. Please try again.');
    }
  }, [fetchChat, addErrorBubble]);

  // Auto-select the first chat after load; when the selected chat disappears
  // (deleted), move to another one; when no chats remain, clear everything.
  useEffect(() => {
    if (!chats.length) {
      if (selectedChatId) {
        setSelectedChatId(null);
        setMessagesByChat({});
        setVideoByChat({});
      }
      return;
    }
    const valid = selectedChatId && chats.some((c) => c.id === selectedChatId);
    if (!valid) {
      handleSelectChat(chats[0].id);
    }
  }, [chats, selectedChatId, handleSelectChat]);

  // ============== UI actions ==============
  const handleNewChat = useCallback(() => {
    sendMessage('create_chat', { title: 'New Chat' });
  }, [sendMessage]);

  const handleDeleteChat = useCallback((chatId: string) => {
    sendMessage('delete_chat', { chat_id: chatId });
  }, [sendMessage]);

  const handleScreenshotCapture = useCallback((screenshot: PendingScreenshot) => {
    setPendingScreenshots((prev) => [...prev, screenshot]);
  }, []);

  const handleRemoveScreenshot = useCallback((id: string) => {
    setPendingScreenshots((prev) => prev.filter((ss) => ss.id !== id));
  }, []);

  const handleSendMessage = useCallback((prompt: string, screenshots: PendingScreenshot[]) => {
    if (!selectedChatId) {
      // No chat selected - create a chat and queue the message(s).
      pendingChatMessagesRef.current.push({ prompt, screenshots });
      const ok = sendMessage('create_chat', { title: prompt.slice(0, 50) || 'New Chat' });
      if (!ok) {
        // The create_chat itself is queued by the hook; warn the user.
        addErrorBubble(null, 'No connection right now - the message will be sent when the connection returns.');
      }
      return;
    }
    sendMessageToChat(selectedChatId, prompt, screenshots, sendMessage);
  }, [selectedChatId, sendMessage, sendMessageToChat, addErrorBubble]);

  // "Not what I wanted": ask again, skipping the library.
  const handleRegenerate = useCallback((prompt: string) => {
    if (!selectedChatId || !prompt) return;
    sendMessageToChat(selectedChatId, prompt, [], sendMessage, true);
  }, [selectedChatId, sendMessage, sendMessageToChat]);

  // ============== render ==============
  if (authChecking) {
    return (
      <div className="h-screen flex items-center justify-center bg-dark-900">
        <div className="w-8 h-8 border-2 border-accent-primary/30 border-t-accent-primary rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) {
    return <LoginScreen onLogin={handleLogin} onSignup={handleSignup} />;
  }

  const selectedMessages = selectedChatId ? messagesByChat[selectedChatId] || [] : [];
  const currentVideoUrl = selectedChatId ? videoByChat[selectedChatId] || null : null;
  const isLoading = pendingRequestChatId !== null && pendingRequestChatId === selectedChatId;

  return (
    <div className="h-screen flex overflow-hidden bg-dark-900">
      {/* Sidebar */}
      <div className={`${sidebarOpen ? 'block' : 'hidden'} md:block`}>
        <ChatSidebar
          chats={chats}
          selectedChatId={selectedChatId}
          onSelectChat={handleSelectChat}
          onNewChat={handleNewChat}
          onDeleteChat={handleDeleteChat}
          onLogout={handleLogout}
        />
      </div>

      {/* Toggle Sidebar Button (Mobile) */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="md:hidden fixed top-4 left-4 z-50 p-2 bg-dark-700 rounded-lg"
      >
        <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      {/* Main Content */}
      <div className="flex-1 flex min-w-0">
        {/* Chat Panel */}
        <div className="w-2/5 min-w-[320px] max-w-[500px] border-r border-dark-600">
          <ChatPanel
            messages={selectedMessages}
            pendingScreenshots={pendingScreenshots}
            onRemoveScreenshot={handleRemoveScreenshot}
            onSendMessage={handleSendMessage}
            onRegenerate={handleRegenerate}
            isLoading={isLoading}
            isConnected={isConnected}
          />
        </div>

        {/* Video Panel */}
        <div className="flex-1 min-w-0">
          <VideoPlayer
            videoUrl={currentVideoUrl}
            onScreenshotCapture={handleScreenshotCapture}
          />
        </div>
      </div>
    </div>
  );
}

export default App;