import { useState, useEffect, useCallback, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { LoginScreen } from './components/LoginScreen';
import { ChatSidebar } from './components/ChatSidebar';
import { ChatPanel } from './components/ChatPanel';
import { VideoPanel } from './components/VideoPanel';
import { useWebSocket } from './hooks/useWebSocket';
import { useApi } from './hooks/useApi';
import { Chat, ChatMessage, PendingScreenshot } from './types';

// Hardcoded user ID
const USER_ID = '1';

interface PendingMessage {
  prompt: string;
  screenshots: PendingScreenshot[];
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [chats, setChats] = useState<Chat[]>([]);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentVideoUrl, setCurrentVideoUrl] = useState<string | null>(null);
  const [pendingScreenshots, setPendingScreenshots] = useState<PendingScreenshot[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  
  // Queue for messages that are waiting for chat creation
  const pendingMessageRef = useRef<PendingMessage | null>(null);

  const { fetchUserChats, fetchChat } = useApi();

  // Check for existing auth on mount
  useEffect(() => {
    const authStatus = sessionStorage.getItem('anyq_auth');
    if (authStatus === 'authenticated') {
      setIsAuthenticated(true);
    }
  }, []);

  // Handle login
  const handleLogin = (username: string, password: string): boolean => {
    // Hardcoded gatekeeper credentials
    if (username === 'admin' && password === 'yesko') {
      sessionStorage.setItem('anyq_auth', 'authenticated');
      setIsAuthenticated(true);
      return true;
    }
    return false;
  };

  // Handle logout
  const handleLogout = () => {
    sessionStorage.removeItem('anyq_auth');
    setIsAuthenticated(false);
  };

  // Send message to a specific chat
  const sendMessageToChat = useCallback((chatId: string, prompt: string, screenshots: PendingScreenshot[], sendMessageFn: (type: string, data: Record<string, unknown>) => boolean) => {
    // Create user message for immediate display
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

    setMessages((prev) => [...prev, userMessage]);
    setPendingScreenshots([]);
    setIsLoading(true);

    // Send via WebSocket
    sendMessageFn('user_message', {
      chat_id: chatId,
      prompt,
      screenshots: screenshots.map((ss) => ({
        id: ss.id,
        image_base64: ss.dataUrl,
      })),
    });
  }, []);

  // WebSocket message handler
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
        setMessages([]);
        setCurrentVideoUrl(null);
        
        // Check if there's a pending message to send
        if (pendingMessageRef.current) {
          const { prompt, screenshots } = pendingMessageRef.current;
          pendingMessageRef.current = null; // Clear the pending message
          
          // Send the message to the newly created chat
          setTimeout(() => {
            sendMessageToChat(chatData.id, prompt, screenshots, sendMessageFn);
          }, 100);
        } else {
          setPendingScreenshots([]);
        }
        break;
      }

      case 'chat_deleted': {
        const deleteData = data.data as { chat_id: string; success: boolean };
        if (deleteData.success) {
          setChats((prev) => prev.filter((c) => c.id !== deleteData.chat_id));
          // Note: We'll handle selection in useEffect to avoid stale closure
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
        };

        const assistantMessage: ChatMessage = {
          id: responseData.message_id,
          role: 'assistant',
          content: responseData.content,
          screenshots: [],
          video_url: responseData.video_url,
          timestamp: responseData.timestamp,
        };

        setMessages((prev) => [...prev, assistantMessage]);

        if (responseData.video_url) {
          setCurrentVideoUrl(responseData.video_url);
        }

        setIsLoading(false);
        
        // Refresh chat list to update message counts
        fetchUserChats(USER_ID).then(setChats);
        break;
      }

      case 'error': {
        const errorData = data.data as { message: string };
        console.error('WebSocket error:', errorData.message);
        setIsLoading(false);
        // Show error to user
        const errorMessage: ChatMessage = {
          id: uuidv4(),
          role: 'assistant',
          content: `⚠️ Error: ${errorData.message}`,
          screenshots: [],
          timestamp: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, errorMessage]);
        break;
      }

      case 'pong':
        console.log('Pong received');
        break;
    }
  }, [fetchUserChats, sendMessageToChat]);

  const handleWsConnect = useCallback(() => {
    console.log('WebSocket connected');
  }, []);

  const handleWsDisconnect = useCallback(() => {
    console.log('WebSocket disconnected');
  }, []);

  // Create a wrapper that includes sendMessage in the callback
  const wsMessageHandler = useCallback((data: Record<string, unknown>) => {
    handleWebSocketMessage(data, sendMessage);
  }, [handleWebSocketMessage]);

  const { isConnected, sendMessage } = useWebSocket({
    userId: USER_ID,
    enabled: isAuthenticated,
    onMessage: wsMessageHandler,
    onConnect: handleWsConnect,
    onDisconnect: handleWsDisconnect,
  });

  // Handle chat deletion selection
  useEffect(() => {
    if (selectedChatId && !chats.find(c => c.id === selectedChatId)) {
      // Selected chat was deleted
      if (chats.length > 0) {
        handleSelectChat(chats[0].id);
      } else {
        setSelectedChatId(null);
        setMessages([]);
        setCurrentVideoUrl(null);
      }
    }
  }, [chats, selectedChatId]);

  // Load chats on mount (only when authenticated)
  useEffect(() => {
    if (!isAuthenticated) return;
    
    const loadChats = async () => {
      console.log('Loading user chats');
      const userChats = await fetchUserChats(USER_ID);
      setChats(userChats);

      // Auto-select first chat if exists
      if (userChats.length > 0 && !selectedChatId) {
        handleSelectChat(userChats[0].id);
      }
    };

    loadChats();
  }, [isAuthenticated, fetchUserChats]);

  // Load chat details when selected (using HTTP GET - kept as per requirements)
  const handleSelectChat = async (chatId: string) => {
    setSelectedChatId(chatId);
    setPendingScreenshots([]);

    const chatDetail = await fetchChat(chatId, USER_ID);
    if (chatDetail) {
      setMessages(chatDetail.messages);
      setCurrentVideoUrl(chatDetail.current_video_url);
    }
  };

  // Create new chat via WebSocket
  const handleNewChat = () => {
    sendMessage('create_chat', { title: 'New Chat' });
  };

  // Delete chat via WebSocket
  const handleDeleteChat = (chatId: string) => {
    sendMessage('delete_chat', { chat_id: chatId });
  };

  // Add screenshot from video panel
  const handleScreenshotCapture = (screenshot: PendingScreenshot) => {
    setPendingScreenshots((prev) => [...prev, screenshot]);
  };

  // Remove pending screenshot
  const handleRemoveScreenshot = (id: string) => {
    setPendingScreenshots((prev) => prev.filter((ss) => ss.id !== id));
  };

  // Send message via WebSocket
  const handleSendMessage = (prompt: string, screenshots: PendingScreenshot[]) => {
    if (!selectedChatId) {
      // No chat selected - create a new chat and queue the message
      pendingMessageRef.current = { prompt, screenshots };
      sendMessage('create_chat', { title: prompt.slice(0, 50) || 'New Chat' });
      return;
    }

    // Send directly to the selected chat
    sendMessageToChat(selectedChatId, prompt, screenshots, sendMessage);
  };

  // Show login screen if not authenticated
  if (!isAuthenticated) {
    return <LoginScreen onLogin={handleLogin} />;
  }

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
            messages={messages}
            pendingScreenshots={pendingScreenshots}
            onRemoveScreenshot={handleRemoveScreenshot}
            onSendMessage={handleSendMessage}
            isLoading={isLoading}
            isConnected={isConnected}
          />
        </div>

        {/* Video Panel */}
        <div className="flex-1 min-w-0">
          <VideoPanel
            videoUrl={currentVideoUrl}
            onScreenshotCapture={handleScreenshotCapture}
          />
        </div>
      </div>
    </div>
  );
}

export default App;
