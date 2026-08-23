"use client";

import Link from "next/link";
import { useAuth } from "../../lib/auth";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useShell, ShellActions } from "../../lib/shell";
import StudioWorkflowLibrary from "./StudioWorkflowLibrary";
import {
  workflowLibraryKeys,
  fetchWorkflowDefinitions,
  fetchWorkflowVersions,
  fetchWorkflowTriggers,
  fetchWorkflowRuns,
  deleteWorkflowDefinitionRequest,
  deleteWorkflowVersionRequest,
  createManualWorkflowTriggerRequest,
  invokeWorkflowTriggerRequest,
} from "./workflowLibraryQueries";
import type { WorkflowDefinition, WorkflowTrigger, WorkflowVersion } from "./types";

export default function WorkflowLibraryPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user: authUser } = useAuth();
  const [workspaceUserId, setWorkspaceUserId] = useState("");
  const [activeWorkflowDefinitionId, setActiveWorkflowDefinitionId] = useState<string | null>(null);
  const [activeWorkflowVersionId, setActiveWorkflowVersionId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (authUser?.user_id) {
      setWorkspaceUserId(authUser.user_id);
    }
  }, [authUser?.user_id]);

  const definitionsQuery = useQuery({
    queryKey: workflowLibraryKeys.definitions(workspaceUserId),
    queryFn: () => fetchWorkflowDefinitions(workspaceUserId),
  });
  const workflowDefinitions = useMemo(() => definitionsQuery.data ?? [], [definitionsQuery.data]);

  useEffect(() => {
    if (workflowDefinitions.length === 0) {
      setActiveWorkflowDefinitionId(null);
      return;
    }
    if (
      !activeWorkflowDefinitionId ||
      !workflowDefinitions.some((item) => item.id === activeWorkflowDefinitionId)
    ) {
      setActiveWorkflowDefinitionId(workflowDefinitions[0].id);
    }
  }, [activeWorkflowDefinitionId, workflowDefinitions]);

  const versionsQuery = useQuery({
    queryKey: workflowLibraryKeys.versions(activeWorkflowDefinitionId ?? ""),
    queryFn: () => fetchWorkflowVersions(activeWorkflowDefinitionId as string),
    enabled: Boolean(activeWorkflowDefinitionId),
  });
  const workflowVersions = useMemo(
    () => (activeWorkflowDefinitionId ? versionsQuery.data ?? [] : []),
    [activeWorkflowDefinitionId, versionsQuery.data]
  );

  const triggersQuery = useQuery({
    queryKey: workflowLibraryKeys.triggers(activeWorkflowDefinitionId ?? ""),
    queryFn: () => fetchWorkflowTriggers(activeWorkflowDefinitionId as string),
    enabled: Boolean(activeWorkflowDefinitionId),
  });
  const workflowTriggers = activeWorkflowDefinitionId ? triggersQuery.data ?? [] : [];

  const runsQuery = useQuery({
    queryKey: workflowLibraryKeys.runs(activeWorkflowDefinitionId ?? ""),
    queryFn: () => fetchWorkflowRuns(activeWorkflowDefinitionId as string),
    enabled: Boolean(activeWorkflowDefinitionId),
  });
  const workflowRuns = activeWorkflowDefinitionId ? runsQuery.data ?? [] : [];

  useEffect(() => {
    if (!activeWorkflowVersionId || !workflowVersions.some((version) => version.id === activeWorkflowVersionId)) {
      setActiveWorkflowVersionId(workflowVersions[0]?.id || null);
    }
  }, [activeWorkflowVersionId, workflowVersions]);

  const activeWorkflowDefinition = useMemo(
    () => workflowDefinitions.find((definition) => definition.id === activeWorkflowDefinitionId) || null,
    [activeWorkflowDefinitionId, workflowDefinitions]
  );

  const invalidateActiveDefinitionQueries = () => {
    if (!activeWorkflowDefinitionId) return;
    void queryClient.invalidateQueries({ queryKey: workflowLibraryKeys.versions(activeWorkflowDefinitionId) });
    void queryClient.invalidateQueries({ queryKey: workflowLibraryKeys.triggers(activeWorkflowDefinitionId) });
    void queryClient.invalidateQueries({ queryKey: workflowLibraryKeys.runs(activeWorkflowDefinitionId) });
  };

  const deleteDefinitionMutation = useMutation({
    mutationFn: (definition: WorkflowDefinition) => deleteWorkflowDefinitionRequest(definition.id),
    onSuccess: (_data, definition) => {
      queryClient.setQueryData<WorkflowDefinition[]>(
        workflowLibraryKeys.definitions(workspaceUserId),
        (prev: WorkflowDefinition[] | undefined) => (prev ?? []).filter((item) => item.id !== definition.id)
      );
      setNotice(`Deleted "${definition.title}".`);
      setActionError(null);
    },
    onError: (error) => {
      console.error("[WorkflowLibrary] deleteWorkflowDefinition:", error);
      setActionError(error instanceof Error ? error.message : "Failed to delete saved draft.");
    },
  });

  const deleteVersionMutation = useMutation({
    mutationFn: (version: WorkflowVersion) => deleteWorkflowVersionRequest(version.id),
    onSuccess: (_data, version) => {
      queryClient.setQueryData<WorkflowVersion[]>(
        workflowLibraryKeys.versions(version.definition_id),
        (prev: WorkflowVersion[] | undefined) => (prev ?? []).filter((v) => v.id !== version.id)
      );
      if (activeWorkflowDefinitionId) {
        void queryClient.invalidateQueries({ queryKey: workflowLibraryKeys.runs(activeWorkflowDefinitionId) });
      }
      setNotice(`Deleted version v${version.version_number}.`);
      setActionError(null);
    },
    onError: (error) => {
      console.error("[WorkflowLibrary] deleteWorkflowVersion:", error);
      setActionError(error instanceof Error ? error.message : "Failed to delete version.");
    },
  });

  const createManualTriggerMutation = useMutation({
    mutationFn: () => {
      if (!activeWorkflowDefinitionId || !activeWorkflowDefinition) {
        throw new Error("Select a workflow definition before creating a trigger.");
      }
      return createManualWorkflowTriggerRequest({
        definitionId: activeWorkflowDefinitionId,
        title: activeWorkflowDefinition.title,
        workspaceUserId,
      });
    },
    onSuccess: (trigger) => {
      invalidateActiveDefinitionQueries();
      setNotice(`Created manual trigger ${trigger.title}.`);
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : "Failed to create workflow trigger.");
    },
  });

  const invokeTriggerMutation = useMutation({
    mutationFn: (trigger: WorkflowTrigger) => invokeWorkflowTriggerRequest(trigger.id),
    onSuccess: (result, trigger) => {
      setActiveWorkflowDefinitionId(result.workflow_definition.id);
      setActiveWorkflowVersionId(result.workflow_version.id);
      void queryClient.invalidateQueries({ queryKey: workflowLibraryKeys.runs(result.workflow_definition.id) });
      setNotice(`Triggered job ${result.job.id} via ${trigger.title}.`);
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : "Failed to invoke workflow trigger.");
    },
  });

  const workflowActionLoading: "delete" | "save" | "run" | null = deleteDefinitionMutation.isPending
    || deleteVersionMutation.isPending
    ? "delete"
    : createManualTriggerMutation.isPending
    ? "save"
    : invokeTriggerMutation.isPending
    ? "run"
    : null;

  const summaryChips = [
    `drafts ${workflowDefinitions.length}`,
    `versions ${workflowVersions.length}`,
    `runs ${workflowRuns.length}`,
    workflowActionLoading ? `${workflowActionLoading}...` : "ready",
    activeWorkflowDefinition ? `active ${activeWorkflowDefinition.title}` : "no active draft",
  ];

  useShell({
    title: "Saved Workflows",
    breadcrumbs: [
      { label: "Project", href: "/project" },
      { label: "Saved Workflows" },
    ],
  });

  return (
    <>
      <ShellActions>
        <Link
          href="/studio"
          className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-sky-300/35 hover:bg-surface-1"
        >
          Open Studio
        </Link>
        <Link
          href="/studio?mode=new"
          className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-default-theme hover:bg-slate-950/35"
        >
          New Workflow
        </Link>
      </ShellActions>
      {actionError ? (
        <div className="mb-4 rounded-[24px] border border-rose-300/20 bg-accent-rose px-4 py-3 text-sm text-text-rose-token">
          {actionError}
        </div>
      ) : null}
      {notice ? (
        <div className="mb-4 rounded-[24px] border border-sky-300/15 bg-accent-sky px-4 py-3 text-sm text-text-sky-token">
          {notice}
        </div>
      ) : null}
      <section className="relative">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-[0.26em] text-text-sky-token">
                    Saved Workflows
                  </div>
                  <h2 className="mt-1 text-xl font-semibold tracking-tight text-text-hi">
                    Saved Workflows
                  </h2>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em]">
                  {summaryChips.map((chip) => (
                    <span
                      key={chip}
                      className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-text-hi"
                    >
                      {chip}
                    </span>
                  ))}
                </div>
              </div>

              <div className="mt-5 max-w-[1180px]">
                <StudioWorkflowLibrary
                  workflowDefinitions={workflowDefinitions}
                  workflowDefinitionsLoading={definitionsQuery.isFetching}
                  workflowDefinitionsError={
                    definitionsQuery.error
                      ? definitionsQuery.error instanceof Error
                        ? definitionsQuery.error.message
                        : "Failed to load saved workflows."
                      : null
                  }
                  workflowVersions={workflowVersions}
                  workflowVersionsLoading={activeWorkflowDefinitionId ? versionsQuery.isFetching : false}
                  workflowVersionsError={
                    versionsQuery.error
                      ? versionsQuery.error instanceof Error
                        ? versionsQuery.error.message
                        : "Failed to load workflow versions."
                      : null
                  }
                  workflowTriggers={workflowTriggers}
                  workflowTriggersLoading={activeWorkflowDefinitionId ? triggersQuery.isFetching : false}
                  workflowTriggersError={
                    triggersQuery.error
                      ? triggersQuery.error instanceof Error
                        ? triggersQuery.error.message
                        : "Failed to load workflow triggers."
                      : null
                  }
                  workflowRuns={workflowRuns}
                  workflowRunsLoading={activeWorkflowDefinitionId ? runsQuery.isFetching : false}
                  workflowRunsError={
                    runsQuery.error
                      ? runsQuery.error instanceof Error
                        ? runsQuery.error.message
                        : "Failed to load workflow run history."
                      : null
                  }
                  activeWorkflowDefinitionId={activeWorkflowDefinitionId}
                  activeWorkflowVersionId={activeWorkflowVersionId}
                  deletingWorkflowDefinitionId={
                    deleteDefinitionMutation.isPending ? deleteDefinitionMutation.variables?.id ?? null : null
                  }
                  onRefresh={() => {
                    void queryClient.invalidateQueries({ queryKey: workflowLibraryKeys.definitions(workspaceUserId) });
                    invalidateActiveDefinitionQueries();
                  }}
                  onSelectDefinition={(definition) => {
                    setActiveWorkflowDefinitionId(definition.id);
                  }}
                  onOpenDefinition={(definition) => {
                    router.push(`/studio?definition=${encodeURIComponent(definition.id)}`);
                  }}
                  onDeleteDefinition={(definition) => {
                    deleteDefinitionMutation.mutate(definition);
                  }}
                  openDefinitionLabel="Open In Studio"
                  deletingWorkflowVersionId={
                    deleteVersionMutation.isPending ? deleteVersionMutation.variables?.id ?? null : null
                  }
                  onSelectVersion={(version) => {
                    setActiveWorkflowVersionId(version.id);
                  }}
                  onOpenVersion={(version) => {
                    router.push(
                      `/studio?definition=${encodeURIComponent(version.definition_id)}&version=${encodeURIComponent(version.id)}`
                    );
                  }}
                  onDeleteVersion={(version) => {
                    deleteVersionMutation.mutate(version);
                  }}
                  openVersionLabel="Open Version"
                  onCreateManualTrigger={() => {
                    createManualTriggerMutation.mutate();
                  }}
                  onInvokeTrigger={(trigger) => {
                    invokeTriggerMutation.mutate(trigger);
                  }}
                />
              </div>
      </section>
    </>
  );
}
