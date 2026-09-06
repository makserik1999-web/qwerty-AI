import { useEffect, useRef, useCallback, useState } from 'react';

interface OutgoingMessage {
  type: string;
  data: Record<string, unknown>;
}

interface WebSocketHookOptions {
  enabled?: boolean;
  onMessage: (data: Record<string, unknown>) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

const HEARTBEAT_INTERVAL_MS = 25000;
const HEARTBEAT_TIMEOUT_MS = 35000;
const MAX_QUEUE = 20;

/**
 * UI WebSocket with:
 * - session-cookie auth (same-origin /ws, no user id in the path)
 * - application-level heartbeat: frontend pings every 25s, backend answers
 *   "pong"; when no pong arrives for 35s the socket is closed with a
 *   non-1000 code so the existing exponential reconnect takes over
 * - an outbound queue flashed on reconnect (no silently lost messages)
 */
export function useWebSocket({ enabled = true, onMessage, onConnect, onDisconnect }: WebSocketHookOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);
  const isConnectingRef = useRef(false);
  const isMountedRef = useRef(true);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastPongRef = useRef(Date.now());
  const queueRef = useRef<OutgoingMessage[]>([]);

  const onMessageRef = useRef(onMessage);
  const onConnectRef = useRef(onConnect);
  const onDisconnectRef = useRef(onDisconnect);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onConnectRef.current = onConnect;
    onDisconnectRef.current = onDisconnect;
  }, [onMessage, onConnect, onDisconnect]);

  const stopHeartbeat = useCallback(() => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback(() => {
    stopHeartbeat();
    lastPongRef.current = Date.now();
    heartbeatRef.current = setInterval(() => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (Date.now() - lastPongRef.current > HEARTBEAT_TIMEOUT_MS) {
        console.warn('WebSocket heartbeat timeout - closing socket');
        stopHeartbeat();
        ws.close(4001, 'heartbeat timeout');
        return;
      }
      try {
        ws.send(JSON.stringify({ type: 'ping' }));
      } catch {
        // socket is dying; the close handler will reconnect
      }
    }, HEARTBEAT_INTERVAL_MS);
  }, [stopHeartbeat]);

  const flushQueue = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const queued = queueRef.current;
    queueRef.current = [];
    for (const item of queued) {
      try {
        ws.send(JSON.stringify(item));
      } catch {
        queueRef.current.push(item); // put it back; reconnect will retry
      }
    }
  }, []);

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
    const wsUrl = `${protocol}//${host}/ws`;

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
        lastPongRef.current = Date.now();
        startHeartbeat();
        flushQueue();
        onConnectRef.current?.();
      };

      ws.onclose = (event) => {
        console.log('WebSocket disconnected, code:', event.code);
        isConnectingRef.current = false;
        stopHeartbeat();
        if (wsRef.current === ws) {
          wsRef.current = null;
        }

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
          if (data && data.type === 'pong') {
            lastPongRef.current = Date.now();
            return;
          }
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
  }, [enabled, startHeartbeat, stopHeartbeat, flushQueue]);

  const disconnect = useCallback(() => {
    isMountedRef.current = false;
    isConnectingRef.current = false;
    stopHeartbeat();

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Component unmounting');
      wsRef.current = null;
    }
  }, [stopHeartbeat]);

  const sendMessage = useCallback((type: string, data: Record<string, unknown>): boolean => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, data }));
      return true;
    }
    // Queue for the next reconnect (bounded).
    if (queueRef.current.length < MAX_QUEUE) {
      queueRef.current.push({ type, data });
    } else {
      console.error('Outbound queue full; dropping message');
    }
    console.warn('WebSocket not connected - message queued for retry');
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
  };
}