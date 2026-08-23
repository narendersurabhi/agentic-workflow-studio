import type { RefObject } from "react";

import Badge from "../../components/ui/Badge";
import ChatMessageFeedback from "../../components/feedback/ChatMessageFeedback";
import { CHAT_FEEDBACK_REASONS, feedbackTargetKey, type FeedbackEntry, type FeedbackSentiment } from "../../lib/feedback";
import { MarkdownContent } from "./MarkdownContent";
import { ThinkingState } from "./ThinkingState";
import { ToolProgressCard } from "./ToolProgressCard";
import type { ChatMessage, ToolStepItem } from "./types";

export type ChatMessageListProps = {
  messages: ChatMessage[];
  loading: boolean;
  feedbackByTarget: Record<string, FeedbackEntry>;
  feedbackSubmitting: Record<string, boolean>;
  onSubmitFeedback: (
    messageId: string,
    payload: { sentiment: FeedbackSentiment; reason_codes: string[]; comment?: string },
  ) => Promise<void> | void;
  formatTimestamp: (value?: string) => string;
  transcriptRef: RefObject<HTMLDivElement | null>;
};

export function ChatMessageList({
  messages,
  loading,
  feedbackByTarget,
  feedbackSubmitting,
  onSubmitFeedback,
  formatTimestamp,
  transcriptRef,
}: ChatMessageListProps) {
  return (
    <div ref={transcriptRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
      {messages.length === 0 ? (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
          <div className="text-3xl">💬</div>
          <p className="text-sm text-text-md">
            Describe what you need in plain language. Type{" "}
            <kbd className="rounded border border-subtle bg-surface-1 px-1.5 py-0.5 text-[11px]">/</kbd>{" "}
            for Skills.
          </p>
        </div>
      ) : (
        messages.map((message) => {
          const isPending = Boolean(message.metadata?.pending);
          const toolSteps = (message.metadata?.toolSteps as ToolStepItem[] | undefined) ?? [];
          const isToolBacked = message.role === "assistant" && toolSteps.length > 0;
          return (
            <div
              key={message.id}
              className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm shadow-sm ${
                message.role === "user"
                  ? "ml-auto bg-white text-slate-900"
                  : "border border-subtle bg-surface-1 text-text-hi"
              } ${isPending ? "opacity-70" : ""}`}
            >
              <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em]">
                <div className="flex items-center gap-2">
                  <span className={message.role === "user" ? "text-slate-400" : "text-text-md"}>
                    {message.role}
                  </span>
                  {isToolBacked ? <Badge variant="sky">Tool-backed</Badge> : null}
                  {isPending ? (
                    <span className="rounded-full border border-amber-400/30 bg-accent-amber px-2 py-0.5 text-[9px] font-semibold tracking-[0.12em] text-amber-200">
                      Pending
                    </span>
                  ) : null}
                </div>
                <span className="text-text-lo">{formatTimestamp(message.created_at)}</span>
              </div>
              <div className="mt-2">
                <ToolProgressCard
                  intent={message.metadata?.toolIntent as string | undefined}
                  steps={toolSteps}
                />
                <MarkdownContent
                  content={message.content}
                  streaming={Boolean(message.metadata?.streaming)}
                />
              </div>
              {message.action?.clarification_questions &&
              message.action.clarification_questions.length > 0 ? (
                <div className="mt-3 space-y-1 rounded-xl border border-amber-300/20 bg-accent-amber px-3 py-2 text-[12px] text-text-amber-token">
                  {message.action.clarification_questions.map((q, i) => (
                    <div key={`${message.id}-q-${i}`}>{q}</div>
                  ))}
                </div>
              ) : null}
              {message.job_id ? (
                <div className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-emerald-300/20 bg-accent-emerald px-3 py-2 text-[12px] text-text-emerald-token">
                  <span>Job {message.job_id}</span>
                  <a
                    href={`/observability?job=${encodeURIComponent(message.job_id)}`}
                    className="rounded-full border border-emerald-200/30 px-2 py-1 text-[11px] font-semibold text-emerald-50 transition hover:border-emerald-100/60"
                  >
                    View in Observability
                  </a>
                </div>
              ) : null}
              {message.role === "assistant" && !isPending ? (
                <ChatMessageFeedback
                  reasonOptions={CHAT_FEEDBACK_REASONS}
                  existing={feedbackByTarget[feedbackTargetKey("chat_message", message.id)] || null}
                  submitting={Boolean(feedbackSubmitting[feedbackTargetKey("chat_message", message.id)])}
                  onSubmit={(payload) => onSubmitFeedback(message.id, payload)}
                />
              ) : null}
            </div>
          );
        })
      )}
      {loading ? <ThinkingState /> : null}
    </div>
  );
}

export default ChatMessageList;
