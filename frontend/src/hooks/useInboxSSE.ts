/**
 * Inbox SSE 接続フック（Phase 2）。
 * useSSE の薄いラッパー — インターフェースは変更なし。
 * InboxPage.tsx 側のコードは変更不要。
 */
import { useSSE } from "./useSSE";

interface UseInboxSSEOptions {
  /** SSE で update 通知を受け取ったときのコールバック */
  onUpdate: () => void;
}

export function useInboxSSE({ onUpdate }: UseInboxSSEOptions): void {
  useSSE({ endpoint: "/api/v1/conversations/stream", onUpdate });
}
