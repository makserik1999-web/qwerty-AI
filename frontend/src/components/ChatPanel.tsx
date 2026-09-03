import { useRef, useEffect, useState } from 'react';
import { ChatMessage, PendingScreenshot } from '../types';
import { Quota, shouldShowQuota } from '../useQuota';
import { MarkdownMessage } from './MarkdownMessage';
import { NarrationToggle, type NarrationVoice } from './NarrationToggle';

interface ChatPanelProps {
  messages: ChatMessage[];
  pendingScreenshots: PendingScreenshot[];
  onRemoveScreenshot: (id: string) => void;
  onSendMessage: (prompt: string, screenshots: PendingScreenshot[]) => void;
  onRegenerate?: (prompt: string) => void;
  isLoading: boolean;
  isConnected: boolean;
  /** Remaining generation budget; shown only when it is running low. */
  quota?: Quota | null;
  /** Whether the next video speaks, and in whose voice. */
  narration: boolean;
  narrationVoice: NarrationVoice;
  onNarrationChange: (enabled: boolean) => void;
  onNarrationVoiceChange: (voice: NarrationVoice) => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({
  messages,
  pendingScreenshots,
  onRemoveScreenshot,
  onSendMessage,
  onRegenerate,
  isLoading,
  isConnected,
  quota = null,
  narration,
  narrationVoice,
  onNarrationChange,
  onNarrationVoiceChange,
}) => {
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = () => {
    if (inputValue.trim() || pendingScreenshots.length > 0) {
      onSendMessage(inputValue.trim(), pendingScreenshots);
      setInputValue('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = (inputValue.trim() || pendingScreenshots.length > 0) && !isLoading && isConnected;

  return (
    <div className="flex flex-col h-full bg-dark-800">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <svg className="w-16 h-16 mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} 
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p className="text-lg font-medium">Start a conversation</p>
            <p className="text-sm mt-1">Ask about any topic to generate a video</p>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              // Stable hook for the UI tests: styling classes are not a contract.
              data-role={message.isError ? 'error' : message.role}
              data-testid="chat-message"
              className={`animate-slide-up ${
                message.role === 'user' ? 'flex justify-end' : 'flex justify-start'
              }`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                  message.role === 'user'
                    ? 'bg-accent-primary text-white rounded-br-md'
                    : 'bg-dark-600 text-gray-200 rounded-bl-md border border-dark-500'
                }`}
              >
                {/* Screenshots in message */}
                {message.screenshots.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-2">
                    {message.screenshots.map((ss) => (
                      <img
                        key={ss.id}
                        src={ss.image_base64}
                        alt="Screenshot"
                        className="w-24 h-16 object-cover rounded-lg border border-dark-500"
                      />
                    ))}
                  </div>
                )}
                
                {/* Message content */}
                {message.content && (
                  message.role === 'user' ? (
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">
                      {message.content}
                    </p>
                  ) : (
                    <MarkdownMessage content={message.content} />
                  )
                )}

                {/* Served from the library rather than generated just now.
                    Shown because an answer that normally takes minutes
                    arriving instantly is otherwise unexplained. */}
                {message.fromCache && (
                  <div
                    data-testid="from-cache-badge"
                    className="mt-2 pt-2 border-t border-white/10 flex items-center
                               justify-between gap-3 text-xs"
                  >
                    <span className="flex items-center gap-1.5 text-gray-400">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                      </svg>
                      {message.cacheTier === 'curated'
                        ? 'From the library - reviewed'
                        : 'From the library'}
                    </span>

                    {/* A semantic hit answered a DIFFERENT wording. Saying
                        which one is what lets the reader notice it is not
                        what they meant - and the button beside it is how
                        they ask again. */}
                    {message.cacheMatch === 'semantic' && message.matchedQuestion && (
                      <span
                        data-testid="matched-question"
                        className="text-gray-500 italic truncate"
                        title={message.matchedQuestion}
                      >
                        answered: "{message.matchedQuestion}"
                      </span>
                    )}
                    {onRegenerate && message.sourcePrompt && (
                      <button
                        onClick={() => onRegenerate(message.sourcePrompt as string)}
                        disabled={isLoading || !isConnected}
                        data-testid="regenerate-button"
                        className="text-accent-primary hover:underline disabled:text-gray-600
                                   disabled:no-underline whitespace-nowrap"
                      >
                        Generate a new one
                      </button>
                    )}
                  </div>
                )}

                {/* Video indicator */}
                {message.video_url && (
                  <div className="mt-2 pt-2 border-t border-white/10 flex items-center gap-2 text-xs opacity-70">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                            d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    New video generated
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        
        {/* Loading indicator */}
        {isLoading && (
          <div className="flex justify-start animate-fade-in">
            <div className="bg-dark-600 rounded-2xl rounded-bl-md px-5 py-4 border border-dark-500 shadow-lg">
              <div className="flex items-center gap-3">
                {/* Animated spinner */}
                <div className="relative w-5 h-5">
                  <div className="absolute inset-0 border-2 border-accent-primary/30 rounded-full"></div>
                  <div className="absolute inset-0 border-2 border-transparent border-t-accent-primary rounded-full animate-spin"></div>
                </div>
                {/* Animated text */}
                <div className="flex items-center">
                  <span className="text-sm text-gray-300 font-medium">Generating</span>
                  <span className="inline-flex ml-0.5">
                    <span className="animate-pulse" style={{ animationDelay: '0ms' }}>.</span>
                    <span className="animate-pulse" style={{ animationDelay: '200ms' }}>.</span>
                    <span className="animate-pulse" style={{ animationDelay: '400ms' }}>.</span>
                  </span>
                </div>
              </div>
              {/* Progress bar animation */}
              <div className="mt-3 h-1 bg-dark-500 rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-accent-primary to-accent-secondary rounded-full animate-pulse"
                     style={{ width: '60%', animation: 'loading-bar 2s ease-in-out infinite' }}></div>
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* Pending Screenshots Preview */}
      {pendingScreenshots.length > 0 && (
        <div className="px-4 py-2 border-t border-dark-600 bg-dark-700">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-gray-400">
              {pendingScreenshots.length} screenshot{pendingScreenshots.length !== 1 ? 's' : ''} attached
            </span>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-2">
            {pendingScreenshots.map((ss) => (
              <div key={ss.id} className="relative group flex-shrink-0 animate-fade-in">
                <img
                  src={ss.dataUrl}
                  alt="Pending screenshot"
                  className="w-20 h-14 object-cover rounded-lg border border-dark-500"
                />
                <button
                  onClick={() => onRemoveScreenshot(ss.id)}
                  className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-red-500 hover:bg-red-600 
                             rounded-full flex items-center justify-center transition-colors
                             shadow-lg"
                >
                  <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Input Area */}
      <div className="p-4 border-t border-dark-600">
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about the video or a topic..."
              className="w-full bg-dark-700 border border-dark-500 rounded-xl px-4 py-3 
                         text-gray-200 placeholder-gray-500 resize-none
                         focus:border-accent-primary focus:ring-1 focus:ring-accent-primary
                         transition-all duration-200"
              rows={2}
              disabled={isLoading}
            />
            <div className="absolute bottom-2 right-2 text-xs text-gray-500">
              Ctrl+Enter to send
            </div>
          </div>
          <button
            onClick={handleSend}
            disabled={!canSend}
            className={`px-5 py-3 rounded-xl font-medium transition-all duration-200
                       flex items-center gap-2 ${
                         canSend
                           ? 'bg-accent-primary hover:bg-accent-secondary text-white shadow-lg shadow-accent-primary/20'
                           : 'bg-dark-600 text-gray-500 cursor-not-allowed'
                       }`}
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                    d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
            Send
          </button>
        </div>
        
        {/* Narration choice, next to the connection status: both describe what
            is about to happen rather than what already has. */}
        <div className="flex items-center justify-between mt-2 text-xs">
          <NarrationToggle
            enabled={narration}
            voice={narrationVoice}
            onEnabledChange={onNarrationChange}
            onVoiceChange={onNarrationVoiceChange}
            disabled={isLoading}
          />
        </div>

        {/* Connection status */}
        <div className="flex items-center gap-2 mt-2 text-xs">
          <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-gray-500">
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
          {!isConnected && (
            <span className="text-amber-400/90 ml-1">
              - sending is paused; queued messages will be sent when the connection returns
            </span>
          )}

          {/* Only when it is running out: a counter that is always on screen
              turns every question into a transaction. */}
          {shouldShowQuota(quota) && quota && (
            <span
              className={`ml-auto ${quota.remaining_hour <= 1 ? 'text-amber-400' : 'text-gray-500'}`}
              data-testid="quota-remaining"
              title={`${quota.remaining_day} of ${quota.limit_day} left today`}
            >
              {quota.remaining_hour} of {quota.limit_hour} videos left this hour
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
