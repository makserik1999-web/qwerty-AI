export interface User {
  id: string;
  username: string;
  email?: string | null;
  created_at?: string | null;
}

export interface Screenshot {
  id: string;
  image_base64: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  screenshots: Screenshot[];
  video_url?: string;
  timestamp: string;
  /**
   * Client-side failure notice, not something the assistant said. These are
   * never persisted, so they disappear when the chat history is reloaded.
   */
  isError?: boolean;
  /** Served from the answer library instead of being generated just now. */
  fromCache?: boolean;
  /** Which storage tier it came from; "curated" means a reviewed video. */
  cacheTier?: string;
  /** "exact" or "semantic". A semantic hit answered a DIFFERENT wording. */
  cacheMatch?: string;
  /** The stored question a semantic hit was matched against. */
  matchedQuestion?: string;
  /** The question that produced it, so it can be asked again from scratch. */
  sourcePrompt?: string;
}

export interface Chat {
  id: string;
  title: string;
  current_video_url: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatDetail extends Chat {
  user_id: string;
  messages: ChatMessage[];
}

export interface PendingScreenshot {
  id: string;
  dataUrl: string;
}