import { useEffect, useRef, useCallback, useState } from 'react';

interface WebSocketHookOptions {
  userId: string;
  enabled?: boolean;
  onMessage: (data: Record<string, unknown>) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export function useWebSocket({ userId, enabled = true, onMessage, onConnect, onDisconnect }: WebSocketHookOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);
  const isConnectingRef = useRef(false);
  const isMountedRef = useRef(true);

  const onMessageRef = useRef(onMessage);
  const onConnectRef = useRef(onConnect);
  const onDisconnectRef = useRef(onDisconnect);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onConnectRef.current = onConnect;
    onDisconnectRef.current = onDisconnect;
  }, [onMessage, onConnect, onDisconnect]);

  const connect = useCallback(() => {
    if (!enabled) return;
    
    if (isConnectingRef.current || wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    isConnectingRef.current = true;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/${userId}`;

    console.log('Connecting to WebSocket:', wsUrl);
    
    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        if (!isMountedRef.current) {
          ws.close();
          return;
        }
        console.log('WebSocket connected');
        isConnectingRef.current = false;
        setIsConnected(true);
        reconnectAttempts.current = 0;
        onConnectRef.current?.();
      };

      ws.onclose = (event) => {
        console.log('WebSocket disconnected, code:', event.code);
        isConnectingRef.current = false;
        wsRef.current = null;
        
        if (isMountedRef.current) {
          setIsConnected(false);
          onDisconnectRef.current?.();

          if (event.code !== 1000 && event.code !== 1001 && enabled) {
            const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
            reconnectAttempts.current++;

            if (reconnectTimeoutRef.current) {
              clearTimeout(reconnectTimeoutRef.current);
            }

            reconnectTimeoutRef.current = setTimeout(() => {
              if (isMountedRef.current && enabled) {
                connect();
              }
            }, delay);
          }
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        isConnectingRef.current = false;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onMessageRef.current(data);
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      wsRef.current = ws;
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      isConnectingRef.current = false;
    }
  }, [userId, enabled]);

  const disconnect = useCallback(() => {
    isMountedRef.current = false;
    isConnectingRef.current = false;
    
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    
    if (wsRef.current) {
      wsRef.current.close(1000, 'Component unmounting');
      wsRef.current = null;
    }
  }, []);

  const sendMessage = useCallback((type: string, data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, data }));
      return true;
    }
    console.error('WebSocket not connected');
    return false;
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    
    if (enabled) {
      const connectTimeout = setTimeout(() => {
        if (isMountedRef.current) {
          connect();
        }
      }, 100);
      
      return () => {
        clearTimeout(connectTimeout);
        disconnect();
      };
    }
    
    return () => {
      disconnect();
    };
  }, [connect, disconnect, enabled]);

  return {
    isConnected,
    sendMessage,
    userId,
  };
}

