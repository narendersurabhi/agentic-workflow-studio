"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import Button from "../../components/ui/Button";
import Input from "../../components/ui/Input";
import Textarea from "../../components/ui/Textarea";
import { LLM_PROVIDERS, modelsForProvider } from "../../lib/llmProviders";
import StudioWorkbenchIcon from "./StudioWorkbenchIcon";
import {
  createAgentDefinition,
  deleteAgentDefinition,
  fetchAgentDefinitionVersions,
  fetchAgentDefinitions,
  fetchCapabilityCatalog,
  fetchRunDebugger,
  launchAgentRun,
  launchCapabilityRun,
  publishAgentDefinitionVersion,
  searchCapabilities,
  updateAgentDefinition,
  type WorkbenchDebuggerData,
  type WorkbenchRunLaunchResponse,
} from "./studioApi";
import { studioWorkbenchKeys } from "./studioWorkbenchQueries";
import { mapDebuggerStepToReplayDraft, mapRunToWorkbenchFork, mapRunToWorkflowPromotion } from "./studioWorkbenchMappings";
import type {
  AgentDefinition,
  AgentDefinitionCreateRequest,
  AgentDefinitionVersion,
  CapabilityItem,
  ReplayableCapabilityDraft,
  StudioSurface,
  WorkbenchWorkflowPromotionDraft,
} from "./types";

type WorkbenchMode = "capability" | "agent";
type AgentStepRole = "agent" | "step";

type CapabilityInputDraft = Record<string, string | boolean>;

type AgentStepDraft = {
  localId: string;
  stepId: string;
  name: string;
  description: string;
  instruction: string;
  capabilityId: string;
  dependsOnText: string;
  inputDraft: CapabilityInputDraft;
  rawInputOverrideEnabled: boolean;
  inputJsonText: string;
  retryPolicyText: string;
};

const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "canceled", "accepted", "completed"]);
const DEFAULT_AGENT_CAPABILITY_ID = "codegen.autonomous";
const AGENT_RUN_CAPABILITY_ID = "agent.run";
const DEFAULT_AGENT_WORKSPACE_PATH = "workbench-agent";
const DEFAULT_AGENT_MAX_STEPS = "6";

const DEFAULT_RETRY_POLICY_PREVIEW = {
  max_attempts: 1,
  retry_class: "standard",
  retryable_errors: [],
  backoff_seconds: 0,
  backoff_multiplier: 1,
  jitter_seconds: 0,
};

type WorkbenchBanner = {
  tone: "info" | "warning";
  message: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function parseJsonObject(
  text: string,
  label: string,
  fallback: Record<string, unknown> = {}
): { value: Record<string, unknown> | null; error: string | null } {
  const normalized = text.trim();
  if (!normalized) {
    return { value: fallback, error: null };
  }
  try {
    const parsed = JSON.parse(normalized);
    if (!isRecord(parsed)) {
      return { value: null, error: `${label} must be a JSON object.` };
    }
    return { value: parsed, error: null };
  } catch (error) {
    return {
      value: null,
      error: error instanceof Error ? `${label}: ${error.message}` : `${label} is invalid JSON.`,
    };
  }
}

function slugify(value: string, fallback: string): string {
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return normalized || fallback;
}

function defaultAgentInputDraft(capabilityId: string): CapabilityInputDraft {
  if (capabilityId === DEFAULT_AGENT_CAPABILITY_ID) {
    return {
      workspace_path: DEFAULT_AGENT_WORKSPACE_PATH,
      max_steps: DEFAULT_AGENT_MAX_STEPS,
    };
  }
  if (isAgentRunCapability(capabilityId)) {
    return { max_steps: DEFAULT_AGENT_MAX_STEPS };
  }
  return {};
}

function defaultStepName(capabilityId: string, role: AgentStepRole): string {
  if (!capabilityId) {
    return "";
  }
  if (role === "agent") {
    return "Agent";
  }
  return capabilityId;
}

function defaultStepDescription(capabilityId: string, role: AgentStepRole): string {
  if (!capabilityId) {
    return "";
  }
  if (role === "agent") {
    return "Autonomous agent for the primary workbench task.";
  }
  return `Workbench step for ${capabilityId}`;
}

function defaultStepInstruction(capabilityId: string, role: AgentStepRole): string {
  if (!capabilityId) {
    return "";
  }
  if (role === "agent") {
    return "Plan and execute the requested task in the selected workspace.";
  }
  return `Run ${capabilityId} with the provided inputs.`;
}

function isAgenticCapability(item: CapabilityItem): boolean {
  const id = item.id.toLowerCase();
  const tags = item.tags.map((tag) => tag.toLowerCase());
  return (
    id === DEFAULT_AGENT_CAPABILITY_ID ||
    id === AGENT_RUN_CAPABILITY_ID ||
    id.includes(".autonomous") ||
    tags.includes("autonomous") ||
    tags.includes("coding-agent") ||
    tags.includes("loop")
  );
}

function isAgentRunCapability(capabilityId: string): boolean {
  return capabilityId.trim() === AGENT_RUN_CAPABILITY_ID;
}

function stringInputValue(inputDraft: CapabilityInputDraft, key: string): string {
  const value = inputDraft[key];
  return typeof value === "string" ? value : "";
}

function normalizeSchemaType(schema: Record<string, unknown> | undefined): string {
  const type = schema?.type;
  if (typeof type === "string") {
    return type;
  }
  if (Array.isArray(type)) {
    const firstString = type.find((item) => typeof item === "string");
    return typeof firstString === "string" ? firstString : "string";
  }
  return "string";
}

function getCapabilitySchemaProperties(
  capability: CapabilityItem | null
): [string, Record<string, unknown>][] {
  const rawProperties = capability?.input_schema?.properties;
  return isRecord(rawProperties)
    ? Object.entries(rawProperties).filter((entry): entry is [string, Record<string, unknown>] =>
        isRecord(entry[1])
      )
    : [];
}

function buildStructuredCapabilityInputs(
  capability: CapabilityItem | null,
  inputDraft: CapabilityInputDraft,
  labelPrefix = "Input"
): { value: Record<string, unknown> | null; error: string | null } {
  if (!capability) {
    return { value: null, error: "Choose a capability to configure its inputs." };
  }
  const schemaProperties = getCapabilitySchemaProperties(capability);
  const nextInputs: Record<string, unknown> = {};
  const requiredFields = new Set(capability.required_inputs ?? []);
  for (const [fieldName, schema] of schemaProperties) {
    const rawValue = inputDraft[fieldName];
    const fieldType = normalizeSchemaType(schema);
    const required = requiredFields.has(fieldName);

    if (fieldType === "boolean") {
      if (typeof rawValue === "boolean") {
        nextInputs[fieldName] = rawValue;
      } else if (required) {
        nextInputs[fieldName] = false;
      }
      continue;
    }

    const rawText = typeof rawValue === "string" ? rawValue : "";
    if (!rawText.trim()) {
      if (required) {
        return { value: null, error: `${labelPrefix} '${fieldName}' is required.` };
      }
      continue;
    }

    if (fieldType === "integer" || fieldType === "number") {
      const parsedNumber = Number(rawText);
      if (Number.isNaN(parsedNumber)) {
        return { value: null, error: `${labelPrefix} '${fieldName}' must be a number.` };
      }
      nextInputs[fieldName] = fieldType === "integer" ? Math.trunc(parsedNumber) : parsedNumber;
      continue;
    }

    if (fieldType === "object" || fieldType === "array") {
      try {
        nextInputs[fieldName] = JSON.parse(rawText);
      } catch (error) {
        return {
          value: null,
          error:
            error instanceof Error
              ? `${labelPrefix} '${fieldName}' is invalid JSON: ${error.message}`
              : `${labelPrefix} '${fieldName}' is invalid JSON.`,
        };
      }
      continue;
    }

    nextInputs[fieldName] = rawText;
  }
  return { value: nextInputs, error: null };
}

function splitDependencyList(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitConstraintList(value: string): string[] {
  return value
    .split(/\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function createAgentProfileInputDraft(
  definition: AgentDefinition | AgentDefinitionVersion
): CapabilityInputDraft {
  const inputDraft: CapabilityInputDraft = {};
  if (definition.default_goal.trim()) {
    inputDraft.goal = definition.default_goal;
  }
  const agentCapId = definition.agent_capability_id || DEFAULT_AGENT_CAPABILITY_ID;
  const workspacePath =
    isAgentRunCapability(agentCapId)
      ? ""
      : definition.default_workspace_path?.trim() ||
        (agentCapId === DEFAULT_AGENT_CAPABILITY_ID ? DEFAULT_AGENT_WORKSPACE_PATH : "");
  if (workspacePath) {
    inputDraft.workspace_path = workspacePath;
  }
  if (definition.default_constraints.length > 0) {
    inputDraft.constraints = definition.default_constraints.join("\n");
  }
  const maxSteps =
    definition.default_max_steps ??
    (agentCapId === DEFAULT_AGENT_CAPABILITY_ID || isAgentRunCapability(agentCapId)
      ? Number(DEFAULT_AGENT_MAX_STEPS)
      : null);
  if (maxSteps !== null) {
    inputDraft.max_steps = String(maxSteps);
  }
  return inputDraft;
}

function createAgentStepDraft(capabilityId = "", role: AgentStepRole = "step"): AgentStepDraft {
  const baseId =
    role === "agent"
      ? "agent"
      : slugify(capabilityId || `step_${Date.now()}`, "step");
  return {
    localId: `agent-step-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    stepId: baseId,
    name: defaultStepName(capabilityId, role),
    description: defaultStepDescription(capabilityId, role),
    instruction: defaultStepInstruction(capabilityId, role),
    capabilityId,
    dependsOnText: "",
    inputDraft: role === "agent" ? defaultAgentInputDraft(capabilityId) : {},
    rawInputOverrideEnabled: false,
    inputJsonText: "{\n  \n}",
    retryPolicyText: "",
  };
}

function createAgentStepDraftFromDefinition(
  definition: AgentDefinition | AgentDefinitionVersion
): AgentStepDraft {
  const capabilityId = definition.agent_capability_id || DEFAULT_AGENT_CAPABILITY_ID;
  const inputDraft = createAgentProfileInputDraft(definition);
  const draft = createAgentStepDraft(capabilityId, "agent");
  return {
    ...draft,
    name: "Agent",
    description: definition.description?.trim() || defaultStepDescription(capabilityId, "agent"),
    instruction: definition.instructions || defaultStepInstruction(capabilityId, "agent"),
    inputDraft,
    rawInputOverrideEnabled: false,
    inputJsonText: formatJson(inputDraft),
  };
}

function sortAgentDefinitions(definitions: AgentDefinition[]): AgentDefinition[] {
  return [...definitions].sort((left, right) => right.updated_at.localeCompare(left.updated_at));
}

function sortAgentDefinitionVersions(
  versions: AgentDefinitionVersion[]
): AgentDefinitionVersion[] {
  return [...versions].sort((left, right) => right.version_number - left.version_number);
}

function buildCapabilityRunSpecPreview(
  capabilityId: string,
  inputs: Record<string, unknown>,
  retryPolicy?: Record<string, unknown> | null
): Record<string, unknown> {
  const stepId = slugify(capabilityId, "capability_step");
  const resolvedRetryPolicy =
    retryPolicy && Object.keys(retryPolicy).length > 0 ? retryPolicy : DEFAULT_RETRY_POLICY_PREVIEW;
  return {
    version: "1",
    kind: "api",
    planner_version: "workbench_v1",
    tasks_summary: `Workbench capability run: ${capabilityId}`,
    steps: [
      {
        step_id: stepId,
        name: stepId,
        description: `Capability sandbox run for ${capabilityId}`,
        instruction: `Execute capability ${capabilityId}.`,
        capability_request: {
          request_id: capabilityId,
          capability_id: capabilityId,
          execution_request_id: capabilityId,
        },
        input_bindings: inputs,
        retry_policy: resolvedRetryPolicy,
        acceptance_policy: {
          acceptance_criteria: [],
          critic_required: false,
        },
        depends_on: [],
      },
    ],
    dag_edges: [],
    capability_requests: [
      {
        request_id: capabilityId,
        capability_id: capabilityId,
        execution_request_id: capabilityId,
      },
    ],
    metadata: {
      surface: "studio_workbench",
      workbench_mode: "capability",
      ephemeral: true,
    },
  };
}

function collectArtifacts(debuggerData: WorkbenchDebuggerData | null): Record<string, unknown>[] {
  if (!debuggerData) {
    return [];
  }
  const artifacts: Record<string, unknown>[] = [];
  for (const step of debuggerData.steps) {
    const stepArtifacts = step.latest_result?.artifacts;
    if (!Array.isArray(stepArtifacts)) {
      continue;
    }
    for (const artifact of stepArtifacts) {
      if (isRecord(artifact)) {
        artifacts.push(artifact);
      }
    }
  }
  return artifacts;
}

function capabilityEditorStateFromInputs(
  capability: CapabilityItem | null,
  inputs: Record<string, unknown>
): {
  inputDraft: CapabilityInputDraft;
  rawOverrideEnabled: boolean;
  rawOverrideText: string;
} {
  const rawOverrideText = formatJson(inputs);
  if (!capability) {
    return {
      inputDraft: {},
      rawOverrideEnabled: true,
      rawOverrideText,
    };
  }
  const properties = capability.input_schema?.properties;
  if (!isRecord(properties)) {
    return {
      inputDraft: {},
      rawOverrideEnabled: true,
      rawOverrideText,
    };
  }
  const schemaEntries = Object.entries(properties).filter((entry): entry is [string, Record<string, unknown>] =>
    isRecord(entry[1])
  );
  if (schemaEntries.length === 0) {
    return {
      inputDraft: {},
      rawOverrideEnabled: Object.keys(inputs).length > 0,
      rawOverrideText,
    };
  }
  const structuredDraft: CapabilityInputDraft = {};
  let requiresRawOverride = false;
  const knownFieldNames = new Set(schemaEntries.map(([fieldName]) => fieldName));
  Object.keys(inputs).forEach((fieldName) => {
    if (!knownFieldNames.has(fieldName)) {
      requiresRawOverride = true;
    }
  });
  schemaEntries.forEach(([fieldName, schema]) => {
    const value = inputs[fieldName];
    if (value === undefined) {
      return;
    }
    const fieldType = normalizeSchemaType(schema);
    if (fieldType === "boolean") {
      if (typeof value === "boolean") {
        structuredDraft[fieldName] = value;
        return;
      }
      if (typeof value === "string" && (value === "true" || value === "false")) {
        structuredDraft[fieldName] = value === "true";
        return;
      }
      requiresRawOverride = true;
      return;
    }
    if (fieldType === "object" || fieldType === "array") {
      if (typeof value === "string") {
        structuredDraft[fieldName] = value;
        return;
      }
      if (Array.isArray(value) || isRecord(value)) {
        structuredDraft[fieldName] = formatJson(value);
        return;
      }
      requiresRawOverride = true;
      return;
    }
    if (fieldType === "integer" || fieldType === "number") {
      if (typeof value === "number" || typeof value === "string") {
        structuredDraft[fieldName] = String(value);
        return;
      }
      requiresRawOverride = true;
      return;
    }
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      structuredDraft[fieldName] = String(value);
      return;
    }
    requiresRawOverride = true;
  });
  return {
    inputDraft: structuredDraft,
    rawOverrideEnabled: requiresRawOverride,
    rawOverrideText,
  };
}

function SurfacePanel({
  title,
  subtitle,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-[24px] border border-subtle bg-gradient-panel-deep p-4 shadow-[0_16px_34px_rgba(15,23,42,0.18)] ${className}`.trim()}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-text-sky-token">
            {title}
          </div>
          {subtitle ? <p className="mt-1 text-xs leading-5 text-text-md">{subtitle}</p> : null}
        </div>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

type WorkbenchDebugPanelId =
  | "run_spec"
  | "predicted_execution_request"
  | "capability_input_schema"
  | "capability_output_schema"
  | "retry_policy"
  | "initial_execution_request"
  | "execution_requests"
  | "attempts"
  | "artifacts"
  | "timeline";

function JsonPreview({
  title,
  value,
  emptyLabel,
}: {
  title: string;
  value: unknown;
  emptyLabel: string;
}) {
  const isEmpty =
    value == null ||
    (Array.isArray(value) && value.length === 0) ||
    (isRecord(value) && Object.keys(value).length === 0);
  return (
    <div className="rounded-2xl border border-white/8 bg-black/20 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-md">
        {title}
      </div>
      {isEmpty ? (
        <div className="mt-2 text-xs text-text-lo">{emptyLabel}</div>
      ) : (
        <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-xl border border-white/8 bg-slate-950/55 p-3 text-[11px] leading-5 text-text-hi">
          {formatJson(value)}
        </pre>
      )}
    </div>
  );
}

function WorkbenchTitleField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs text-text-md">
      <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">Title</span>
      <Input value={value} onChange={(event) => onChange(event.target.value)} className="bg-slate-950/45" />
    </label>
  );
}

function WorkbenchUserIdField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs text-text-md">
      <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">User Id</span>
      <Input value={value} onChange={(event) => onChange(event.target.value)} className="bg-slate-950/45" />
    </label>
  );
}

function WorkbenchContextJsonField({
  value,
  onChange,
  className = "block text-xs text-text-md",
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <label className={className}>
      <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">Context JSON</span>
      <Textarea
        rows={5}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-2xl bg-slate-950/45 py-3 font-mono text-[12px]"
      />
    </label>
  );
}

const workbenchSelectClassName =
  "w-full rounded-xl border border-subtle bg-slate-950/45 px-3 py-2 text-sm text-text-hi outline-none transition focus:border-sky-300/35";

function WorkbenchLlmModelFields({
  provider,
  model,
  onProviderChange,
  onModelChange,
  unsetLabel,
}: {
  provider: string;
  model: string;
  onProviderChange: (value: string) => void;
  onModelChange: (value: string) => void;
  unsetLabel: string;
}) {
  const models = modelsForProvider(provider);
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <label className="text-xs text-text-md">
        <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">Provider</span>
        <select
          value={provider}
          onChange={(event) => {
            onProviderChange(event.target.value);
            onModelChange("");
          }}
          className={workbenchSelectClassName}
        >
          {LLM_PROVIDERS.map((option) => (
            <option key={`llm-provider-${option.value || "default"}`} value={option.value}>
              {option.value ? option.label : unsetLabel}
            </option>
          ))}
        </select>
      </label>
      {models.length > 0 ? (
        <label className="text-xs text-text-md">
          <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">Model</span>
          <select value={model} onChange={(event) => onModelChange(event.target.value)} className={workbenchSelectClassName}>
            <option value="">Provider default</option>
            {models.map((modelOption) => (
              <option key={`llm-model-${modelOption}`} value={modelOption}>
                {modelOption}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </div>
  );
}

export default function StudioWorkbenchSurface({
  active,
  workspaceUserId,
  onPromoteWorkflowDraft,
}: {
  active: boolean;
  workspaceUserId: string;
  onPromoteWorkflowDraft?: (draft: WorkbenchWorkflowPromotionDraft) => void;
}) {
  const queryClient = useQueryClient();
  const [workbenchMode, setWorkbenchMode] = useState<WorkbenchMode>("agent");
  const [catalogCollapsed, setCatalogCollapsed] = useState(false);
  const [showDebugData, setShowDebugData] = useState(false);
  const [activeDebugPanelId, setActiveDebugPanelId] = useState<WorkbenchDebugPanelId>("run_spec");
  const [confirmDeleteProfile, setConfirmDeleteProfile] = useState(false);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState("all");
  const [idempotencyFilter, setIdempotencyFilter] = useState("all");
  const [selectedCapabilityId, setSelectedCapabilityId] = useState("");
  const [capabilityTitle, setCapabilityTitle] = useState("Capability workbench run");
  const [capabilityGoal, setCapabilityGoal] = useState("");
  const [capabilityUserId, setCapabilityUserId] = useState(workspaceUserId);
  const [capabilityContextJsonText, setCapabilityContextJsonText] = useState("{\n  \n}");
  const [capabilityRetryPolicyText, setCapabilityRetryPolicyText] = useState("");
  const [capabilityInputDraft, setCapabilityInputDraft] = useState<CapabilityInputDraft>({});
  const [capabilityRawOverrideEnabled, setCapabilityRawOverrideEnabled] = useState(false);
  const [capabilityRawOverrideText, setCapabilityRawOverrideText] = useState("{\n  \n}");
  const [agentTitle, setAgentTitle] = useState("Agent workbench run");
  const [agentGoal, setAgentGoal] = useState("");
  const [agentUserId, setAgentUserId] = useState(workspaceUserId);
  const [agentSteps, setAgentSteps] = useState<AgentStepDraft[]>([
    createAgentStepDraft(DEFAULT_AGENT_CAPABILITY_ID, "agent"),
  ]);
  const [agentAllowedCapabilityIds, setAgentAllowedCapabilityIds] = useState<string[]>([]);
  const [toolPickerQuery, setToolPickerQuery] = useState("");
  const [toolPickerOpen, setToolPickerOpen] = useState(false);
  const toolPickerInputRef = useRef<HTMLInputElement>(null);
  const [selectedAgentDefinitionId, setSelectedAgentDefinitionId] = useState("");
  const [selectedAgentDefinitionVersionId, setSelectedAgentDefinitionVersionId] = useState("");
  const [agentProfileVersionNote, setAgentProfileVersionNote] = useState("");
  const [agentProfileName, setAgentProfileName] = useState("");
  const [agentProfileDescription, setAgentProfileDescription] = useState("");
  const [agentInstructions, setAgentInstructions] = useState("");
  const [agentLlmProvider, setAgentLlmProvider] = useState("");
  const [agentLlmModel, setAgentLlmModel] = useState("");
  const [runLlmProvider, setRunLlmProvider] = useState("");
  const [runLlmModel, setRunLlmModel] = useState("");
  const [agentProfileError, setAgentProfileError] = useState<string | null>(null);
  const [agentProfileSaving, setAgentProfileSaving] = useState(false);
  const [agentProfilePublishing, setAgentProfilePublishing] = useState(false);
  const [agentProfileDeleting, setAgentProfileDeleting] = useState(false);
  const [launchLoading, setLaunchLoading] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launchResponse, setLaunchResponse] = useState<WorkbenchRunLaunchResponse | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [workbenchBanner, setWorkbenchBanner] = useState<WorkbenchBanner | null>(null);

  const deferredCatalogQuery = useDeferredValue(catalogQuery);

  useEffect(() => {
    if (!capabilityUserId.trim() && workspaceUserId.trim()) {
      setCapabilityUserId(workspaceUserId);
    }
  }, [capabilityUserId, workspaceUserId]);

  useEffect(() => {
    if (!agentUserId.trim() && workspaceUserId.trim()) {
      setAgentUserId(workspaceUserId);
    }
  }, [agentUserId, workspaceUserId]);

  useEffect(() => {
    setConfirmDeleteProfile(false);
  }, [selectedAgentDefinitionId]);

  const catalogQueryResult = useQuery({
    queryKey: studioWorkbenchKeys.capabilityCatalog(),
    queryFn: () => fetchCapabilityCatalog(true),
  });
  const catalog = useMemo(() => catalogQueryResult.data?.items ?? [], [catalogQueryResult.data]);
  const catalogLoading = catalogQueryResult.isLoading;
  const catalogError =
    catalogQueryResult.error instanceof Error ? catalogQueryResult.error.message : null;

  useEffect(() => {
    const items = catalogQueryResult.data?.items;
    if (!items) {
      return;
    }
    setSelectedCapabilityId((current) => current || items[0]?.id || "");
    const agentRunInCatalog = items.some((item) => item.id === AGENT_RUN_CAPABILITY_ID);
    if (agentRunInCatalog) {
      setAgentSteps((current) => {
        if (current.length === 1 && current[0].capabilityId === DEFAULT_AGENT_CAPABILITY_ID) {
          return [createAgentStepDraft(AGENT_RUN_CAPABILITY_ID, "agent")];
        }
        return current;
      });
    }
  }, [catalogQueryResult.data]);

  const agentDefinitionsQueryResult = useQuery({
    queryKey: studioWorkbenchKeys.agentDefinitions(workspaceUserId),
    queryFn: () => fetchAgentDefinitions(workspaceUserId.trim() || undefined),
  });
  const agentDefinitions = useMemo(
    () => sortAgentDefinitions(agentDefinitionsQueryResult.data ?? []),
    [agentDefinitionsQueryResult.data]
  );
  const agentDefinitionsLoading = agentDefinitionsQueryResult.isLoading;
  const agentDefinitionsError =
    agentDefinitionsQueryResult.error instanceof Error
      ? agentDefinitionsQueryResult.error.message
      : null;

  const agentDefinitionVersionsQueryResult = useQuery({
    queryKey: studioWorkbenchKeys.agentDefinitionVersions(selectedAgentDefinitionId),
    queryFn: () => fetchAgentDefinitionVersions(selectedAgentDefinitionId),
    enabled: Boolean(selectedAgentDefinitionId),
  });
  const agentDefinitionVersions = useMemo(
    () =>
      selectedAgentDefinitionId
        ? sortAgentDefinitionVersions(agentDefinitionVersionsQueryResult.data ?? [])
        : [],
    [selectedAgentDefinitionId, agentDefinitionVersionsQueryResult.data]
  );
  const agentDefinitionVersionsLoading = agentDefinitionVersionsQueryResult.isLoading;
  const agentDefinitionVersionsError =
    agentDefinitionVersionsQueryResult.error instanceof Error
      ? agentDefinitionVersionsQueryResult.error.message
      : null;

  useEffect(() => {
    if (!selectedAgentDefinitionId) {
      setSelectedAgentDefinitionVersionId("");
      return;
    }
    setSelectedAgentDefinitionVersionId((current) =>
      agentDefinitionVersions.some((version) => version.id === current) ? current : ""
    );
  }, [selectedAgentDefinitionId, agentDefinitionVersions]);

  const trimmedCatalogQuery = deferredCatalogQuery.trim();
  const catalogSearchQueryResult = useQuery({
    queryKey: studioWorkbenchKeys.capabilitySearch(trimmedCatalogQuery),
    queryFn: () => searchCapabilities(trimmedCatalogQuery, 12),
    enabled: Boolean(trimmedCatalogQuery),
  });
  const catalogSearchItems = useMemo(
    () => (trimmedCatalogQuery ? catalogSearchQueryResult.data?.items ?? [] : []),
    [trimmedCatalogQuery, catalogSearchQueryResult.data]
  );
  const catalogSearchLoading = trimmedCatalogQuery ? catalogSearchQueryResult.isLoading : false;
  const catalogSearchError = trimmedCatalogQuery
    ? catalogSearchQueryResult.error instanceof Error
      ? catalogSearchQueryResult.error.message
      : null
    : null;

  const selectedCapability = useMemo(
    () => catalog.find((item) => item.id === selectedCapabilityId) ?? null,
    [catalog, selectedCapabilityId]
  );

  const agentCapabilities = useMemo(
    () => catalog.filter(isAgenticCapability),
    [catalog]
  );

  const primaryAgentStep = agentSteps[0] ?? null;

  const primaryAgentCapability = useMemo(
    () =>
      primaryAgentStep
        ? catalog.find((item) => item.id === primaryAgentStep.capabilityId) ?? null
        : null,
    [catalog, primaryAgentStep]
  );

  const selectedAgentDefinition = useMemo(
    () => agentDefinitions.find((definition) => definition.id === selectedAgentDefinitionId) ?? null,
    [agentDefinitions, selectedAgentDefinitionId]
  );

  const selectedAgentDefinitionVersion = useMemo(
    () =>
      agentDefinitionVersions.find(
        (version) => version.id === selectedAgentDefinitionVersionId
      ) ?? null,
    [agentDefinitionVersions, selectedAgentDefinitionVersionId]
  );

  const groupOptions = useMemo(
    () =>
      Array.from(new Set(catalog.map((item) => item.group || "").filter(Boolean))).sort((a, b) =>
        a.localeCompare(b)
      ),
    [catalog]
  );

  const riskOptions = useMemo(
    () =>
      Array.from(new Set(catalog.map((item) => item.risk_tier).filter(Boolean))).sort((a, b) =>
        a.localeCompare(b)
      ),
    [catalog]
  );

  const idempotencyOptions = useMemo(
    () =>
      Array.from(new Set(catalog.map((item) => item.idempotency).filter(Boolean))).sort((a, b) =>
        a.localeCompare(b)
      ),
    [catalog]
  );

  const filteredCatalog = useMemo(() => {
    const normalizedQuery = deferredCatalogQuery.trim();
    const searchRank = new Map(catalogSearchItems.map((item, index) => [item.id, index]));
    return catalog
      .filter((item) => (groupFilter === "all" ? true : item.group === groupFilter))
      .filter((item) => (riskFilter === "all" ? true : item.risk_tier === riskFilter))
      .filter((item) => (idempotencyFilter === "all" ? true : item.idempotency === idempotencyFilter))
      .filter((item) => {
        if (!normalizedQuery) {
          return true;
        }
        return searchRank.has(item.id);
      })
      .sort((left, right) => {
        if (normalizedQuery) {
          return (searchRank.get(left.id) ?? Number.MAX_SAFE_INTEGER) -
            (searchRank.get(right.id) ?? Number.MAX_SAFE_INTEGER);
        }
        return left.id.localeCompare(right.id);
      });
  }, [catalog, catalogSearchItems, deferredCatalogQuery, groupFilter, idempotencyFilter, riskFilter]);

  const capabilitySchemaProperties = useMemo(() => {
    return getCapabilitySchemaProperties(selectedCapability);
  }, [selectedCapability]);

  const capabilityStructuredInputs = useMemo(() => {
    return buildStructuredCapabilityInputs(selectedCapability, capabilityInputDraft);
  }, [capabilityInputDraft, selectedCapability]);

  const capabilityRawInputs = useMemo(
    () => parseJsonObject(capabilityRawOverrideText, "Capability raw inputs"),
    [capabilityRawOverrideText]
  );

  const capabilityContextJson = useMemo(
    () => parseJsonObject(capabilityContextJsonText, "Capability context JSON"),
    [capabilityContextJsonText]
  );

  const capabilityRetryPolicy = useMemo(
    () => parseJsonObject(capabilityRetryPolicyText, "Retry policy"),
    [capabilityRetryPolicyText]
  );

  const capabilityLaunchInputs = useMemo(() => {
    if (capabilityRawOverrideEnabled) {
      return capabilityRawInputs;
    }
    return capabilityStructuredInputs;
  }, [capabilityRawInputs, capabilityRawOverrideEnabled, capabilityStructuredInputs]);

  const capabilityRunSpecPreview = useMemo(() => {
    if (!selectedCapability || !capabilityLaunchInputs.value) {
      return null;
    }
    return buildCapabilityRunSpecPreview(
      selectedCapability.id,
      capabilityLaunchInputs.value,
      capabilityRetryPolicy.value
    );
  }, [capabilityLaunchInputs.value, capabilityRetryPolicy.value, selectedCapability]);

  const agentRunSpecPreview = useMemo(() => {
    const normalizedTitle = agentTitle.trim() || "Agent workbench run";
    const step = agentSteps[0];
    const normalizedGoal = agentGoal.trim() || stringInputValue(step?.inputDraft ?? {}, "goal").trim();
    if (!step) {
      return { value: null, error: "The agent's primary step is missing." };
    }
    const capabilityId = step.capabilityId.trim();
    if (!capabilityId) {
      return { value: null, error: "Choose an agent capability before launching a run." };
    }
    const stepId = slugify(step.stepId || step.name || capabilityId, "agent");
    const stepCapability = catalog.find((item) => item.id === capabilityId) ?? null;
    const parsedInputs =
      step.rawInputOverrideEnabled || !stepCapability
        ? parseJsonObject(step.inputJsonText, `Inputs for step '${step.name || stepId}'`)
        : buildStructuredCapabilityInputs(
            stepCapability,
            step.inputDraft,
            `Input for step '${step.name || stepId}'`
          );
    if (!parsedInputs.value) {
      return parsedInputs;
    }
    const capabilityRequest = {
      request_id: capabilityId,
      capability_id: capabilityId,
      execution_request_id: capabilityId,
    };
    const stepIsAgentic = stepCapability
      ? isAgenticCapability(stepCapability)
      : capabilityId.includes(".autonomous");
    const stepIntent = stepIsAgentic ? "generate" : undefined;
    // provider+model are inherited as one atomic pair -- run-level override wins
    // wholesale if set, otherwise fall through to the definition-level pair.
    // Never mix a provider from one source with a model from the other; a model
    // name only makes sense paired with the provider it belongs to.
    const [effectiveLlmProvider, effectiveLlmModel] = runLlmProvider.trim()
      ? [runLlmProvider.trim(), runLlmModel.trim()]
      : [agentLlmProvider.trim(), agentLlmModel.trim()];
    return {
      value: {
        version: "1",
        kind: "api",
        planner_version: "workbench_v1",
        tasks_summary: normalizedGoal || normalizedTitle,
        steps: [
          {
            step_id: stepId,
            name: step.name.trim() || stepId,
            description: step.description.trim() || `Workbench step for ${capabilityId}`,
            instruction: step.instruction.trim() || `Execute capability ${capabilityId}.`,
            ...(stepIntent ? { intent: stepIntent } : {}),
            capability_request: capabilityRequest,
            input_bindings: isAgentRunCapability(capabilityId)
              ? {
                  ...parsedInputs.value,
                  ...(agentInstructions.trim() ? { instructions: agentInstructions.trim() } : {}),
                  ...(agentAllowedCapabilityIds.length > 0
                    ? { allowed_capability_ids: agentAllowedCapabilityIds }
                    : {}),
                  ...(effectiveLlmProvider
                    ? {
                        provider: effectiveLlmProvider,
                        ...(effectiveLlmModel ? { model: effectiveLlmModel } : {}),
                      }
                    : {}),
                }
              : parsedInputs.value,
            retry_policy: DEFAULT_RETRY_POLICY_PREVIEW,
            acceptance_policy: {
              acceptance_criteria: [],
              critic_required: false,
            },
            depends_on: [],
          },
        ],
        dag_edges: [],
        capability_requests: [capabilityRequest],
        metadata: {
          surface: "studio_workbench",
          workbench_mode: "agent",
          ephemeral: true,
        },
      },
      error: null,
    };
  }, [
    agentAllowedCapabilityIds,
    agentGoal,
    agentInstructions,
    agentLlmModel,
    agentLlmProvider,
    agentSteps,
    agentTitle,
    catalog,
    runLlmModel,
    runLlmProvider,
  ]);

  const predictedExecutionRequestPreview = useMemo(() => {
    const previewValue =
      workbenchMode === "capability" ? capabilityRunSpecPreview : agentRunSpecPreview.value;
    if (!isRecord(previewValue)) {
      return null;
    }
    const steps = previewValue.steps;
    if (!Array.isArray(steps) || steps.length === 0 || !isRecord(steps[0])) {
      return null;
    }
    const firstStep = steps[0];
    const capabilityRequest = isRecord(firstStep.capability_request) ? firstStep.capability_request : {};
    const contextPreview = workbenchMode === "capability" ? capabilityContextJson.value : {};
    return {
      step_id: firstStep.step_id,
      request_id: capabilityRequest.execution_request_id ?? capabilityRequest.request_id,
      capability_id: capabilityRequest.capability_id,
      attempt_number: 1,
      status: "prepared",
      request: {
        requests: [
          {
            request_id: capabilityRequest.execution_request_id ?? capabilityRequest.request_id,
            capability_binding: {
              capability_id: capabilityRequest.capability_id,
            },
            input: firstStep.input_bindings ?? {},
          },
        ],
      },
      retry_policy: firstStep.retry_policy ?? {},
      policy_snapshot: firstStep.acceptance_policy ?? {},
      context_provenance: {
        job_context_keys: contextPreview ? Object.keys(contextPreview) : [],
      },
    };
  }, [
    agentRunSpecPreview.value,
    capabilityContextJson.value,
    capabilityRunSpecPreview,
    workbenchMode,
  ]);

  const debuggerQueryResult = useQuery({
    queryKey: studioWorkbenchKeys.runDebugger(activeRunId ?? ""),
    queryFn: () => fetchRunDebugger(activeRunId as string),
    enabled: Boolean(active && activeRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.run?.status;
      return status && TERMINAL_RUN_STATUSES.has(status) ? false : 2500;
    },
  });
  const debuggerData = activeRunId ? debuggerQueryResult.data ?? null : null;
  const debuggerLoading = debuggerQueryResult.isLoading;
  const debuggerError =
    debuggerQueryResult.error instanceof Error ? debuggerQueryResult.error.message : null;

  const currentRunStatus =
    debuggerData?.run?.status ||
    launchResponse?.run?.status ||
    null;

  const replayResultsByStep = useMemo(() => {
    const next = new Map<string, ReturnType<typeof mapDebuggerStepToReplayDraft>>();
    if (!debuggerData) {
      return next;
    }
    debuggerData.steps.forEach((stepPayload) => {
      next.set(stepPayload.step.id, mapDebuggerStepToReplayDraft(debuggerData, stepPayload.step.id));
    });
    return next;
  }, [debuggerData]);

  const forkResult = useMemo(
    () => (debuggerData ? mapRunToWorkbenchFork(debuggerData) : null),
    [debuggerData]
  );

  const workflowPromotionResult = useMemo(
    () => (debuggerData ? mapRunToWorkflowPromotion(debuggerData) : null),
    [debuggerData]
  );

  const applyAgentDefinitionDraft = (definition: AgentDefinition) => {
    const primaryStep = createAgentStepDraftFromDefinition(definition);
    setWorkbenchMode("agent");
    setSelectedAgentDefinitionId(definition.id);
    setSelectedAgentDefinitionVersionId("");
    setAgentProfileName(definition.name);
    setAgentProfileDescription(definition.description ?? "");
    setAgentInstructions(definition.instructions || "");
    setAgentLlmProvider(typeof definition.model_config?.provider === "string" ? definition.model_config.provider : "");
    setAgentLlmModel(typeof definition.model_config?.model === "string" ? definition.model_config.model : "");
    setRunLlmProvider("");
    setRunLlmModel("");
    setAgentTitle(definition.name || "Agent workbench run");
    setAgentGoal(definition.default_goal || "");
    setAgentUserId(definition.user_id || workspaceUserId);
    setAgentSteps([primaryStep]);
    setAgentAllowedCapabilityIds(definition.allowed_capability_ids ?? []);
    setAgentProfileError(null);
    setLaunchError(null);
    setWorkbenchBanner({
      tone: "info",
      message: `Loaded agent profile '${definition.name}'.`,
    });
  };

  const applyAgentDefinitionVersionDraft = (version: AgentDefinitionVersion) => {
    const primaryStep = createAgentStepDraftFromDefinition(version);
    setWorkbenchMode("agent");
    setSelectedAgentDefinitionId(version.agent_definition_id);
    setSelectedAgentDefinitionVersionId(version.id);
    setAgentProfileName(version.name);
    setAgentProfileDescription(version.description ?? "");
    setAgentInstructions(version.instructions || "");
    setAgentLlmProvider(typeof version.model_config?.provider === "string" ? version.model_config.provider : "");
    setAgentLlmModel(typeof version.model_config?.model === "string" ? version.model_config.model : "");
    setRunLlmProvider("");
    setRunLlmModel("");
    setAgentTitle(version.name || "Agent workbench run");
    setAgentGoal(version.default_goal || "");
    setAgentUserId(version.user_id || workspaceUserId);
    setAgentSteps([primaryStep]);
    setAgentAllowedCapabilityIds(version.allowed_capability_ids ?? []);
    setAgentProfileError(null);
    setLaunchError(null);
    setWorkbenchBanner({
      tone: "info",
      message: `Loaded published version v${version.version_number} of '${version.name}'.`,
    });
  };

  const buildAgentDefinitionPayload = (): AgentDefinitionCreateRequest => {
    const primaryStep = primaryAgentStep ?? createAgentStepDraft(DEFAULT_AGENT_CAPABILITY_ID, "agent");
    const capabilityId = primaryStep.capabilityId.trim() || DEFAULT_AGENT_CAPABILITY_ID;
    const defaultGoal =
      agentGoal.trim() || stringInputValue(primaryStep.inputDraft, "goal").trim();
    const workspacePath = stringInputValue(primaryStep.inputDraft, "workspace_path").trim();
    const constraints = splitConstraintList(
      stringInputValue(primaryStep.inputDraft, "constraints")
    );
    const maxStepsText = stringInputValue(primaryStep.inputDraft, "max_steps").trim();
    let maxSteps: number | null = null;
    if (maxStepsText) {
      const parsedMaxSteps = Number(maxStepsText);
      if (!Number.isInteger(parsedMaxSteps) || parsedMaxSteps <= 0) {
        throw new Error("Agent profile max steps must be a positive whole number.");
      }
      maxSteps = parsedMaxSteps;
    }
    const allowedCapabilityIds = Array.from(new Set(agentAllowedCapabilityIds.filter(Boolean)));
    const fallbackName = defaultGoal ? defaultGoal.slice(0, 96) : "Agent profile";
    const name =
      agentProfileName.trim() ||
      agentTitle.trim() ||
      fallbackName;
    const instructions =
      agentInstructions.trim() ||
      primaryStep.instruction.trim() ||
      defaultStepInstruction(capabilityId, "agent");
    return {
      name,
      description: agentProfileDescription.trim() || null,
      agent_capability_id: capabilityId,
      instructions,
      default_goal: defaultGoal,
      default_workspace_path: workspacePath || null,
      default_constraints: constraints,
      default_max_steps: maxSteps,
      model_config: {
        ...(agentLlmProvider.trim() ? { provider: agentLlmProvider.trim() } : {}),
        ...(agentLlmModel.trim() ? { model: agentLlmModel.trim() } : {}),
      },
      allowed_capability_ids: allowedCapabilityIds,
      user_id: agentUserId.trim() || workspaceUserId.trim() || null,
      metadata: {
        ...(selectedAgentDefinition?.metadata ?? {}),
        surface: "studio_workbench",
      },
    };
  };

  const handleNewAgentProfile = () => {
    setWorkbenchMode("agent");
    setSelectedAgentDefinitionId("");
    setSelectedAgentDefinitionVersionId("");
    setAgentProfileVersionNote("");
    setAgentProfileName("");
    setAgentProfileDescription("");
    setAgentTitle("Agent workbench run");
    setAgentGoal("");
    setAgentSteps([createAgentStepDraft(DEFAULT_AGENT_CAPABILITY_ID, "agent")]);
    setRunLlmProvider("");
    setRunLlmModel("");
    setAgentProfileError(null);
    setLaunchError(null);
    setWorkbenchBanner({
      tone: "info",
      message: "Started a new unsaved agent profile draft.",
    });
  };

  const handleSaveAgentProfile = async () => {
    if (!selectedAgentDefinitionId) {
      setAgentProfileError("Select a saved profile first, or use Save as to create one.");
      return;
    }
    setAgentProfileSaving(true);
    setAgentProfileError(null);
    try {
      const payload = buildAgentDefinitionPayload();
      const updated = await updateAgentDefinition(selectedAgentDefinitionId, payload);
      queryClient.setQueryData<AgentDefinition[]>(
        studioWorkbenchKeys.agentDefinitions(workspaceUserId),
        (current: AgentDefinition[] | undefined) =>
          (current ?? []).map((definition) => (definition.id === updated.id ? updated : definition))
      );
      setSelectedAgentDefinitionId(updated.id);
      setSelectedAgentDefinitionVersionId("");
      setAgentProfileName(updated.name);
      setAgentProfileDescription(updated.description ?? "");
      setWorkbenchBanner({
        tone: "info",
        message: `Saved agent profile '${updated.name}'.`,
      });
    } catch (error) {
      setAgentProfileError(
        error instanceof Error ? error.message : "Failed to save agent profile."
      );
    } finally {
      setAgentProfileSaving(false);
    }
  };

  const handleSaveAgentProfileAs = async () => {
    setAgentProfileSaving(true);
    setAgentProfileError(null);
    try {
      const payload = buildAgentDefinitionPayload();
      const created = await createAgentDefinition(payload);
      queryClient.setQueryData<AgentDefinition[]>(
        studioWorkbenchKeys.agentDefinitions(workspaceUserId),
        (current: AgentDefinition[] | undefined) => [
          created,
          ...(current ?? []).filter((definition) => definition.id !== created.id),
        ]
      );
      setSelectedAgentDefinitionId(created.id);
      setSelectedAgentDefinitionVersionId("");
      setAgentProfileName(created.name);
      setAgentProfileDescription(created.description ?? "");
      setWorkbenchBanner({
        tone: "info",
        message: `Saved new agent profile '${created.name}'.`,
      });
    } catch (error) {
      setAgentProfileError(
        error instanceof Error ? error.message : "Failed to create agent profile."
      );
    } finally {
      setAgentProfileSaving(false);
    }
  };

  const handlePublishAgentProfile = async () => {
    if (!selectedAgentDefinitionId) {
      setAgentProfileError("Save the profile before publishing a version.");
      return;
    }
    setAgentProfilePublishing(true);
    setAgentProfileError(null);
    try {
      const payload = buildAgentDefinitionPayload();
      const updated = await updateAgentDefinition(selectedAgentDefinitionId, payload);
      queryClient.setQueryData<AgentDefinition[]>(
        studioWorkbenchKeys.agentDefinitions(workspaceUserId),
        (current: AgentDefinition[] | undefined) =>
          (current ?? []).map((definition) => (definition.id === updated.id ? updated : definition))
      );
      const published = await publishAgentDefinitionVersion(updated.id, {
        version_note: agentProfileVersionNote.trim() || null,
        published_by: agentUserId.trim() || workspaceUserId.trim() || null,
        metadata: {
          surface: "studio_workbench",
        },
      });
      queryClient.setQueryData<AgentDefinitionVersion[]>(
        studioWorkbenchKeys.agentDefinitionVersions(updated.id),
        (current: AgentDefinitionVersion[] | undefined) => [
          published,
          ...(current ?? []).filter((version) => version.id !== published.id),
        ]
      );
      setSelectedAgentDefinitionId(updated.id);
      setSelectedAgentDefinitionVersionId(published.id);
      setAgentProfileName(published.name);
      setAgentProfileDescription(published.description ?? "");
      setAgentProfileVersionNote("");
      setWorkbenchBanner({
        tone: "info",
        message: `Published '${published.name}' as version v${published.version_number}.`,
      });
    } catch (error) {
      setAgentProfileError(
        error instanceof Error ? error.message : "Failed to publish agent profile."
      );
    } finally {
      setAgentProfilePublishing(false);
    }
  };

  const handleDeleteAgentProfile = async () => {
    if (!selectedAgentDefinitionId) {
      return;
    }
    setConfirmDeleteProfile(false);
    setAgentProfileDeleting(true);
    setAgentProfileError(null);
    try {
      await deleteAgentDefinition(selectedAgentDefinitionId);
      queryClient.setQueryData<AgentDefinition[]>(
        studioWorkbenchKeys.agentDefinitions(workspaceUserId),
        (current: AgentDefinition[] | undefined) =>
          (current ?? []).filter((definition) => definition.id !== selectedAgentDefinitionId)
      );
      setSelectedAgentDefinitionId("");
      setSelectedAgentDefinitionVersionId("");
      setAgentProfileVersionNote("");
      setAgentProfileName("");
      setAgentProfileDescription("");
      setWorkbenchBanner({
        tone: "info",
        message: "Deleted the agent profile.",
      });
    } catch (error) {
      setAgentProfileError(
        error instanceof Error ? error.message : "Failed to delete agent profile."
      );
    } finally {
      setAgentProfileDeleting(false);
    }
  };

  const applyCapabilityReplayDraft = (draft: ReplayableCapabilityDraft) => {
    const targetCapability = catalog.find((item) => item.id === draft.capabilityId) ?? null;
    const nextCapabilityState = capabilityEditorStateFromInputs(targetCapability, draft.inputs);
    setWorkbenchMode("capability");
    setSelectedCapabilityId(draft.capabilityId);
    setCapabilityTitle(draft.title || `Capability run: ${draft.capabilityId}`);
    setCapabilityGoal(draft.goal);
    setCapabilityUserId(draft.userId || workspaceUserId);
    setCapabilityContextJsonText(formatJson(draft.contextJson));
    setCapabilityRetryPolicyText(
      draft.retryPolicy && Object.keys(draft.retryPolicy).length > 0
        ? formatJson(draft.retryPolicy)
        : ""
    );
    setCapabilityInputDraft(nextCapabilityState.inputDraft);
    setCapabilityRawOverrideEnabled(nextCapabilityState.rawOverrideEnabled);
    setCapabilityRawOverrideText(nextCapabilityState.rawOverrideText);
    setLaunchError(null);
    setWorkbenchBanner({
      tone: nextCapabilityState.rawOverrideEnabled ? "warning" : "info",
      message: nextCapabilityState.rawOverrideEnabled
        ? `${draft.notice} Some inputs stayed in raw JSON because the current capability schema could not represent them as structured fields.`
        : draft.notice,
    });
  };

  const applyForkResult = () => {
    if (!forkResult) {
      return;
    }
    if (forkResult.mode === "capability") {
      applyCapabilityReplayDraft(forkResult.draft);
      return;
    }
    setWorkbenchMode("agent");
    setSelectedAgentDefinitionId("");
    setSelectedAgentDefinitionVersionId("");
    setAgentProfileVersionNote("");
    setAgentProfileName("");
    setAgentProfileDescription("");
    setAgentProfileError(null);
    setAgentTitle(forkResult.draft.title || "Agent workbench run");
    setAgentGoal(forkResult.draft.goal);
    setAgentUserId(forkResult.draft.userId || workspaceUserId);
    setLaunchError(null);
    if (forkResult.mode === "agent_structured") {
      const [primaryStep, ...extraSteps] = forkResult.draft.steps;
      if (primaryStep) {
        const stepCapability = catalog.find((item) => item.id === primaryStep.capabilityId) ?? null;
        const nextInputState = capabilityEditorStateFromInputs(
          stepCapability,
          primaryStep.inputBindings
        );
        setAgentSteps([
          {
            localId: `forked-step-${primaryStep.stepId}-${Math.random().toString(36).slice(2, 8)}`,
            stepId: primaryStep.stepId,
            name: primaryStep.name,
            description: primaryStep.description,
            instruction: primaryStep.instruction,
            capabilityId: primaryStep.capabilityId,
            dependsOnText: "",
            inputDraft: nextInputState.inputDraft,
            rawInputOverrideEnabled: false,
            inputJsonText: nextInputState.rawOverrideText,
            retryPolicyText: "",
          },
        ]);
      } else {
        setAgentSteps([createAgentStepDraft(DEFAULT_AGENT_CAPABILITY_ID, "agent")]);
      }
      setWorkbenchBanner({
        tone: extraSteps.length > 0 ? "warning" : "info",
        message:
          extraSteps.length > 0
            ? `${forkResult.draft.notice} This run has ${forkResult.draft.steps.length} steps — only the first was loaded here. Use Promote to Workflow to edit the full multi-step run.`
            : forkResult.draft.notice,
      });
      return;
    }
    // mode === "agent_raw": the source run's primary step couldn't be reconstructed automatically.
    setAgentSteps([createAgentStepDraft(DEFAULT_AGENT_CAPABILITY_ID, "agent")]);
    setWorkbenchBanner({
      tone: "warning",
      message: `${forkResult.draft.notice} Reconfigure the agent step manually, or use Promote to Workflow / Debug Data to inspect the original run.`,
    });
  };

  const handleReplayStep = (stepId: string) => {
    const replayResult = replayResultsByStep.get(stepId);
    if (!replayResult || !replayResult.replayable) {
      return;
    }
    applyCapabilityReplayDraft(replayResult.draft);
  };

  const handlePromoteWorkflowDraft = () => {
    if (!workflowPromotionResult?.promotable || !onPromoteWorkflowDraft) {
      return;
    }
    onPromoteWorkflowDraft(workflowPromotionResult.draft);
  };

  const handleCapabilityInsert = (item: CapabilityItem) => {
    setWorkbenchMode("capability");
    setSelectedCapabilityId(item.id);
    setCapabilityTitle(`Capability run: ${item.id}`);
    setWorkbenchBanner(null);
  };

  const handleAgentInsert = (item: CapabilityItem) => {
    setWorkbenchMode("agent");
    if (isAgenticCapability(item)) {
      setAgentSteps((current) => {
        const [first, ...rest] =
          current.length > 0
            ? current
            : [createAgentStepDraft(DEFAULT_AGENT_CAPABILITY_ID, "agent")];
        return [
          {
            ...first,
            stepId: first.stepId || "agent",
            name: first.name || defaultStepName(item.id, "agent"),
            description: first.description || defaultStepDescription(item.id, "agent"),
            instruction: first.instruction || defaultStepInstruction(item.id, "agent"),
            capabilityId: item.id,
            inputDraft: {
              ...defaultAgentInputDraft(item.id),
              ...first.inputDraft,
            },
          },
          ...rest,
        ];
      });
    } else {
      setAgentAllowedCapabilityIds((prev) =>
        prev.includes(item.id) ? prev : [...prev, item.id]
      );
    }
    setWorkbenchBanner(null);
  };

  const handleToolInsert = (capabilityId: string) => {
    if (capabilityId.trim()) {
      setAgentAllowedCapabilityIds((prev) =>
        prev.includes(capabilityId) ? prev : [...prev, capabilityId]
      );
    }
  };

  const handleToolRemove = (capabilityId: string) => {
    setAgentAllowedCapabilityIds((prev) => prev.filter((id) => id !== capabilityId));
  };

  const updatePrimaryAgentStep = (updater: (current: AgentStepDraft) => AgentStepDraft) => {
    setAgentSteps((current) => {
      const [first, ...rest] =
        current.length > 0
          ? current
          : [createAgentStepDraft(DEFAULT_AGENT_CAPABILITY_ID, "agent")];
      return [updater(first), ...rest];
    });
  };

  const updatePrimaryAgentCapability = (capabilityId: string) => {
    updatePrimaryAgentStep((current) => ({
      ...current,
      capabilityId,
      stepId: current.stepId || "agent",
      name: current.name || defaultStepName(capabilityId, "agent"),
      description: current.description || defaultStepDescription(capabilityId, "agent"),
      instruction: current.instruction || defaultStepInstruction(capabilityId, "agent"),
      inputDraft: {
        ...defaultAgentInputDraft(capabilityId),
        ...current.inputDraft,
      },
      rawInputOverrideEnabled: false,
    }));
  };

  const updatePrimaryAgentInput = (key: string, value: string) => {
    if (key === "goal") {
      setAgentGoal(value);
    }
    updatePrimaryAgentStep((current) => ({
      ...current,
      inputDraft: {
        ...current.inputDraft,
        [key]: value,
      },
      rawInputOverrideEnabled: false,
    }));
  };

  const launchCurrentWorkbenchRun = async () => {
    setLaunchLoading(true);
    setLaunchError(null);
    setWorkbenchBanner(null);

    try {
      let response: WorkbenchRunLaunchResponse;
      if (workbenchMode === "capability") {
        if (!selectedCapability) {
          throw new Error("Choose a capability before launching a workbench run.");
        }
        if (capabilityContextJson.error) {
          throw new Error(capabilityContextJson.error);
        }
        if (capabilityRetryPolicy.error) {
          throw new Error(capabilityRetryPolicy.error);
        }
        if (capabilityLaunchInputs.error || !capabilityLaunchInputs.value) {
          throw new Error(capabilityLaunchInputs.error || "Capability inputs are invalid.");
        }
        response = await launchCapabilityRun({
          title: capabilityTitle.trim(),
          goal: capabilityGoal.trim(),
          user_id: capabilityUserId.trim() || null,
          context_json: capabilityContextJson.value ?? {},
          capability_id: selectedCapability.id,
          inputs: capabilityLaunchInputs.value,
          retry_policy:
            capabilityRetryPolicy.value && Object.keys(capabilityRetryPolicy.value).length > 0
              ? capabilityRetryPolicy.value
              : null,
        });
      } else {
        if (agentRunSpecPreview.error || !agentRunSpecPreview.value) {
          throw new Error(agentRunSpecPreview.error || "Agent RunSpec is invalid.");
        }
        // Pre-flight: validate the agent's capability id against the loaded catalog
        const catalogIds = new Set(catalog.map((c) => c.id));
        const cid = primaryAgentStep?.capabilityId.trim() ?? "";
        if (catalogIds.size > 0 && cid && !catalogIds.has(cid)) {
          const suggestion = catalog.find((c) =>
            c.id.includes(cid.toLowerCase()) || cid.toLowerCase().includes(c.id.split(".")[0])
          );
          throw new Error(
            `"${cid}" is not a known capability.${suggestion ? ` Did you mean "${suggestion.id}"?` : " Browse the catalog to find the right ID."}`
          );
        }
        const primaryAgentGoal = stringInputValue(primaryAgentStep?.inputDraft ?? {}, "goal").trim();
        response = await launchAgentRun({
          title: agentTitle.trim(),
          goal: agentGoal.trim() || primaryAgentGoal,
          user_id: agentUserId.trim() || null,
          context_json: {},
          run_spec: agentRunSpecPreview.value,
          ...(selectedAgentDefinitionId
            ? { agent_definition_id: selectedAgentDefinitionId }
            : {}),
          ...(selectedAgentDefinitionVersionId
            ? { agent_definition_version_id: selectedAgentDefinitionVersionId }
            : {}),
        });
      }

      setLaunchResponse(response);
      // Setting activeRunId enables and keys debuggerQueryResult for the new
      // run, so it fetches (and then polls) reactively — no manual fetch here.
      setActiveRunId(response.run.id);
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : "Workbench launch failed.");
    } finally {
      setLaunchLoading(false);
    }
  };

  const artifacts = useMemo(() => collectArtifacts(debuggerData), [debuggerData]);
  const activeSurface: StudioSurface = "workbench";
  const launchWorkbenchModeLabel =
    typeof launchResponse?.run?.metadata?.workbench_mode === "string"
      ? launchResponse.run.metadata.workbench_mode
      : workbenchMode;

  const debugPanels: { id: WorkbenchDebugPanelId; label: string; value: unknown; emptyLabel: string }[] = [
    {
      id: "run_spec",
      label: "RunSpec Preview",
      value: workbenchMode === "capability" ? capabilityRunSpecPreview : agentRunSpecPreview.value,
      emptyLabel: "The current editor state does not yet produce a valid run specification.",
    },
    {
      id: "predicted_execution_request",
      label: "Predicted First ExecutionRequest",
      value: predictedExecutionRequestPreview,
      emptyLabel: "Execution request preview will appear once the first step is valid.",
    },
    ...(workbenchMode === "capability" && selectedCapability
      ? [
          {
            id: "capability_input_schema" as const,
            label: "Capability Input Schema",
            value: selectedCapability.input_schema,
            emptyLabel: "No input schema is available for the selected capability.",
          },
          {
            id: "capability_output_schema" as const,
            label: "Capability Output Schema",
            value: selectedCapability.output_schema,
            emptyLabel: "No output schema is available for the selected capability.",
          },
        ]
      : []),
    {
      id: "retry_policy",
      label: "Retry / Policy Snapshot",
      value:
        workbenchMode === "capability"
          ? {
              retry_policy:
                capabilityRetryPolicy.value && Object.keys(capabilityRetryPolicy.value).length > 0
                  ? capabilityRetryPolicy.value
                  : DEFAULT_RETRY_POLICY_PREVIEW,
              acceptance_policy: { acceptance_criteria: [], critic_required: false },
            }
          : isRecord(predictedExecutionRequestPreview)
            ? {
                retry_policy: predictedExecutionRequestPreview.retry_policy ?? {},
                policy_snapshot: predictedExecutionRequestPreview.policy_snapshot ?? {},
              }
            : null,
      emptyLabel: "Policy preview will appear once the active workbench payload is valid.",
    },
    {
      id: "initial_execution_request",
      label: "Initial Prepared ExecutionRequest",
      value: launchResponse?.execution_request,
      emptyLabel: "The launch response did not include a prepared execution request.",
    },
    {
      id: "execution_requests",
      label: "Execution Requests",
      value: debuggerData?.execution_requests,
      emptyLabel: "No execution requests have been captured for this run yet.",
    },
    {
      id: "attempts",
      label: "Attempts / Tool Calls",
      value: { attempts: debuggerData?.attempts ?? [], invocations: debuggerData?.invocations ?? [] },
      emptyLabel: "No attempts or tool invocations have been captured yet.",
    },
    {
      id: "artifacts",
      label: "Artifacts",
      value: artifacts,
      emptyLabel: "Artifacts will appear once a step produces durable outputs.",
    },
    {
      id: "timeline",
      label: "Debugger Timeline",
      value: debuggerData?.events,
      emptyLabel: "Debugger events will stream in as the canonical runtime advances the run.",
    },
  ];
  const activeDebugPanel = debugPanels.find((panel) => panel.id === activeDebugPanelId) ?? debugPanels[0];

  const toolPickerCandidates = useMemo(() => {
    const q = toolPickerQuery.trim().toLowerCase();
    return catalog
      .filter(
        (item) =>
          !isAgenticCapability(item) &&
          !agentAllowedCapabilityIds.includes(item.id) &&
          (!q ||
            item.id.toLowerCase().includes(q) ||
            (item.description || "").toLowerCase().includes(q) ||
            (item.group || "").toLowerCase().includes(q))
      )
      .slice(0, 20);
  }, [catalog, toolPickerQuery, agentAllowedCapabilityIds]);

  const addToolFromPicker = (capabilityId: string) => {
    handleToolInsert(capabilityId);
    setToolPickerQuery("");
    toolPickerInputRef.current?.focus();
  };

  return (
    <section className={active ? "block" : "hidden"} aria-hidden={!active}>
      <div className="relative">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.26em] text-text-sky-token">
              Studio Surface
            </div>
            <h2 className="mt-1 flex items-center gap-2 text-xl font-semibold tracking-tight text-text-hi">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-xl border border-sky-300/22 bg-accent-sky text-text-sky-token">
                <StudioWorkbenchIcon kind="run" className="h-4 w-4" />
              </span>
              Agent Workbench
            </h2>
          </div>
        </div>

        {workbenchBanner ? (
          <div
            className={`mt-4 rounded-[24px] border px-4 py-3 text-sm ${
              workbenchBanner.tone === "warning"
                ? "border-amber-300/18 bg-accent-amber text-text-amber-token"
                : "border-sky-300/15 bg-accent-sky text-text-hi"
            }`}
          >
            {workbenchBanner.message}
          </div>
        ) : null}

        <datalist id="studio-capability-id-options">
          {catalog.map((item) => (
            <option key={item.id} value={item.id} />
          ))}
        </datalist>
        <datalist id="studio-agent-capability-options">
          {agentCapabilities.map((item) => (
            <option key={item.id} value={item.id} />
          ))}
        </datalist>

        <div className="studio-contrast-surface mt-3 overflow-hidden rounded-[24px] border border-subtle bg-gradient-panel-mid p-4 shadow-[0_12px_32px_rgba(15,23,42,0.14)]">
          <div className={`grid gap-4 ${catalogCollapsed ? "xl:grid-cols-[auto_minmax(0,1fr)]" : "xl:grid-cols-[240px_minmax(0,1fr)]"}`}>
            <SurfacePanel
              title={catalogCollapsed ? "" : "Catalog"}
              subtitle={catalogCollapsed ? "" : "Search live capabilities, filter the catalog, and insert into either sandbox."}
            >
              <button
                type="button"
                className="mb-2 flex items-center gap-1 rounded-lg border border-subtle bg-surface-1 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo transition hover:text-text-hi"
                onClick={() => setCatalogCollapsed((prev) => !prev)}
                title={catalogCollapsed ? "Expand catalog" : "Collapse catalog"}
              >
                {catalogCollapsed ? "›" : "‹"} {catalogCollapsed ? "" : "Collapse"}
              </button>
              {catalogCollapsed ? null : <div className="space-y-3">
                <Input
                  value={catalogQuery}
                  onChange={(event) => setCatalogQuery(event.target.value)}
                  placeholder="Search capabilities"
                  className="bg-slate-950/45"
                />
                <div className="grid gap-2">
                  <select
                    value={groupFilter}
                    onChange={(event) => setGroupFilter(event.target.value)}
                    className="rounded-xl border border-subtle bg-slate-950/45 px-3 py-2 text-xs text-text-hi outline-none"
                  >
                    <option value="all">All groups</option>
                    {groupOptions.map((group) => (
                      <option key={group} value={group}>
                        {group}
                      </option>
                    ))}
                  </select>
                  <select
                    value={riskFilter}
                    onChange={(event) => setRiskFilter(event.target.value)}
                    className="rounded-xl border border-subtle bg-slate-950/45 px-3 py-2 text-xs text-text-hi outline-none"
                  >
                    <option value="all">All risk tiers</option>
                    {riskOptions.map((risk) => (
                      <option key={risk} value={risk}>
                        {risk}
                      </option>
                    ))}
                  </select>
                  <select
                    value={idempotencyFilter}
                    onChange={(event) => setIdempotencyFilter(event.target.value)}
                    className="rounded-xl border border-subtle bg-slate-950/45 px-3 py-2 text-xs text-text-hi outline-none"
                  >
                    <option value="all">All idempotency</option>
                    {idempotencyOptions.map((mode) => (
                      <option key={mode} value={mode}>
                        {mode}
                      </option>
                    ))}
                  </select>
                </div>
                {catalogLoading ? (
                  <div className="rounded-2xl border border-white/8 bg-black/20 px-3 py-3 text-xs text-text-md">
                    Loading capability catalog...
                  </div>
                ) : null}
                {catalogError ? (
                  <div className="rounded-2xl border border-rose-300/18 bg-accent-rose px-3 py-3 text-xs text-text-rose-token">
                    {catalogError}
                  </div>
                ) : null}
                {catalogSearchLoading ? (
                  <div className="text-[11px] text-text-md">Searching capability catalog...</div>
                ) : null}
                {catalogSearchError ? (
                  <div className="text-[11px] text-text-rose-token">{catalogSearchError}</div>
                ) : null}
                <div className="max-h-[460px] space-y-2 overflow-auto pr-1">
                  {filteredCatalog.map((item) => {
                    const searchHit = catalogSearchItems.find((candidate) => candidate.id === item.id);
                    return (
                      <div
                        key={item.id}
                        className={`rounded-2xl border px-3 py-3 ${
                          item.id === selectedCapabilityId
                            ? "border-sky-300/28 bg-accent-sky"
                            : "border-white/8 bg-black/18"
                        }`}
                      >
                        <button
                          type="button"
                          className="w-full text-left"
                          onClick={() => setSelectedCapabilityId(item.id)}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-sm font-semibold text-text-hi">{item.id}</div>
                            <span className="rounded-full border border-subtle bg-surface-1 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-text-md">
                              {item.group || "ungrouped"}
                            </span>
                          </div>
                          <div className="mt-1 text-xs leading-5 text-text-md">
                            {item.description}
                          </div>
                        </button>
                        <div className="mt-3 flex flex-wrap gap-2 text-[10px] uppercase tracking-[0.14em] text-text-md">
                          <span className="rounded-full border border-subtle bg-surface-1 px-2 py-1">
                            {item.risk_tier}
                          </span>
                          <span className="rounded-full border border-subtle bg-surface-1 px-2 py-1">
                            {item.idempotency}
                          </span>
                          {searchHit ? (
                            <span className="rounded-full border border-sky-300/22 bg-accent-sky px-2 py-1 text-text-sky-token">
                              {searchHit.source}
                            </span>
                          ) : null}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {!isAgenticCapability(item) && agentAllowedCapabilityIds.includes(item.id) ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="cursor-default uppercase tracking-[0.14em] text-text-sky-token"
                              disabled
                            >
                              ✓ Added
                            </Button>
                          ) : (
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              className="uppercase tracking-[0.14em]"
                              onClick={() => handleAgentInsert(item)}
                            >
                              {isAgenticCapability(item) ? "Use as Agent" : "Add as Tool"}
                            </Button>
                          )}
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="uppercase tracking-[0.14em]"
                            onClick={() => handleCapabilityInsert(item)}
                          >
                            Test
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                  {!catalogLoading && filteredCatalog.length === 0 ? (
                    <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-4 text-xs text-text-md">
                      No capabilities matched the current search and filters.
                    </div>
                  ) : null}
                </div>
              </div>}
            </SurfacePanel>

            <SurfacePanel
              title="Configure"
              subtitle=""
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="rounded-full border border-sky-300/28 bg-accent-sky px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi">
                  {workbenchMode === "capability" ? "Test Capability" : "Build Agent"}
                </span>
              </div>

              {workbenchMode === "capability" ? (
                <div className="mt-4 space-y-4">
                  <div className="grid gap-3 lg:grid-cols-2">
                    <label className="text-xs text-text-md">
                      <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">
                        Capability Id
                      </span>
                      <Input
                        list="studio-capability-id-options"
                        value={selectedCapabilityId}
                        onChange={(event) => setSelectedCapabilityId(event.target.value)}
                        className="bg-slate-950/45"
                      />
                    </label>
                    <WorkbenchUserIdField value={capabilityUserId} onChange={setCapabilityUserId} />
                    <WorkbenchTitleField value={capabilityTitle} onChange={setCapabilityTitle} />
                    <label className="text-xs text-text-md">
                      <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">
                        Goal
                      </span>
                      <Input
                        value={capabilityGoal}
                        onChange={(event) => setCapabilityGoal(event.target.value)}
                        className="bg-slate-950/45"
                      />
                    </label>
                  </div>

                  <WorkbenchContextJsonField value={capabilityContextJsonText} onChange={setCapabilityContextJsonText} />

                  <div className="rounded-2xl border border-white/8 bg-black/18 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-md">
                          Generated input form
                        </div>
                        <div className="mt-1 text-xs text-text-md">
                          Required fields come from the capability input schema.
                        </div>
                      </div>
                      <label className="inline-flex items-center gap-2 text-[11px] uppercase tracking-[0.14em] text-text-md">
                        <input
                          type="checkbox"
                          checked={capabilityRawOverrideEnabled}
                          onChange={(event) => setCapabilityRawOverrideEnabled(event.target.checked)}
                        />
                        raw override
                      </label>
                    </div>
                    <div className="mt-3 space-y-3">
                      {capabilitySchemaProperties.map(([fieldName, schema]) => {
                        const fieldType = normalizeSchemaType(schema);
                        const required = selectedCapability?.required_inputs?.includes(fieldName) ?? false;
                        const rawFieldValue = capabilityInputDraft[fieldName];
                        const fieldValue = typeof rawFieldValue === "string" ? rawFieldValue : "";
                        if (fieldType === "boolean") {
                          return (
                            <label
                              key={fieldName}
                              className="flex items-center justify-between gap-3 rounded-2xl border border-white/8 bg-slate-950/38 px-3 py-2 text-sm text-text-hi"
                            >
                              <span>
                                {fieldName}
                                {required ? <span className="ml-2 text-[10px] uppercase text-text-sky-token">required</span> : null}
                              </span>
                              <input
                                type="checkbox"
                                checked={capabilityInputDraft[fieldName] === true}
                                onChange={(event) =>
                                  setCapabilityInputDraft((current) => ({
                                    ...current,
                                    [fieldName]: event.target.checked,
                                  }))
                                }
                              />
                            </label>
                          );
                        }
                        const multiLine = fieldType === "object" || fieldType === "array";
                        return (
                          <label key={fieldName} className="block text-xs text-text-md">
                            <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">
                              {fieldName}
                              {required ? " *" : ""}
                            </span>
                            {multiLine ? (
                              <Textarea
                                rows={4}
                                value={fieldValue}
                                onChange={(event) =>
                                  setCapabilityInputDraft((current) => ({
                                    ...current,
                                    [fieldName]: event.target.value,
                                  }))
                                }
                                className="rounded-2xl bg-slate-950/45 py-3 font-mono text-[12px]"
                              />
                            ) : (
                              <Input
                                value={fieldValue}
                                onChange={(event) =>
                                  setCapabilityInputDraft((current) => ({
                                    ...current,
                                    [fieldName]: event.target.value,
                                  }))
                                }
                                className="bg-slate-950/45"
                              />
                            )}
                          </label>
                        );
                      })}
                      {capabilitySchemaProperties.length === 0 ? (
                        <div className="rounded-2xl border border-white/8 bg-slate-950/38 px-3 py-4 text-xs text-text-md">
                          This capability does not expose structured schema fields. Use the raw input override
                          for advanced payloads.
                        </div>
                      ) : null}
                    </div>
                  </div>

                  {capabilityRawOverrideEnabled ? (
                    <label className="block text-xs text-text-md">
                      <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">
                        Raw input override JSON
                      </span>
                      <Textarea
                        rows={6}
                        value={capabilityRawOverrideText}
                        onChange={(event) => setCapabilityRawOverrideText(event.target.value)}
                        className="rounded-2xl bg-slate-950/45 py-3 font-mono text-[12px]"
                      />
                    </label>
                  ) : null}

                  <label className="block text-xs text-text-md">
                    <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">
                      Advanced retry / policy override
                    </span>
                    <Textarea
                      rows={4}
                      value={capabilityRetryPolicyText}
                      onChange={(event) => setCapabilityRetryPolicyText(event.target.value)}
                      className="rounded-2xl bg-slate-950/45 py-3 font-mono text-[12px]"
                    />
                  </label>
                </div>
              ) : (
                <div className="mt-4 space-y-4">

                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-sky-token">
                    Definition
                  </div>

                  {/* ── Profile header: compact select + version ── */}
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={selectedAgentDefinitionId}
                      onChange={(event) => {
                        const nextId = event.target.value;
                        if (!nextId) {
                          setSelectedAgentDefinitionId("");
                          setSelectedAgentDefinitionVersionId("");
                          setAgentProfileName("");
                          setAgentProfileDescription("");
                          setAgentInstructions("");
                          setAgentProfileError(null);
                          return;
                        }
                        const definition =
                          agentDefinitions.find((item) => item.id === nextId) ?? null;
                        if (definition) {
                          applyAgentDefinitionDraft(definition);
                        }
                      }}
                      className="rounded-xl border border-subtle bg-slate-950/45 px-3 py-1.5 text-sm text-text-hi outline-none transition focus:border-sky-300/35"
                    >
                      <option value="">Unsaved draft</option>
                      {agentDefinitions.map((definition) => (
                        <option key={definition.id} value={definition.id}>
                          {definition.name}
                        </option>
                      ))}
                    </select>
                    <select
                      value={selectedAgentDefinitionVersionId}
                      onChange={(event) => {
                        const nextVersionId = event.target.value;
                        if (!nextVersionId) {
                          setSelectedAgentDefinitionVersionId("");
                          if (selectedAgentDefinition) {
                            applyAgentDefinitionDraft(selectedAgentDefinition);
                          }
                          return;
                        }
                        const version =
                          agentDefinitionVersions.find((item) => item.id === nextVersionId) ?? null;
                        if (version) {
                          applyAgentDefinitionVersionDraft(version);
                        }
                      }}
                      disabled={!selectedAgentDefinitionId || agentDefinitionVersionsLoading}
                      className="rounded-xl border border-subtle bg-slate-950/45 px-3 py-1.5 text-sm text-text-hi outline-none transition focus:border-sky-300/35 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <option value="">Draft / latest</option>
                      {agentDefinitionVersions.map((version) => (
                        <option key={version.id} value={version.id}>
                          v{version.version_number}
                          {version.version_note ? ` — ${version.version_note}` : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                  {(agentDefinitionVersionsError || agentDefinitionsError || agentProfileError) ? (
                    <div className="rounded-2xl border border-rose-300/18 bg-accent-rose px-3 py-3 text-xs text-text-rose-token">
                      {agentDefinitionVersionsError || agentDefinitionsError || agentProfileError}
                    </div>
                  ) : null}

                  {/* ── Save / publish / delete ── */}
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      className="uppercase tracking-[0.14em]"
                      onClick={() => void handleSaveAgentProfileAs()}
                      disabled={agentProfileSaving}
                    >
                      {agentProfileSaving ? "Saving…" : "Save as new"}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      className="uppercase tracking-[0.14em]"
                      onClick={() => void handleSaveAgentProfile()}
                      disabled={!selectedAgentDefinitionId || agentProfileSaving}
                    >
                      {agentProfileSaving ? "Saving…" : "Save"}
                    </Button>
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      className="border-emerald-300/24 bg-accent-emerald uppercase tracking-[0.14em] hover:border-emerald-300/36 hover:bg-accent-emerald/80"
                      onClick={() => void handlePublishAgentProfile()}
                      disabled={!selectedAgentDefinitionId || agentProfileSaving || agentProfilePublishing}
                    >
                      {agentProfilePublishing ? "Publishing…" : "Publish version"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="uppercase tracking-[0.14em]"
                      onClick={() => handleNewAgentProfile()}
                    >
                      New
                    </Button>
                    {confirmDeleteProfile ? (
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-text-rose-token">Delete this profile?</span>
                        <Button
                          type="button"
                          variant="destructive"
                          size="sm"
                          onClick={() => void handleDeleteAgentProfile()}
                          disabled={agentProfileDeleting}
                        >
                          {agentProfileDeleting ? "Deleting…" : "Yes, delete"}
                        </Button>
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          onClick={() => setConfirmDeleteProfile(false)}
                        >
                          Cancel
                        </Button>
                      </div>
                    ) : (
                      <Button
                        type="button"
                        variant="destructive"
                        size="sm"
                        className="uppercase tracking-[0.14em]"
                        onClick={() => setConfirmDeleteProfile(true)}
                        disabled={!selectedAgentDefinitionId || agentProfileDeleting}
                      >
                        Delete
                      </Button>
                    )}
                  </div>

                  {/* ── Agent identity ── */}
                  <div className="space-y-3">
                    <div className="grid gap-3 lg:grid-cols-2">
                      <label className="text-xs text-text-md">
                        <span className="mb-1 block uppercase tracking-[0.16em] text-text-lo">Name</span>
                        <Input
                          value={agentProfileName}
                          onChange={(event) => setAgentProfileName(event.target.value)}
                          placeholder="My agent"
                          className="bg-slate-950/45"
                        />
                      </label>
                      <label className="text-xs text-text-md">
                        <span className="mb-1 block uppercase tracking-[0.16em] text-text-lo">Description</span>
                        <Input
                          value={agentProfileDescription}
                          onChange={(event) => setAgentProfileDescription(event.target.value)}
                          placeholder="What this agent does"
                          className="bg-slate-950/45"
                        />
                      </label>
                    </div>
                    <label className="block text-xs text-text-md">
                      <span className="mb-1 block uppercase tracking-[0.16em] text-text-lo">Instructions</span>
                      <Textarea
                        rows={5}
                        value={agentInstructions}
                        onChange={(event) => setAgentInstructions(event.target.value)}
                        placeholder="You are a helpful agent. Think step by step and use your tools to achieve the goal."
                        className="rounded-2xl bg-slate-950/45 py-3"
                      />
                    </label>
                    {primaryAgentStep ? (
                      <label className="text-xs text-text-md">
                        <span className="mb-1 block uppercase tracking-[0.16em] text-text-lo">Agent capability</span>
                        <Input
                          list="studio-agent-capability-options"
                          value={primaryAgentStep.capabilityId}
                          onChange={(event) => updatePrimaryAgentCapability(event.target.value)}
                          className="bg-slate-950/45"
                        />
                        {primaryAgentCapability ? (
                          <span className="mt-1 block text-[11px] leading-5 text-text-md">
                            {primaryAgentCapability.description}
                          </span>
                        ) : null}
                      </label>
                    ) : null}
                    <WorkbenchLlmModelFields
                      provider={agentLlmProvider}
                      model={agentLlmModel}
                      onProviderChange={setAgentLlmProvider}
                      onModelChange={setAgentLlmModel}
                      unsetLabel="Platform default"
                    />
                  </div>

                  {/* ── Tools ── */}
                  <div className="rounded-2xl border border-white/8 bg-black/18 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-md">Tools</div>
                        <div className="mt-0.5 text-[11px] text-text-lo">Capabilities this agent can call during the run loop.</div>
                      </div>
                      <span className="rounded-full border border-subtle bg-surface-1 px-2 py-0.5 text-[10px] text-text-lo">
                        {agentAllowedCapabilityIds.length} added
                      </span>
                    </div>
                    {agentAllowedCapabilityIds.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {agentAllowedCapabilityIds.map((capId) => {
                          const cap = catalog.find((c) => c.id === capId);
                          return (
                            <div
                              key={capId}
                              className="flex items-center gap-1.5 rounded-xl border border-subtle bg-surface-1 pl-3 pr-1.5 py-1"
                            >
                              <span className="text-[11px] font-medium text-text-hi">{capId}</span>
                              {cap?.group ? (
                                <span className="rounded-full border border-subtle bg-surface-2 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.12em] text-text-lo">
                                  {cap.group}
                                </span>
                              ) : null}
                              <button
                                type="button"
                                className="ml-1 rounded-md px-1.5 py-0.5 text-[10px] text-text-lo transition hover:bg-accent-rose hover:text-text-rose-token"
                                onClick={() => handleToolRemove(capId)}
                                aria-label={`Remove ${capId}`}
                              >
                                ✕
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="mt-3 text-[11px] text-text-lo">
                        No tools added yet. Search below to add one.
                      </div>
                    )}
                    <div className="relative mt-3">
                      <Input
                        ref={toolPickerInputRef}
                        value={toolPickerQuery}
                        onChange={(e) => {
                          setToolPickerQuery(e.target.value);
                          setToolPickerOpen(true);
                        }}
                        onFocus={() => setToolPickerOpen(true)}
                        onBlur={() => setToolPickerOpen(false)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && toolPickerCandidates[0]) {
                            e.preventDefault();
                            addToolFromPicker(toolPickerCandidates[0].id);
                          } else if (e.key === "Escape") {
                            setToolPickerOpen(false);
                          }
                        }}
                        placeholder="Search capabilities to add as tools..."
                        className="bg-slate-950/45"
                      />
                      {toolPickerOpen ? (
                        <div className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-xl border border-subtle bg-surface-2 shadow-[0_18px_36px_rgba(15,23,42,0.32)]">
                          {toolPickerCandidates.length > 0 ? (
                            toolPickerCandidates.map((item) => (
                              <button
                                key={item.id}
                                type="button"
                                className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left transition hover:bg-surface-1"
                                onMouseDown={(e) => {
                                  e.preventDefault();
                                  addToolFromPicker(item.id);
                                }}
                              >
                                <span className="flex w-full items-center justify-between gap-2 text-xs font-semibold text-text-hi">
                                  {item.id}
                                  <span className="shrink-0 rounded-full border border-subtle bg-surface-1 px-1.5 py-0.5 text-[9px] font-normal uppercase tracking-[0.12em] text-text-lo">
                                    {item.group || "ungrouped"}
                                  </span>
                                </span>
                                {item.description ? (
                                  <span className="line-clamp-1 text-[11px] text-text-md">{item.description}</span>
                                ) : null}
                              </button>
                            ))
                          ) : (
                            <div className="px-3 py-2 text-xs text-text-lo">
                              {toolPickerQuery.trim()
                                ? "No matching capabilities."
                                : "All eligible capabilities are already added."}
                            </div>
                          )}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  {/* ── Execution ── */}
                  <div className="space-y-3 rounded-2xl border border-white/8 bg-black/18 p-3">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-md">
                      Execution
                    </div>
                    <label className="block text-xs text-text-md">
                      <span className="mb-1 block text-sm font-semibold text-text-hi">Goal</span>
                      <Textarea
                        rows={4}
                        value={agentGoal}
                        onChange={(event) => updatePrimaryAgentInput("goal", event.target.value)}
                        placeholder="Describe what this agent should accomplish…"
                        className="rounded-2xl bg-slate-950/45 py-3"
                      />
                    </label>
                    {primaryAgentStep ? (
                      <div className="grid gap-3 lg:grid-cols-2">
                        {!isAgentRunCapability(primaryAgentStep.capabilityId) ? (
                          <label className="text-xs text-text-md">
                            <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">
                              Workspace path
                            </span>
                            <Input
                              value={stringInputValue(primaryAgentStep.inputDraft, "workspace_path")}
                              onChange={(event) =>
                                updatePrimaryAgentInput("workspace_path", event.target.value)
                              }
                              className="bg-slate-950/45"
                            />
                          </label>
                        ) : null}
                        <label className="text-xs text-text-md">
                          <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">
                            Max steps
                          </span>
                          <Input
                            type="number"
                            min={1}
                            max={32}
                            value={stringInputValue(primaryAgentStep.inputDraft, "max_steps")}
                            onChange={(event) => updatePrimaryAgentInput("max_steps", event.target.value)}
                            className="bg-slate-950/45"
                          />
                        </label>
                        <label className="text-xs text-text-md lg:col-span-2">
                          <span className="mb-1 block uppercase tracking-[0.16em] text-text-md">
                            Constraints
                          </span>
                          <Textarea
                            rows={3}
                            value={stringInputValue(primaryAgentStep.inputDraft, "constraints")}
                            onChange={(event) => updatePrimaryAgentInput("constraints", event.target.value)}
                            className="rounded-2xl bg-slate-950/45 py-3"
                          />
                        </label>
                      </div>
                    ) : null}
                    <WorkbenchLlmModelFields
                      provider={runLlmProvider}
                      model={runLlmModel}
                      onProviderChange={setRunLlmProvider}
                      onModelChange={setRunLlmModel}
                      unsetLabel="Use agent's default"
                    />
                    <div className="grid gap-3 lg:grid-cols-2">
                      <WorkbenchTitleField value={agentTitle} onChange={setAgentTitle} />
                      <WorkbenchUserIdField value={agentUserId} onChange={setAgentUserId} />
                    </div>
                  </div>
                </div>
              )}

              {/* Debug Data — consolidated JSON/debug panels, shared between both modes and both
                  the pre-launch preview data and post-launch run results (previously split across
                  a "Developer Preview" group and four always-rendered panels further down). */}
              <div className="mt-4">
                <button
                  type="button"
                  className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-lo transition hover:text-text-hi"
                  onClick={() => setShowDebugData((v) => !v)}
                >
                  <span className={`transition-transform ${showDebugData ? "rotate-90" : ""}`}>▶</span>
                  Debug Data
                </button>
                {showDebugData ? (
                  <div className="mt-3 space-y-3">
                    <div className="flex flex-wrap gap-1.5">
                      {debugPanels.map((panel) => (
                        <button
                          key={panel.id}
                          type="button"
                          className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] transition ${
                            activeDebugPanel?.id === panel.id
                              ? "border-sky-300/35 bg-accent-sky text-text-hi"
                              : "border-subtle bg-surface-1 text-text-md hover:text-text-hi"
                          }`}
                          onClick={() => setActiveDebugPanelId(panel.id)}
                        >
                          {panel.label}
                        </button>
                      ))}
                    </div>
                    {activeDebugPanel ? (
                      <JsonPreview
                        title={activeDebugPanel.label}
                        value={activeDebugPanel.value}
                        emptyLabel={activeDebugPanel.emptyLabel}
                      />
                    ) : null}
                  </div>
                ) : null}
              </div>

              {(workbenchMode === "capability"
                ? capabilityLaunchInputs.error || capabilityContextJson.error || capabilityRetryPolicy.error
                : agentRunSpecPreview.error) ? (
                <div className="mt-4 rounded-2xl border border-rose-300/18 bg-accent-rose px-3 py-3 text-xs text-text-rose-token">
                  {workbenchMode === "capability"
                    ? capabilityLaunchInputs.error || capabilityContextJson.error || capabilityRetryPolicy.error
                    : agentRunSpecPreview.error}
                </div>
              ) : null}

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant="primary"
                  className="gap-2 px-5 uppercase tracking-[0.16em]"
                  onClick={() => void launchCurrentWorkbenchRun()}
                  disabled={launchLoading}
                >
                  <StudioWorkbenchIcon kind="run" className="h-4 w-4" />
                  {launchLoading ? "Running..." : workbenchMode === "agent" ? "Run Agent" : "Run"}
                </Button>
                {launchError ? <div className="text-xs text-text-rose-token">{launchError}</div> : null}
              </div>
            </SurfacePanel>

          </div>

          <div className="mt-4 rounded-[24px] border border-subtle bg-gradient-panel-deep shadow-[0_18px_36px_rgba(15,23,42,0.24)]">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-md">
                  Run Results
                </div>
              </div>
              <div className="flex flex-col items-end gap-2">
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="uppercase tracking-[0.14em]"
                    onClick={applyForkResult}
                    disabled={!forkResult}
                  >
                    Fork Run
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    className="uppercase tracking-[0.14em]"
                    onClick={handlePromoteWorkflowDraft}
                    disabled={!workflowPromotionResult?.promotable || !onPromoteWorkflowDraft}
                  >
                    Promote to Workflow
                  </Button>
                </div>
                {!onPromoteWorkflowDraft ? (
                  <div className="max-w-[420px] text-right text-[11px] text-text-amber-token">
                    Workflow promotion handoff is unavailable in the current Studio shell.
                  </div>
                ) : null}
                {forkResult?.mode === "agent_raw" ? (
                  <div className="max-w-[420px] text-right text-[11px] text-text-amber-token">
                    Fork will open the raw RunSpec editor: {forkResult.draft.reason}
                  </div>
                ) : null}
                {workflowPromotionResult && !workflowPromotionResult.promotable ? (
                  <div className="max-w-[420px] text-right text-[11px] text-text-amber-token">
                    Promote unavailable: {workflowPromotionResult.reason}
                  </div>
                ) : null}
                <div className="flex flex-wrap items-center justify-end gap-2 text-[10px] uppercase tracking-[0.14em]">
                  <span className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-text-hi">
                    status {currentRunStatus || "idle"}
                  </span>
                  <span className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-text-hi">
                    mode {launchWorkbenchModeLabel}
                  </span>
                  {activeRunId ? (
                    <span className="rounded-full border border-sky-300/28 bg-accent-sky px-3 py-1 text-text-hi">
                      run {activeRunId}
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
            <div className="px-4 py-4">
              <div className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-4">
                  <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-text-md">
                      steps
                    </div>
                    <div className="mt-2 text-2xl font-semibold text-text-hi">
                      {debuggerData?.steps.length ?? 0}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-text-md">
                      execution requests
                    </div>
                    <div className="mt-2 text-2xl font-semibold text-text-hi">
                      {debuggerData?.execution_requests.length ?? 0}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-text-md">
                      attempts
                    </div>
                    <div className="mt-2 text-2xl font-semibold text-text-hi">
                      {debuggerData?.attempts.length ?? 0}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-text-md">
                      invocations
                    </div>
                    <div className="mt-2 text-2xl font-semibold text-text-hi">
                      {debuggerData?.invocations.length ?? 0}
                    </div>
                  </div>
                </div>

                {debuggerLoading ? (
                  <div className="rounded-2xl border border-white/8 bg-black/18 px-3 py-3 text-xs text-text-md">
                    Refreshing debugger state...
                  </div>
                ) : null}
                {debuggerError ? (
                  <div className="rounded-2xl border border-rose-300/18 bg-accent-rose px-3 py-3 text-xs text-text-rose-token">
                    {debuggerError}
                  </div>
                ) : null}
                <div className="rounded-2xl border border-white/8 bg-black/18 p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-md">
                    Steps
                  </div>
                  <div className="mt-3 space-y-2">
                    {debuggerData?.steps.map((stepPayload) => {
                      const replayResult = replayResultsByStep.get(stepPayload.step.id);
                      return (
                        <div
                          key={stepPayload.step.id}
                          className="rounded-2xl border border-white/8 bg-slate-950/40 px-3 py-3"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-text-hi">
                                {stepPayload.step.name}
                              </div>
                              <div className="mt-1 text-xs text-text-md">
                                {stepPayload.step.capability_id}
                              </div>
                            </div>
                            <div className="flex flex-wrap items-center justify-end gap-2 text-[10px] uppercase tracking-[0.14em] text-text-md">
                              <span className="rounded-full border border-subtle bg-surface-1 px-2 py-1">
                                {stepPayload.step.status}
                              </span>
                              <span className="rounded-full border border-subtle bg-surface-1 px-2 py-1">
                                requests {stepPayload.execution_requests.length}
                              </span>
                              <span className="rounded-full border border-subtle bg-surface-1 px-2 py-1">
                                attempts {stepPayload.attempts.length}
                              </span>
                              <Button
                                type="button"
                                variant="secondary"
                                size="sm"
                                className="uppercase tracking-[0.14em]"
                                onClick={() => handleReplayStep(stepPayload.step.id)}
                                disabled={!replayResult?.replayable}
                              >
                                Replay Step
                              </Button>
                            </div>
                          </div>
                          {!replayResult?.replayable ? (
                            <div className="mt-2 text-xs text-text-amber-token">
                              Replay unavailable: {replayResult?.reason || "The replay payload could not be reconstructed."}
                            </div>
                          ) : null}
                          {stepPayload.error?.message ? (
                            <div className="mt-2 text-xs text-text-rose-token">
                              {String(stepPayload.error.message)}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                    {!debuggerData?.steps.length ? (
                      <div className="text-xs text-text-md">
                        Launch a workbench run to inspect step state here.
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
