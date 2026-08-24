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

export interface WebSocketMessage {
  type: string;
  data: Record<string, unknown>;
}

export interface PendingScreenshot {
  id: string;
  dataUrl: string;
}

