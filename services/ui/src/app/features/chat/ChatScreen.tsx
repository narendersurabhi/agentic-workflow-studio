import type { Dispatch, RefObject, SetStateAction } from "react";

import Button from "../../components/ui/Button";
import type { FeedbackEntry, FeedbackSentiment } from "../../lib/feedback";
import type { CapabilityCatalog, Job } from "../../WorkspaceSurfaceContent";
import type { CapabilityItem as SkillCapabilityItem, Skill } from "../skills/types";
import { ChatComposer } from "./ChatComposer";
import { ChatMessageList } from "./ChatMessageList";
import type { ChatSession } from "./types";

export type ChatScreenProps = {
  jobs: Job[];
  chatSession: ChatSession | null;
  chatLoading: boolean;
  chatError: string | null;
  chatNotice: string | null;
  feedbackError: string | null;
  chatInput: string;
  setChatInput: Dispatch<SetStateAction<string>>;
  resetChatSession: () => void;
  submitChatTurn: () => void;
  chatTranscriptRef: RefObject<HTMLDivElement | null>;
  chatInputRef: RefObject<HTMLTextAreaElement | null>;
  showSkillPalette: boolean;
  setShowSkillPalette: (show: boolean) => void;
  skills: Skill[];
  capabilityCatalog: CapabilityCatalog | null;
  showSaveSkillForm: boolean;
  setShowSaveSkillForm: Dispatch<SetStateAction<boolean>>;
  saveSkillName: string;
  setSaveSkillName: (value: string) => void;
  saveSkillDesc: string;
  setSaveSkillDesc: (value: string) => void;
  saveSkillError: string | null;
  setSaveSkillError: (value: string | null) => void;
  saveCurrentAsSkill: () => void;
  feedbackByTarget: Record<string, FeedbackEntry>;
  feedbackSubmitting: Record<string, boolean>;
  submitFeedback: (
    targetType: "chat_message",
    targetId: string,
    payload: { sentiment: FeedbackSentiment; reason_codes: string[]; comment?: string },
  ) => Promise<void> | void;
  formatTimestamp: (value?: string) => string;
};

export function ChatScreen({
  jobs,
  chatSession,
  chatLoading,
  chatError,
  chatNotice,
  feedbackError,
  chatInput,
  setChatInput,
  resetChatSession,
  submitChatTurn,
  chatTranscriptRef,
  chatInputRef,
  showSkillPalette,
  setShowSkillPalette,
  skills,
  capabilityCatalog,
  showSaveSkillForm,
  setShowSaveSkillForm,
  saveSkillName,
  setSaveSkillName,
  saveSkillDesc,
  setSaveSkillDesc,
  saveSkillError,
  setSaveSkillError,
  saveCurrentAsSkill,
  feedbackByTarget,
  feedbackSubmitting,
  submitFeedback,
  formatTimestamp,
}: ChatScreenProps) {
  const chatMessages = chatSession?.messages || [];
  const activeJob = chatSession?.active_job_id
    ? jobs.find((j) => j.id === chatSession.active_job_id)
    : null;
  const activeJobStatus = activeJob?.status ?? (chatSession?.active_job_id ? "running" : null);
  const isJobTerminal = activeJobStatus
    ? ["succeeded", "failed", "canceled", "completed", "accepted"].includes(activeJobStatus)
    : false;
  const jobStatusColor = !activeJobStatus
    ? ""
    : activeJobStatus === "succeeded" || activeJobStatus === "completed" || activeJobStatus === "accepted"
    ? "border-emerald-300/25 bg-accent-emerald text-text-emerald-token"
    : activeJobStatus === "failed" || activeJobStatus === "canceled"
    ? "border-rose-300/20 bg-accent-rose text-text-rose-token"
    : "border-sky-300/22 bg-accent-sky text-text-sky-token";

  return (
    <div className="flex h-[calc(100dvh-60px)] flex-col gap-0 overflow-hidden">
      {/* ── Top bar ── */}
      <div className="flex shrink-0 items-center justify-between gap-4 border-b border-subtle px-4 py-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.22em] text-text-sky-token">
            AI Workflow Workspace
          </div>
          <h1 className="mt-0.5 text-lg font-semibold tracking-tight text-text-hi">Chat</h1>
        </div>
        <Button variant="secondary" onClick={resetChatSession} disabled={chatLoading}>
          New Chat
        </Button>
      </div>

      {/* ── Transcript ── */}
      <ChatMessageList
        messages={chatMessages}
        loading={chatLoading}
        feedbackByTarget={feedbackByTarget}
        feedbackSubmitting={feedbackSubmitting}
        onSubmitFeedback={(messageId, payload) => submitFeedback("chat_message", messageId, payload)}
        formatTimestamp={formatTimestamp}
        transcriptRef={chatTranscriptRef}
      />

      {/* ── Active job card ── */}
      {chatSession?.active_job_id ? (
        <div
          className={`mx-4 mb-2 shrink-0 flex items-center justify-between gap-3 rounded-2xl border px-4 py-2.5 text-sm ${jobStatusColor}`}
        >
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] opacity-70">
              {isJobTerminal ? "Last job" : "Running job"}
            </span>
            <span className="truncate font-mono text-xs">{chatSession.active_job_id}</span>
            <span className="text-[11px] capitalize opacity-80">{activeJobStatus}</span>
          </div>
          <a
            href={`/observability?job=${encodeURIComponent(chatSession.active_job_id)}`}
            className="shrink-0 rounded-xl border border-current/30 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] opacity-90 transition hover:opacity-100"
          >
            View details
          </a>
        </div>
      ) : null}

      {/* ── Input bar ── */}
      <div className="shrink-0 border-t border-subtle bg-gradient-panel px-4 py-3 space-y-2">
        {chatError ? (
          <div className="rounded-xl border border-rose-300/20 bg-accent-rose px-3 py-2 text-sm text-text-rose-token">
            {chatError}
          </div>
        ) : null}
        {chatNotice ? (
          <div className="rounded-xl border border-sky-300/20 bg-accent-sky px-3 py-2 text-sm text-text-sky-token">
            {chatNotice}
          </div>
        ) : null}
        {feedbackError ? (
          <div className="rounded-xl border border-amber-300/20 bg-accent-amber px-3 py-2 text-sm text-text-amber-token">
            Feedback error: {feedbackError}
          </div>
        ) : null}
        <ChatComposer
          value={chatInput}
          onChange={setChatInput}
          onSubmit={submitChatTurn}
          sending={chatLoading}
          textareaRef={chatInputRef}
          showSkillPalette={showSkillPalette}
          onShowSkillPalette={setShowSkillPalette}
          skills={skills}
          capabilities={(capabilityCatalog?.items ?? []) as SkillCapabilityItem[]}
          showSaveSkillForm={showSaveSkillForm}
          onToggleSaveSkillForm={() => {
            setSaveSkillName("");
            setSaveSkillDesc("");
            setSaveSkillError(null);
            setShowSaveSkillForm((prev) => !prev);
          }}
          saveSkillName={saveSkillName}
          onSaveSkillNameChange={setSaveSkillName}
          saveSkillDesc={saveSkillDesc}
          onSaveSkillDescChange={setSaveSkillDesc}
          saveSkillError={saveSkillError}
          onSaveSkill={saveCurrentAsSkill}
          onCancelSaveSkill={() => setShowSaveSkillForm(false)}
        />
      </div>
    </div>
  );
}

export default ChatScreen;
