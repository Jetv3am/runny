"use client";

import { useCallback, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/api/client";

export type ChatTurn = ChatMessage & { id: number; pending?: boolean };

const CHAT_URL = "/api/v1/chat";
const MAX_HISTORY = 20;

/** Parse an SSE byte stream into JSON payloads from `data:` lines. */
async function* sseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<Record<string, unknown>> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      const line = event.split("\n").find((l) => l.startsWith("data: "));
      if (line) yield JSON.parse(line.slice(6));
    }
  }
}

export function useChatStream() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(async (content: string) => {
    const text = content.trim();
    if (!text || isStreaming) return;
    setError(null);

    const user: ChatTurn = { id: nextId.current++, role: "user", content: text };
    const assistantId = nextId.current++;
    const history = [...turns, user].slice(-MAX_HISTORY).map(({ role, content: c }) => ({ role, content: c }));
    setTurns((prev) => [...prev, user, { id: assistantId, role: "assistant", content: "", pending: true }]);
    setIsStreaming(true);

    const appendDelta = (delta: string) =>
      setTurns((prev) => prev.map((t) => (t.id === assistantId ? { ...t, content: t.content + delta } : t)));

    abortRef.current = new AbortController();
    try {
      const response = await fetch(CHAT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history }),
        signal: abortRef.current.signal,
      });
      if (!response.ok || !response.body) throw new Error(`Coach unavailable (${response.status})`);
      for await (const event of sseEvents(response.body)) {
        if (typeof event.delta === "string") appendDelta(event.delta);
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
        setTurns((prev) => prev.filter((t) => t.id !== assistantId || t.content));
      }
    } finally {
      setTurns((prev) => prev.map((t) => (t.id === assistantId ? { ...t, pending: false } : t)));
      setIsStreaming(false);
    }
  }, [turns, isStreaming]);

  const stop = useCallback(() => abortRef.current?.abort(), []);
  const reset = useCallback(() => {
    abortRef.current?.abort();
    setTurns([]);
    setError(null);
  }, []);

  return { turns, isStreaming, error, send, stop, reset };
}
