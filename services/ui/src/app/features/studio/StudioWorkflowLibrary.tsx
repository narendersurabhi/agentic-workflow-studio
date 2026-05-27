"use client";

import type {
  WorkflowDefinition,
  WorkflowRun,
  WorkflowTrigger,
  WorkflowVersion,
} from "./types";
import { formatTimestamp } from "./utils";

type StudioWorkflowLibraryProps = {
  workflowDefinitions: WorkflowDefinition[];
  workflowDefinitionsLoading: boolean;
  workflowDefinitionsError: string | null;
  workflowVersions: WorkflowVersion[];
  workflowVersionsLoading: boolean;
  workflowVersionsError: string | null;
  workflowTriggers: WorkflowTrigger[];
  workflowTriggersLoading: boolean;
  workflowTriggersError: string | null;
  workflowRuns: WorkflowRun[];
  workflowRunsLoading: boolean;
  workflowRunsError: string | null;
  activeWorkflowDefinitionId: string | null;
  activeWorkflowVersionId: string | null;
  deletingWorkflowDefinitionId: string | null;
  onRefresh: () => void;
  onSelectDefinition?: (definition: WorkflowDefinition) => void;
  onOpenDefinition: (definition: WorkflowDefinition) => void;
  onDeleteDefinition: (definition: WorkflowDefinition) => void;
  openDefinitionLabel?: string;
  onSelectVersion?: (version: WorkflowVersion) => void;
  onOpenVersion: (version: WorkflowVersion) => void;
  openVersionLabel?: string;
  onCreateManualTrigger: () => void;
  onInvokeTrigger: (trigger: WorkflowTrigger) => void;
};

const libraryPanelClassName =
  "rounded-[32px] border border-subtle bg-gradient-panel p-4 text-text-hi shadow-card";
const librarySectionHeadingClassName =
  "text-[11px] font-semibold uppercase tracking-[0.18em] text-text-md";
const libraryCardClassName =
  "rounded-2xl border border-subtle bg-surface-1 px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]";
const libraryActiveSkyCardClassName =
  "rounded-2xl border border-sky-300/28 bg-accent-sky px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]";
const libraryActiveEmeraldCardClassName =
  "rounded-2xl border border-emerald-300/28 bg-accent-emerald px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]";
const libraryPillClassName =
  "rounded-full border border-subtle bg-surface-1 px-2.5 py-1 text-text-md";
const libraryActionButtonClassName =
  "rounded-full border border-subtle bg-surface-1 px-3 py-1.5 text-xs font-semibold text-text-hi transition hover:border-sky-300/40 hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50";

export default function StudioWorkflowLibrary({
  workflowDefinitions,
  workflowDefinitionsLoading,
  workflowDefinitionsError,
  workflowVersions,
  workflowVersionsLoading,
  workflowVersionsError,
  workflowTriggers,
  workflowTriggersLoading,
  workflowTriggersError,
  workflowRuns,
  workflowRunsLoading,
  workflowRunsError,
  activeWorkflowDefinitionId,
  activeWorkflowVersionId,
  deletingWorkflowDefinitionId,
  onRefresh,
  onSelectDefinition,
  onOpenDefinition,
  onDeleteDefinition,
  openDefinitionLabel = "Open Draft",
  onSelectVersion,
  onOpenVersion,
  openVersionLabel = "Restore Version",
  onCreateManualTrigger,
  onInvokeTrigger,
}: StudioWorkflowLibraryProps) {
  return (
    <section className={libraryPanelClassName}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-text-sky-token">
            Saved Workflows
          </div>
          <h3 className="mt-1 font-display text-2xl text-text-hi">Workflow Versions</h3>
        </div>
        <button
          className="rounded-full border border-subtle bg-surface-1 px-4 py-2 text-sm font-semibold text-text-hi transition hover:border-sky-300/40 hover:bg-surface-1"
          onClick={onRefresh}
        >
          Refresh
        </button>
      </div>

      <p className="mt-3 text-sm leading-6 text-text-md">
        Manage reusable workflow definitions, versions, triggers, and published automations.
      </p>

      <div className="mt-4">
        <div className={librarySectionHeadingClassName}>Definitions</div>
        {workflowDefinitionsLoading ? (
          <div className="mt-3 rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-sm text-text-md">
            Loading saved workflows...
          </div>
        ) : workflowDefinitionsError ? (
          <div className="mt-3 rounded-2xl border border-subtle bg-accent-rose px-4 py-3 text-sm text-text-rose-token">
            {workflowDefinitionsError}
          </div>
        ) : workflowDefinitions.length === 0 ? (
          <div className="mt-3 rounded-2xl border border-dashed border-subtle bg-surface-1 px-4 py-4 text-sm text-text-lo">
            Save a Studio draft to start building version history.
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            {workflowDefinitions.map((definition) => {
              const isActive = definition.id === activeWorkflowDefinitionId;
              return (
                <article
                  key={definition.id}
                  className={`${isActive ? libraryActiveSkyCardClassName : libraryCardClassName} ${
                    onSelectDefinition ? "cursor-pointer transition hover:border-sky-300/40 hover:bg-surface-1" : ""
                  }`}
                  onClick={() => {
                    onSelectDefinition?.(definition);
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-text-hi">
                        {definition.title}
                      </div>
                      <div className="mt-1 line-clamp-2 text-xs leading-5 text-text-md">
                        {definition.goal || "No goal recorded for this workflow."}
                      </div>
                    </div>
                    {isActive ? (
                      <span className="rounded-full border border-sky-300/25 bg-accent-sky px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-sky-token">
                        Active
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.14em] text-text-lo">
                    <span className={libraryPillClassName}>
                      updated {formatTimestamp(definition.updated_at)}
                    </span>
                    {definition.user_id ? (
                      <span className={libraryPillClassName}>
                        user {definition.user_id}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      className={libraryActionButtonClassName}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenDefinition(definition);
                      }}
                    >
                      {openDefinitionLabel}
                    </button>
                    <button
                      className="rounded-full border border-rose-300/30 bg-accent-rose px-3 py-1.5 text-xs font-semibold text-text-rose-token transition hover:border-rose-400/50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={(event) => {
                        event.stopPropagation();
                        onDeleteDefinition(definition);
                      }}
                      disabled={deletingWorkflowDefinitionId === definition.id}
                    >
                      {deletingWorkflowDefinitionId === definition.id ? "Deleting..." : "Delete"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>

      <div className="mt-6">
        <div className="flex items-center justify-between gap-3">
          <div className={librarySectionHeadingClassName}>Triggers</div>
          <button
            className={libraryActionButtonClassName}
            onClick={onCreateManualTrigger}
            disabled={!activeWorkflowDefinitionId}
          >
            Create Manual Trigger
          </button>
        </div>
        {!activeWorkflowDefinitionId ? (
          <div className="mt-3 rounded-2xl border border-dashed border-subtle bg-surface-1 px-4 py-4 text-sm text-text-lo">
            Open a saved workflow definition before configuring triggers.
          </div>
        ) : workflowTriggersLoading ? (
          <div className="mt-3 rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-sm text-text-md">
            Loading triggers...
          </div>
        ) : workflowTriggersError ? (
          <div className="mt-3 rounded-2xl border border-subtle bg-accent-rose px-4 py-3 text-sm text-text-rose-token">
            {workflowTriggersError}
          </div>
        ) : workflowTriggers.length === 0 ? (
          <div className="mt-3 rounded-2xl border border-dashed border-subtle bg-surface-1 px-4 py-4 text-sm text-text-lo">
            No triggers yet. Create a manual trigger to invoke the latest published version.
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            {workflowTriggers.map((trigger) => (
              <article
                key={trigger.id}
                className={libraryCardClassName}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-text-hi">
                      {trigger.title}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.14em] text-text-lo">
                      <span className={libraryPillClassName}>
                        {trigger.trigger_type}
                      </span>
                      <span
                        className={`rounded-full border px-2.5 py-1 ${
                          trigger.enabled
                            ? "border-emerald-300/25 bg-accent-emerald text-text-emerald-token"
                            : "border-subtle bg-surface-1 text-text-md"
                        }`}
                      >
                        {trigger.enabled ? "enabled" : "disabled"}
                      </span>
                    </div>
                  </div>
                  <button
                    className={libraryActionButtonClassName}
                    onClick={() => onInvokeTrigger(trigger)}
                    disabled={!trigger.enabled}
                  >
                    Invoke
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <div className="mt-6">
        <div className={librarySectionHeadingClassName}>Version History</div>
        {!activeWorkflowDefinitionId ? (
          <div className="mt-3 rounded-2xl border border-dashed border-subtle bg-surface-1 px-4 py-4 text-sm text-text-lo">
            Open a saved workflow definition to browse its published versions.
          </div>
        ) : workflowVersionsLoading ? (
          <div className="mt-3 rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-sm text-text-md">
            Loading version history...
          </div>
        ) : workflowVersionsError ? (
          <div className="mt-3 rounded-2xl border border-subtle bg-accent-rose px-4 py-3 text-sm text-text-rose-token">
            {workflowVersionsError}
          </div>
        ) : workflowVersions.length === 0 ? (
          <div className="mt-3 rounded-2xl border border-dashed border-subtle bg-surface-1 px-4 py-4 text-sm text-text-lo">
            Publish a version to make this workflow runnable and restorable.
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            {workflowVersions.map((version) => {
              const isActive = version.id === activeWorkflowVersionId;
              return (
                <article
                  key={version.id}
                  className={`${isActive ? libraryActiveEmeraldCardClassName : libraryCardClassName} ${
                    onSelectVersion
                      ? "cursor-pointer transition hover:border-emerald-300/40 hover:bg-surface-1"
                      : ""
                  }`}
                  onClick={() => {
                    onSelectVersion?.(version);
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-text-hi">
                        v{version.version_number}
                      </div>
                      <div className="mt-1 text-xs text-text-lo">
                        {formatTimestamp(version.created_at)}
                      </div>
                    </div>
                    {isActive ? (
                      <span className="rounded-full border border-emerald-300/25 bg-accent-emerald px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-emerald-token">
                        Loaded
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-3 line-clamp-2 text-xs leading-5 text-text-md">
                    {version.goal || version.title || "Published workflow version"}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      className={libraryActionButtonClassName}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenVersion(version);
                      }}
                    >
                      {openVersionLabel}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>

      <div className="mt-6">
        <div className={librarySectionHeadingClassName}>Run History</div>
        {!activeWorkflowDefinitionId ? (
          <div className="mt-3 rounded-2xl border border-dashed border-subtle bg-surface-1 px-4 py-4 text-sm text-text-lo">
            Open a saved workflow definition to browse its run history.
          </div>
        ) : workflowRunsLoading ? (
          <div className="mt-3 rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-sm text-text-md">
            Loading workflow runs...
          </div>
        ) : workflowRunsError ? (
          <div className="mt-3 rounded-2xl border border-subtle bg-accent-rose px-4 py-3 text-sm text-text-rose-token">
            {workflowRunsError}
          </div>
        ) : workflowRuns.length === 0 ? (
          <div className="mt-3 rounded-2xl border border-dashed border-subtle bg-surface-1 px-4 py-4 text-sm text-text-lo">
            No runs yet. Publish and run a workflow, or invoke a trigger, to populate history.
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            {workflowRuns.map((run) => (
              <article
                key={run.id}
                className={libraryCardClassName}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-text-hi">{run.title}</div>
                    <div className="mt-1 text-xs text-text-lo">
                      {formatTimestamp(run.updated_at || run.created_at)}
                    </div>
                  </div>
                  <span
                    className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] ${
                      run.job_status === "succeeded"
                        ? "border border-emerald-300/25 bg-accent-emerald text-text-emerald-token"
                        : run.job_status === "failed"
                          ? "border border-rose-300/25 bg-accent-rose text-text-rose-token"
                          : run.job_status === "running"
                            ? "border border-sky-300/25 bg-accent-sky text-text-sky-token"
                            : "border border-subtle bg-surface-1 text-text-md"
                    }`}
                  >
                    {run.job_status || "queued"}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.14em] text-text-lo">
                  <span className={libraryPillClassName}>
                    job {run.job_id.slice(0, 8)}
                  </span>
                  <span className={libraryPillClassName}>
                    plan {run.plan_id.slice(0, 8)}
                  </span>
                  <span className={libraryPillClassName}>
                    version {run.version_id.slice(0, 8)}
                  </span>
                  {run.trigger_id ? (
                    <span className={libraryPillClassName}>
                      trigger {run.trigger_id.slice(0, 8)}
                    </span>
                  ) : null}
                </div>
                {run.latest_task_error ? (
                  <div className="mt-3 rounded-2xl border border-subtle bg-accent-rose px-3 py-3 text-xs leading-5 text-text-rose-token">
                    <div className="font-semibold uppercase tracking-[0.14em]">
                      Latest Task Error
                    </div>
                    <div className="mt-1">
                      {run.latest_task_name ? `${run.latest_task_name}: ` : null}
                      {run.latest_task_error}
                    </div>
                  </div>
                ) : run.job_error ? (
                  <div className="mt-3 rounded-2xl border border-subtle bg-accent-amber px-3 py-3 text-xs leading-5 text-text-amber-token">
                    <div className="font-semibold uppercase tracking-[0.14em]">
                      Run Error
                    </div>
                    <div className="mt-1">{run.job_error}</div>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
