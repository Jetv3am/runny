"use client";

import { ArrowUp, RotateCcw, Sparkles, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Markdown } from "./markdown";
import { useChatStream } from "./use-chat-stream";

const SUGGESTIONS = [
  "What are my training paces?",
  "What race times am I ready for?",
  "Am I too tired to train hard today?",
  "What's my next workout?",
];

export function ChatWindow() {
  const { turns, isStreaming, error, send, stop, reset } = useChatStream();
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  const submit = (text: string) => {
    void send(text);
    setDraft("");
    inputRef.current?.focus();
  };

  const lastReply = turns.findLast((t) => t.role === "assistant" && !t.pending);

  return (
    <div className="flex h-[calc(100vh-14rem)] min-h-[480px] flex-col overflow-hidden rounded-xl border border-line bg-surface">
      {/* Announce each finished reply once, instead of every streamed token. */}
      <div aria-live="polite" className="sr-only">{lastReply?.content}</div>

      <div className="flex-1 overflow-y-auto px-5 py-6" aria-busy={isStreaming}
           role="region" aria-label="Conversation" tabIndex={0}>
        <div className="mx-auto max-w-2xl space-y-6">
          {turns.length === 0 && (
            <div className="py-10 text-center">
              <span aria-hidden className="mx-auto grid size-10 place-items-center rounded-xl bg-accent">
                <Sparkles className="size-5 text-ink" />
              </span>
              <h2 className="mt-4 text-[18px] font-medium tracking-[-0.01em] text-ink">Ask your coach anything</h2>
              <p className="mt-1 text-ink-muted">Answers are grounded in your training data.</p>
              <ul className="mt-6 grid gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((s) => (
                  <li key={s}>
                    <button type="button" onClick={() => submit(s)}
                            className="w-full rounded-lg border border-line px-3 py-2.5 text-left text-[13px] text-ink transition-colors hover:bg-hover">
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {turns.map((turn) => (
            turn.role === "user" ? (
              <div key={turn.id} className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-white">
                  <span className="sr-only">You said:</span>
                  {turn.content}
                </div>
              </div>
            ) : (
              <div key={turn.id} className="flex gap-3">
                <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-lg bg-accent">
                  <Sparkles className="size-3.5 text-ink" />
                </span>
                <div className="min-w-0 flex-1 pt-0.5 leading-relaxed text-ink">
                  <span className="sr-only">Coach said:</span>
                  {turn.content ? <Markdown text={turn.content} /> : <span className="animate-pulse text-ink-muted">Thinking…</span>}
                </div>
              </div>
            )
          ))}
          <div ref={endRef} />
        </div>
      </div>

      {error && <p role="alert" className="mx-5 mb-2 rounded-lg bg-negative-soft p-2 text-[13px] text-negative">{error}</p>}

      <form className="border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); submit(draft); }}>
        <div className="mx-auto flex max-w-2xl items-end gap-2 rounded-xl border border-line-strong bg-surface p-1.5 focus-within:border-ink focus-within:ring-1 focus-within:ring-ink">
          <label htmlFor="chat-input" className="sr-only">Message your coach</label>
          <textarea
            id="chat-input"
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(draft); }
            }}
            rows={1}
            maxLength={4000}
            placeholder="Ask about paces, races, fatigue, or your plan…"
            className="max-h-32 flex-1 resize-none bg-transparent px-2 py-1.5 text-ink outline-none placeholder:text-ink-muted"
          />
          {turns.length > 0 && !isStreaming && (
            <button type="button" onClick={reset} className="grid size-8 place-items-center rounded-lg text-ink-muted hover:bg-hover hover:text-ink">
              <RotateCcw aria-hidden className="size-4" />
              <span className="sr-only">New conversation</span>
            </button>
          )}
          {isStreaming ? (
            <button type="button" onClick={stop} className="grid size-8 place-items-center rounded-lg bg-ink text-white">
              <Square aria-hidden className="size-3.5" fill="currentColor" />
              <span className="sr-only">Stop</span>
            </button>
          ) : (
            <button type="submit" disabled={!draft.trim()}
                    className="grid size-8 place-items-center rounded-lg bg-ink text-white disabled:bg-hover disabled:text-ink-muted">
              <ArrowUp aria-hidden className="size-4" />
              <span className="sr-only">Send</span>
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
