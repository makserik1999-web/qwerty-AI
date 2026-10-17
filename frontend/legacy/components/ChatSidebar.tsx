import { Chat } from '../types';

interface ChatSidebarProps {
  chats: Chat[];
  selectedChatId: string | null;
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
  onDeleteChat: (chatId: string) => void;
  onLogout: () => void;
}

export const ChatSidebar: React.FC<ChatSidebarProps> = ({
  chats,
  selectedChatId,
  onSelectChat,
  onNewChat,
  onDeleteChat,
  onLogout,
}) => {
  return (
    <div className="w-64 bg-dark-800 border-r border-dark-600 flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-dark-600">
        <button
          onClick={onNewChat}
          className="w-full py-2.5 px-4 bg-accent-primary hover:bg-accent-secondary 
                     text-white rounded-lg font-medium transition-all duration-200
                     flex items-center justify-center gap-2 shadow-lg shadow-accent-primary/20"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>
      </div>

      {/* Chat List */}
      <div className="flex-1 overflow-y-auto py-2">
        {chats.length === 0 ? (
          <div className="text-center text-gray-500 py-8 px-4">
            <p className="text-sm">No chats yet</p>
            <p className="text-xs mt-1">Start a new conversation!</p>
          </div>
        ) : (
          chats.map((chat) => (
            <div
              key={chat.id}
              onClick={() => onSelectChat(chat.id)}
              className={`group mx-2 mb-1 p-3 rounded-lg cursor-pointer transition-all duration-200
                         ${selectedChatId === chat.id 
                           ? 'bg-dark-600 border border-accent-primary/30' 
                           : 'hover:bg-dark-700 border border-transparent'}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-medium text-gray-200 truncate">
                    {chat.title}
                  </h3>
                  <p className="text-xs text-gray-500 mt-1">
                    {chat.message_count} messages
                  </p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteChat(chat.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-500/20 
                             rounded transition-all duration-200"
                >
                  <svg className="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Footer with Logout */}
      <div className="p-4 border-t border-dark-600 space-y-3">
        <button
          onClick={onLogout}
          className="w-full py-2 px-3 bg-dark-700 hover:bg-dark-600 
                     text-gray-400 hover:text-white rounded-lg text-sm font-medium 
                     transition-all duration-200 flex items-center justify-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                  d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          Sign Out
        </button>
        <div className="text-xs text-gray-500 text-center">
          <span className="font-mono">Anyq</span> v1.0
        </div>
      </div>
    </div>
  );
};

