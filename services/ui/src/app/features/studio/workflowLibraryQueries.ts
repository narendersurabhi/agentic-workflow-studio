import { fetchJson } from "../../lib/queryFetch";
import type {
  WorkflowDefinition,
  WorkflowRun,
  WorkflowRunResult,
  WorkflowTrigger,
  WorkflowVersion,
} from "./types";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";

/**
 * Query key factory for the workflow library screen. Centralizing these keeps
 * `useQuery` reads and `queryClient.invalidateQueries`/`setQueryData` writes
 * from drifting apart — later phases converting other screens should follow
 * the same per-feature key-factory pattern rather than inlining key arrays.
 */
export const workflowLibraryKeys = {
  definitions: (userId: string) => ["workflow-definitions", userId] as const,
  versions: (definitionId: string) => ["workflow-versions", definitionId] as const,
  triggers: (definitionId: string) => ["workflow-triggers", definitionId] as const,
  runs: (definitionId: string) => ["workflow-runs", definitionId] as const,
};

export async function fetchWorkflowDefinitions(userId: string): Promise<WorkflowDefinition[]> {
  const params = new URLSearchParams();
  const normalizedUserId = userId.trim();
  if (normalizedUserId) {
    params.set("user_id", normalizedUserId);
  }
  const body = await fetchJson<WorkflowDefinition[]>(
    `${apiUrl}/workflows/definitions${params.size > 0 ? `?${params.toString()}` : ""}`,
    undefined,
    "Workflow library request failed"
  );
  return Array.isArray(body) ? body : [];
}

export async function fetchWorkflowVersions(definitionId: string): Promise<WorkflowVersion[]> {
  const body = await fetchJson<WorkflowVersion[]>(
    `${apiUrl}/workflows/definitions/${encodeURIComponent(definitionId)}/versions`,
    undefined,
    "Workflow version history request failed"
  );
  return Array.isArray(body) ? body : [];
}

export async function fetchWorkflowTriggers(definitionId: string): Promise<WorkflowTrigger[]> {
  const body = await fetchJson<WorkflowTrigger[]>(
    `${apiUrl}/workflows/definitions/${encodeURIComponent(definitionId)}/triggers`,
    undefined,
    "Workflow trigger request failed"
  );
  return Array.isArray(body) ? body : [];
}

export async function fetchWorkflowRuns(definitionId: string): Promise<WorkflowRun[]> {
  const body = await fetchJson<WorkflowRun[]>(
    `${apiUrl}/workflows/definitions/${encodeURIComponent(definitionId)}/runs?limit=12`,
    undefined,
    "Workflow run history request failed"
  );
  return Array.isArray(body) ? body : [];
}

export async function deleteWorkflowDefinitionRequest(definitionId: string): Promise<void> {
  await fetchJson<null>(
    `${apiUrl}/workflows/definitions/${encodeURIComponent(definitionId)}`,
    { method: "DELETE" },
    "Delete draft failed"
  );
}

export async function deleteWorkflowVersionRequest(versionId: string): Promise<void> {
  await fetchJson<null>(
    `${apiUrl}/workflows/versions/${encodeURIComponent(versionId)}`,
    { method: "DELETE" },
    "Delete version failed"
  );
}

export async function createManualWorkflowTriggerRequest(input: {
  definitionId: string;
  title: string;
  workspaceUserId: string;
}): Promise<WorkflowTrigger> {
  return fetchJson<WorkflowTrigger>(
    `${apiUrl}/workflows/definitions/${encodeURIComponent(input.definitionId)}/triggers`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: `${input.title} manual trigger`,
        trigger_type: "manual",
        enabled: true,
        config: { version_mode: "latest_published" },
        user_id: input.workspaceUserId.trim() || undefined,
        metadata: { source: "workflow_library_page" },
      }),
    },
    "Create trigger failed"
  );
}

export async function invokeWorkflowTriggerRequest(triggerId: string): Promise<WorkflowRunResult> {
  return fetchJson<WorkflowRunResult>(
    `${apiUrl}/workflows/triggers/${encodeURIComponent(triggerId)}/invoke`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priority: 0 }),
    },
    "Trigger invoke failed"
  );
}
