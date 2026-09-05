// lib/hooks/useWebSocket.ts
"use client";

import { useEffect, useRef, useState, useCallback } from "react";

const WS_URL = "wss://shuvopaycom-production.up.railway.app";

export function useWebSocket(onMessage: (data: any) => void) {
  const ws = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>();
  const merchantId = useRef<string | null>(null);

  const connect = useCallback(() => {
    const token = localStorage.getItem("access_token");
    const mid = localStorage.getItem("merchant_id");
    if (!token || !mid) return;

    merchantId.current = mid;
    const url = `${WS_URL}/api/v1/ws/merchant/${mid}?token=${token}`;

    ws.current = new WebSocket(url);

    ws.current.onopen = () => {
      setConnected(true);
      // Start ping interval
      const pingInterval = setInterval(() => {
        if (ws.current?.readyState === WebSocket.OPEN) {
          ws.current.send("ping");
        }
      }, 30_000);
      ws.current!.onclose = () => clearInterval(pingInterval);
    };

    ws.current.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data !== "pong") onMessage(data);
      } catch {}
    };

    ws.current.onclose = () => {
      setConnected(false);
      // Reconnect with exponential backoff
      reconnectTimeout.current = setTimeout(connect, 3000);
    };

    ws.current.onerror = () => {
      ws.current?.close();
    };
  }, [onMessage]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimeout.current);
      ws.current?.close();
    };
  }, [connect]);

  return { connected };
}
