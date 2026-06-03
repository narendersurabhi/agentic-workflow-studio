"use client";

import { useEffect, useState } from "react";
import type { FeedbackEntry, FeedbackReasonOption, FeedbackSentiment } from "../../lib/feedback";

type ChatMessageFeedbackProps = {
  reasonOptions: FeedbackReasonOption[];
  existing?: FeedbackEntry | null;
  submitting?: boolean;
  onSubmit: (payload: {
    sentiment: FeedbackSentiment;
    reason_codes: string[];
    comment?: string;
  }) => Promise<void> | void;
};

function ThumbUpIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-3.5 w-3.5"
      aria-hidden="true"
    >
      <path d="M7 10.5V16a1 1 0 0 0 1 1h5.5a1.5 1.5 0 0 0 1.47-1.2l.9-4.5A1.5 1.5 0 0 0 14.4 9.5H11V5a1.5 1.5 0 0 0-1.5-1.5h-.25a.75.75 0 0 0-.75.75V6L7 10.5Z" />
      <path d="M4.5 9.5H6a.5.5 0 0 1 .5.5v7a.5.5 0 0 1-.5.5H4.5A1.5 1.5 0 0 1 3 16v-5a1.5 1.5 0 0 1 1.5-1.5Z" />
    </svg>
  );
}

function ThumbDownIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-3.5 w-3.5"
      aria-hidden="true"
    >
      <path d="M13 9.5V4a1 1 0 0 0-1-1H6.5A1.5 1.5 0 0 0 5.03 4.2l-.9 4.5A1.5 1.5 0 0 0 5.6 10.5H9V15a1.5 1.5 0 0 0 1.5 1.5h.25a.75.75 0 0 0 .75-.75V14l1.5-4.5Z" />
      <path d="M15.5 10.5H14a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5h1.5A1.5 1.5 0 0 1 17 4v5a1.5 1.5 0 0 1-1.5 1.5Z" />
    </svg>
  );
}

export default function ChatMessageFeedback({
  reasonOptions,
  existing,
  submitting = false,
  onSubmit
}: ChatMessageFeedbackProps) {
  const [expanded, setExpanded] = useState(false);
  const [selectedReasons, setSelectedReasons] = useState<string[]>([]);
  const [comment, setComment] = useState("");

  useEffect(() => {
    if (existing) {
      setSelectedReasons(Array.isArray(existing.reason_codes) ? existing.reason_codes : []);
      setComment(typeof existing.comment === "string" ? existing.comment : "");
      setExpanded(false);
    }
  }, [existing]);

  const handleThumbUp = async () => {
    if (existing) return;
    await Promise.resolve(onSubmit({ sentiment: "positive", reason_codes: [] }));
  };

  const handleThumbDown = () => {
    if (existing) return;
    setExpanded(true);
  };

  const submitNegative = async () => {
    await Promise.resolve(
      onSubmit({ sentiment: "negative", reason_codes: selectedReasons, comment: comment.trim() || undefined })
    );
    setExpanded(false);
  };

  const toggleReason = (code: string) => {
    setSelectedReasons((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );
  };

  const isPositive = existing?.sentiment === "positive";
  const isNegative = existing?.sentiment === "negative";

  return (
    <div className="mt-2">
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="Helpful"
          disabled={submitting || Boolean(existing)}
          onClick={() => void handleThumbUp()}
          className={`rounded-md p-1 transition ${
            isPositive
              ? "text-emerald-500"
              : "text-text-lo hover:text-text-md disabled:opacity-40"
          }`}
        >
          <ThumbUpIcon filled={isPositive} />
        </button>
        <button
          type="button"
          aria-label="Not helpful"
          disabled={submitting || Boolean(existing)}
          onClick={handleThumbDown}
          className={`rounded-md p-1 transition ${
            isNegative
              ? "text-rose-400"
              : "text-text-lo hover:text-text-md disabled:opacity-40"
          }`}
        >
          <ThumbDownIcon filled={isNegative} />
        </button>
        {existing ? (
          <span className="ml-1 text-[10px] text-text-lo">
            {isPositive ? "Marked helpful" : "Feedback saved"}
          </span>
        ) : null}
      </div>

      {expanded ? (
        <div className="mt-2 space-y-2 rounded-xl border border-subtle bg-surface-1 p-3">
          <p className="text-[11px] font-medium text-text-md">What went wrong?</p>
          <div className="flex flex-wrap gap-1.5">
            {reasonOptions.map((reason) => {
              const active = selectedReasons.includes(reason.code);
              return (
                <button
                  key={reason.code}
                  type="button"
                  className={`rounded-full border px-2 py-0.5 text-[11px] transition ${
                    active
                      ? "border-amber-300/60 bg-amber-400/20 text-text-hi"
                      : "border-subtle bg-surface-2 text-text-md hover:border-default hover:text-text-hi"
                  }`}
                  onClick={() => toggleReason(reason.code)}
                >
                  {reason.label}
                </button>
              );
            })}
          </div>
          <textarea
            className="min-h-[3.5rem] w-full resize-none rounded-lg border border-subtle bg-surface-input px-3 py-2 text-xs text-text-hi placeholder:text-text-placeholder focus:border-default focus:outline-none"
            placeholder="Optional comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              className="rounded-full border border-subtle px-3 py-1 text-[11px] text-text-md hover:border-default hover:text-text-hi"
              onClick={() => setExpanded(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={submitting}
              className="rounded-full bg-slate-900 px-3 py-1 text-[11px] font-semibold text-slate-50 disabled:opacity-50"
              onClick={() => void submitNegative()}
            >
              {submitting ? "Saving…" : "Send"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
