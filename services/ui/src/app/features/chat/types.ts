import type { Job } from "../../WorkspaceSurfaceContent";

export type ChatAssistantAction = {
  type:
    | "respond"
    | "tool_call"
    | "ask_clarification"
    | "submit_job"
    | "run_workflow"
    | "attach_to_job"
    | "summarize_job";
  goal?: string | null;
  job_id?: string | null;
  workflow_run_id?: string | null;
  workflow_definition_id?: string | null;
  workflow_version_id?: string | null;
  workflow_trigger_id?: string | null;
  capability_id?: string | null;
  tool_name?: string | null;
  clarification_questions?: string[];
  goal_intent_profile?: Record<string, unknown>;
  context_json?: Record<string, unknown>;
};

export type ToolStepItem = {
  capability: string;
  label: string;
  status: "running" | "done";
  result?: Record<string, unknown>;
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  metadata?: Record<string, unknown>;
  action?: ChatAssistantAction | null;
  job_id?: string | null;
};

export type ChatSession = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
  active_job_id?: string | null;
  messages: ChatMessage[];
};

export type ChatTurnResponse = {
  session: ChatSession;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  job?: Job | null;
  workflow_run?: Record<string, unknown> | null;
};

export const makeOptimisticChatMessage = (sessionId: string, content: string): ChatMessage => {
  const createdAt = new Date().toISOString();
  return {
    id: `optimistic-${createdAt}-${Math.random().toString(36).slice(2, 8)}`,
    session_id: sessionId,
    role: "user",
    content,
    created_at: createdAt,
    metadata: {
      optimistic: true,
      pending: true,
    },
    action: null,
    job_id: null,
  };
};

export const appendChatMessage = (session: ChatSession, message: ChatMessage): ChatSession => ({
  ...session,
  updated_at: message.created_at,
  messages: [...(Array.isArray(session.messages) ? session.messages : []), message],
});
