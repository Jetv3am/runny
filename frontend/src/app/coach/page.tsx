import type { Metadata } from "next";
import { ChatWindow } from "@/components/coach/chat-window";
import { PageHeader, Pill } from "@/components/ui";

export const metadata: Metadata = { title: "AI coach" };

export default function CoachPage() {
  return (
    <>
      <PageHeader
        title="AI coach"
        description="Answers come from your real numbers."
        actions={<Pill tone="warning">Demo mode · LLM arrives in Phase 5</Pill>}
      />
      <ChatWindow />
    </>
  );
}
