/**
 * Inbox SSE 接続フック（Phase 2）。
 * fetch() + ReadableStream で SSE を実装（EventSource は Authorization ヘッダー不可のため）。
 * 接続失敗・切断時は自動再接続（指数バックオフ）。ポーリングへのフォールバックは呼び出し側で継続。
 */
import { useCallback, useEffect, useRef } from "react";

import { auth } from "../lib/firebase";

const SSE_ENDPOINT = "/api/v1/conversations/stream";
const SSE_INIT_RETRY_MS = 2_000;
const SSE_MAX_RETRY_MS = 300_000; // 5 分
const SSE_BACKOFF = 2;

interface UseInboxSSEOptions {
  /** SSE で update 通知を受け取ったときのコールバック */
  onUpdate: () => void;
}

export function useInboxSSE({ onUpdate }: UseInboxSSEOptions): void {
  const cancelledRef = useRef(false);
  const retryRef = useRef(SSE_INIT_RETRY_MS);
  const stableOnUpdate = useCallback(onUpdate, [onUpdate]);

  useEffect(() => {
    cancelledRef.current = false;
    retryRef.current = SSE_INIT_RETRY_MS;

    async function connect(): Promise<void> {
      const user = auth.currentUser;
      if (!user || cancelledRef.current) return;

      let token: string;
      try {
        token = await user.getIdToken();
      } catch {
        scheduleReconnect();
        return;
      }

      let response: Response;
      try {
        response = await fetch(SSE_ENDPOINT, {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: "text/event-stream",
            "Cache-Control": "no-cache",
          },
        });
      } catch {
        scheduleReconnect();
        return;
      }

      if (!response.ok || !response.body) {
        scheduleReconnect();
        return;
      }

      // 接続成功 → バックオフリセット
      retryRef.current = SSE_INIT_RETRY_MS;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      try {
        while (!cancelledRef.current) {
          const { done, value } = await reader.read();
          if (done) break;

          buf += decoder.decode(value, { stream: true });
          // SSE イベントは "\n\n" で区切られる
          const events = buf.split("\n\n");
          buf = events.pop() ?? "";

          for (const ev of events) {
            if (ev.includes("event: update")) {
              stableOnUpdate();
            }
            // ": ping" ハートビートは無視
          }
        }
      } finally {
        reader.cancel();
      }

      if (!cancelledRef.current) scheduleReconnect();
    }

    function scheduleReconnect(): void {
      if (cancelledRef.current) return;
      const delay = retryRef.current;
      retryRef.current = Math.min(delay * SSE_BACKOFF, SSE_MAX_RETRY_MS);
      setTimeout(() => {
        if (!cancelledRef.current) connect();
      }, delay);
    }

    connect();

    return () => {
      cancelledRef.current = true;
    };
  }, [stableOnUpdate]);
}
