import { useEffect, useRef, useState } from "react";
import { useUi } from "../store/ui";

/** Subscribe to a backend WebSocket channel with automatic reconnection. */
export function useChannel<T>(channel: string): T | null {
  const [data, setData] = useState<T | null>(null);
  const setWsStatus = useUi((s) => s.setWsStatus);
  const retryRef = useRef(1000);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closed = false;
    let timer: number | undefined;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${window.location.host}/ws/${channel}`);
      socket.onopen = () => {
        setWsStatus("connected");
        retryRef.current = 1000;
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.channel === channel) setData(message.data as T);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        if (closed) return;
        setWsStatus("reconnecting");
        timer = window.setTimeout(connect, retryRef.current);
        retryRef.current = Math.min(retryRef.current * 2, 15000);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      socket?.close();
      setWsStatus("disconnected");
    };
  }, [channel, setWsStatus]);

  return data;
}
