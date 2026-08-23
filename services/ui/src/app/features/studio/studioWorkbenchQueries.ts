/**
 * Query key factory for the workbench surface (StudioWorkbenchSurface.tsx).
 *
 * Unlike workflowLibraryQueries.ts, there's no shared caller for these keys
 * elsewhere in the app yet — this exists purely to keep useQuery reads and
 * queryClient.invalidateQueries writes from drifting apart within the one
 * component, following the same per-feature key-factory pattern.
 *
 * The fetch functions themselves already live in studioApi.ts and are used
 * directly as queryFns — no wrapping needed.
 */
export const studioWorkbenchKeys = {
  capabilityCatalog: () => ["studio-workbench", "capability-catalog"] as const,
  agentDefinitions: (userId: string) => ["studio-workbench", "agent-definitions", userId] as const,
  agentDefinitionVersions: (agentId: string) =>
    ["studio-workbench", "agent-definition-versions", agentId] as const,
  capabilitySearch: (query: string) => ["studio-workbench", "capability-search", query] as const,
  runDebugger: (runId: string) => ["studio-workbench", "run-debugger", runId] as const,
};
