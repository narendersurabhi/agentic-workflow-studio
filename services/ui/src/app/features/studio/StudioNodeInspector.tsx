"use client";

import { useState } from "react";

import type {
  AgentDefinition,
  CapabilityItem,
  CapabilitySchemaField,
  ComposerDraftNode,
  ComposerIssueFocus,
  ComposerInputBinding,
  StudioControlCase,
  StudioControlConfig,
  WorkflowInterface,
} from "./types";

type StudioInspectorField = {
  field: string;
  required: boolean;
  custom: boolean;
  status: "missing" | "from_chain" | "from_context" | "provided";
  detail: string;
  schemaType: string;
  schemaDescription: string;
  schemaProperty: Record<string, unknown> | null;
};

type StudioNodeInspectorProps = {
  selectedDagNode: ComposerDraftNode | null;
  selectedCapability: CapabilityItem | null;
  agentDefinitions?: AgentDefinition[];
  selectedDagNodeStatus: {
    requiredCount: number;
  } | null;
  inputFields: StudioInspectorField[];
  outputSchemaFields: CapabilitySchemaField[];
  activeComposerIssueFocus: ComposerIssueFocus | null;
  inspectorBindingRefs: React.MutableRefObject<Record<string, HTMLDivElement | null>>;
  visualChainNodes: ComposerDraftNode[];
  outputPathSuggestionsForNode: (node: ComposerDraftNode | undefined) => string[];
  contextPathSuggestions: string[];
  workflowInterface: WorkflowInterface;
  autoWireNodeBindings: (nodeId: string) => void;
  quickFixNodeBindings: (nodeId: string) => void;
  setSelectedDagNodeId: (nodeId: string | null) => void;
  capabilityIdOptionsId?: string;
  compactMode?: boolean;
  onDeleteNode?: (nodeId: string) => void;
  updateNodeBasics: (
    nodeId: string,
    patch: Partial<Pick<ComposerDraftNode, "taskName" | "capabilityId" | "outputPath">>
  ) => void;
  setVisualBindingMode: (
    nodeId: string,
    field: string,
    mode:
      | "context"
      | "from"
      | "literal"
      | "memory"
      | "workflow_input"
      | "workflow_variable"
  ) => void;
  clearVisualBinding: (nodeId: string, field: string) => void;
  removeCustomInputField: (nodeId: string, field: string) => void;
  addCustomInputField: (nodeId: string, field: string) => void;
  updateVisualBindingSourceNode: (nodeId: string, field: string, sourceNodeId: string) => void;
  updateVisualBindingPath: (nodeId: string, field: string, sourcePath: string) => void;
  updateVisualBindingLiteral: (nodeId: string, field: string, value: string) => void;
  updateVisualBindingContextPath: (nodeId: string, field: string, path: string) => void;
  updateVisualBindingMemory: (
    nodeId: string,
    field: string,
    patch: { scope?: "job" | "user" | "global"; name?: string; key?: string }
  ) => void;
  updateVisualBindingWorkflowInput: (nodeId: string, field: string, inputKey: string) => void;
  updateVisualBindingWorkflowVariable: (
    nodeId: string,
    field: string,
    variableKey: string
  ) => void;
  setVisualBindingFromPrevious: (nodeId: string, field: string) => void;
  addNodeOutput: (nodeId: string) => void;
  upsertNodeOutputFromSchema: (nodeId: string, field: CapabilitySchemaField) => void;
  updateNodeOutput: (
    nodeId: string,
    outputId: string,
    patch: { name?: string; path?: string; description?: string }
  ) => void;
  removeNodeOutput: (nodeId: string, outputId: string) => void;
  addNodeVariable: (nodeId: string) => void;
  updateNodeVariable: (
    nodeId: string,
    variableId: string,
    patch: { key?: string; value?: string; description?: string }
  ) => void;
  removeNodeVariable: (nodeId: string, variableId: string) => void;
  updateNodeControlConfig: (nodeId: string, patch: Partial<StudioControlConfig>) => void;
  addSwitchCase: (nodeId: string) => void;
  updateSwitchCase: (
    nodeId: string,
    caseId: string,
    patch: Partial<Pick<StudioControlCase, "label" | "match">>
  ) => void;
  removeSwitchCase: (nodeId: string, caseId: string) => void;
};

const bindingModeForField = (binding: ComposerInputBinding | undefined) => {
  if (binding?.kind === "step_output") {
    return "from";
  }
  if (binding?.kind === "literal") {
    return "literal";
  }
  if (binding?.kind === "memory") {
    return "memory";
  }
  if (binding?.kind === "workflow_input") {
    return "workflow_input";
  }
  if (binding?.kind === "workflow_variable") {
    return "workflow_variable";
  }
  return "context";
};

const schemaPropertyEnum = (property: Record<string, unknown> | null) =>
  Array.isArray(property?.enum)
    ? property.enum.map((value) => String(value)).filter(Boolean)
    : [];

const schemaPropertyDefault = (property: Record<string, unknown> | null) => {
  if (!property || !Object.prototype.hasOwnProperty.call(property, "default")) {
    return "";
  }
  const value = property.default;
  if (typeof value === "string") {
    return value;
  }
  if (value === null || value === undefined) {
    return "";
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const inspectorPanelClassName =
  "h-full overflow-auto px-2.5 py-2.5 text-text-hi [&_.border-slate-100]:border-white/8 [&_.border-slate-200]:border-subtle [&_.border-slate-300]:border-subtle [&_.border-sky-200]:border-sky-300/25 [&_.border-emerald-200]:border-emerald-300/25 [&_.border-amber-200]:border-amber-300/25 [&_.border-rose-200]:border-rose-300/25 [&_.bg-slate-50]:bg-surface-1 [&_.bg-slate-100]:bg-surface-1 [&_.bg-white]:bg-surface-1 [&_.bg-sky-50]:bg-accent-sky [&_.bg-sky-100]:bg-accent-sky [&_.bg-emerald-50]:bg-accent-emerald [&_.bg-emerald-100]:bg-accent-emerald [&_.bg-rose-50]:bg-accent-rose [&_.bg-rose-100]:bg-accent-rose [&_.bg-amber-50]:bg-accent-amber [&_.bg-amber-100]:bg-accent-amber [&_.text-slate-900]:text-text-hi [&_.text-slate-800]:text-text-hi [&_.text-slate-700]:text-text-md [&_.text-slate-600]:text-text-md [&_.text-text-lo]:text-text-lo [&_.text-sky-700]:text-text-sky-token [&_.text-emerald-700]:text-text-emerald-token [&_.text-rose-700]:text-text-rose-token [&_.text-amber-700]:text-text-amber-token [&_.text-amber-800]:text-text-amber-token [&_.text-amber-900]:text-amber-50 [&_input]:text-text-hi [&_select]:text-text-hi [&_textarea]:text-text-hi [&_code]:rounded-md [&_code]:bg-black/20 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-text-sky-token";

export default function StudioNodeInspector({
  selectedDagNode,
  selectedCapability,
  agentDefinitions = [],
  selectedDagNodeStatus,
  inputFields,
  outputSchemaFields,
  activeComposerIssueFocus,
  inspectorBindingRefs,
  visualChainNodes,
  outputPathSuggestionsForNode,
  contextPathSuggestions,
  workflowInterface,
  autoWireNodeBindings,
  quickFixNodeBindings,
  setSelectedDagNodeId,
  capabilityIdOptionsId,
  compactMode = false,
  onDeleteNode,
  updateNodeBasics,
  setVisualBindingMode,
  clearVisualBinding,
  removeCustomInputField,
  addCustomInputField,
  updateVisualBindingSourceNode,
  updateVisualBindingPath,
  updateVisualBindingLiteral,
  updateVisualBindingContextPath,
  updateVisualBindingMemory,
  updateVisualBindingWorkflowInput,
  updateVisualBindingWorkflowVariable,
  setVisualBindingFromPrevious,
  addNodeOutput,
  upsertNodeOutputFromSchema,
  updateNodeOutput,
  removeNodeOutput,
  addNodeVariable,
  updateNodeVariable,
  removeNodeVariable,
  updateNodeControlConfig,
  addSwitchCase,
  updateSwitchCase,
  removeSwitchCase,
}: StudioNodeInspectorProps) {
  const [pendingInputField, setPendingInputField] = useState("");

  if (!selectedDagNode) {
    return (
      <section className="rounded-[22px] border border-dashed border-subtle bg-gradient-panel-deep px-4 py-4 text-sm text-text-md shadow-[0_18px_44px_rgba(2,8,23,0.18)]">
        Select a node to configure its inputs, outputs, and design variables.
      </section>
    );
  }

  const isControlNode = selectedDagNode.nodeKind === "control";
  const isAgentNode = selectedDagNode.nodeKind === "agent";
  const agentDefinition = isAgentNode
    ? agentDefinitions.find((def) => def.id === selectedDagNode.agentDefinitionId) || null
    : null;
  const controlConfig = selectedDagNode.controlConfig || {
    expression: "",
    trueLabel: "",
    falseLabel: "",
    parallelMode: "fan_out" as const,
    switchCases: [],
  };

  return (
    <section
      className={`${inspectorPanelClassName} ${
        compactMode ? "px-2.5 py-2.5 [&_h2]:text-[20px]" : ""
      }`.trim()}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold tracking-tight text-text-hi">{selectedDagNode.taskName}</h2>
          <div className="truncate text-[10px] text-text-lo">{selectedDagNode.capabilityId}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            className="rounded-lg border border-subtle bg-surface-1 px-2 py-1 text-[10px] font-semibold text-text-md transition hover:text-text-hi"
            onClick={() => autoWireNodeBindings(selectedDagNode.id)}
            title="Auto-wire inputs"
          >
            Wire
          </button>
          <button
            className="rounded-lg border border-subtle bg-surface-1 px-2 py-1 text-[10px] font-semibold text-text-md transition hover:text-text-hi"
            onClick={() => quickFixNodeBindings(selectedDagNode.id)}
            title="Quick fix inputs"
          >
            Fix
          </button>
          {onDeleteNode ? (
            <button
              className="rounded-lg border border-rose-300/20 bg-accent-rose px-2 py-1 text-[10px] font-semibold text-text-rose-token transition hover:border-rose-300/35"
              onClick={() => onDeleteNode(selectedDagNode.id)}
              title="Delete node"
            >
              Del
            </button>
          ) : null}
        </div>
      </div>

      <div className="mt-2 grid gap-2">
        <label className="block">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
            Task Name
          </div>
          <input
            className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-900 outline-none transition focus:border-slate-400 focus:bg-white"
            value={selectedDagNode.taskName}
            onChange={(event) =>
              updateNodeBasics(selectedDagNode.id, { taskName: event.target.value })
            }
          />
        </label>
        <label className="block">
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
            {isControlNode ? "Control Node Id" : "Capability Id"}
          </div>
          <input
            className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-900 outline-none transition focus:border-slate-400 focus:bg-white"
            list={capabilityIdOptionsId}
            value={selectedDagNode.capabilityId}
            disabled={isControlNode}
            onChange={(event) =>
              updateNodeBasics(selectedDagNode.id, { capabilityId: event.target.value })
            }
          />
        </label>
        <label className="block">
          <div className="flex items-center justify-between gap-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
              Primary Output Path
            </div>
            <div className="text-xs text-text-lo">
              {selectedDagNode.outputs.length} extra output{selectedDagNode.outputs.length === 1 ? "" : "s"}
            </div>
          </div>
          <input
            className="mt-1 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-900 outline-none transition focus:border-slate-400 focus:bg-white"
            value={selectedDagNode.outputPath}
            onChange={(event) =>
              updateNodeBasics(selectedDagNode.id, { outputPath: event.target.value })
            }
          />
        </label>
      </div>

      {isAgentNode ? (
        <div className="mt-5 rounded-2xl border border-violet-200 bg-violet-50/70 p-3.5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-violet-700">
            Agent Profile
          </div>
          {agentDefinition ? (
            <div className="mt-2">
              <div className="text-sm font-semibold text-violet-900">{agentDefinition.name}</div>
              {agentDefinition.description ? (
                <div className="mt-1 text-xs text-violet-800">{agentDefinition.description}</div>
              ) : null}
              {agentDefinition.allowed_capability_ids.length > 0 ? (
                <div className="mt-2">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-600">
                    Tools ({agentDefinition.allowed_capability_ids.length})
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {agentDefinition.allowed_capability_ids.slice(0, 6).map((id) => (
                      <span
                        key={id}
                        className="rounded-full border border-violet-200 bg-violet-100 px-2 py-0.5 text-[10px] text-violet-700"
                      >
                        {id}
                      </span>
                    ))}
                    {agentDefinition.allowed_capability_ids.length > 6 ? (
                      <span className="rounded-full border border-violet-200 bg-violet-100 px-2 py-0.5 text-[10px] text-violet-700">
                        +{agentDefinition.allowed_capability_ids.length - 6} more
                      </span>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mt-2 text-xs text-violet-700">
              Agent definition not loaded. ID: {selectedDagNode.agentDefinitionId || "unknown"}
            </div>
          )}
          <div className="mt-3 text-[11px] text-violet-700">
            Instructions and tool list are injected from the agent profile at compile time.
          </div>
        </div>
      ) : null}

      {isControlNode ? (
        <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50/70 p-3.5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-700">
            Control Flow
          </div>
          <div className="mt-1 text-xs text-amber-900">
            <code>if</code>, <code>if_else</code>, and <code>parallel</code> compile into
            execution gates and dependency structure. <code>switch</code> is still authoring-only.
          </div>
          <div className="mt-2 text-[11px] text-amber-800">
            References: <code>context.*</code>, <code>workflow.input.*</code>,{" "}
            <code>workflow.variable.*</code>, <code>step.{"{task}"}.*</code>. Operators:{" "}
            <code>==</code> <code>!=</code> <code>&gt;</code> <code>&lt;</code> <code>&gt;=</code>{" "}
            <code>&lt;=</code> <code>contains</code> <code>startswith</code> <code>endswith</code>.
            Combine clauses with <code>and</code> / <code>or</code>.
          </div>
          <div className="mt-4 grid gap-3">
            <label className="block">
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                Expression
              </div>
              <input
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                value={controlConfig.expression || ""}
                onChange={(event) =>
                  updateNodeControlConfig(selectedDagNode.id, { expression: event.target.value })
                }
                placeholder={
                  selectedDagNode.controlKind === "parallel"
                    ? "Optional branch grouping note"
                    : "workflow.variable.should_publish == true"
                }
              />
            </label>

            {selectedDagNode.controlKind === "if_else" ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                    True Label
                  </div>
                  <input
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                    value={controlConfig.trueLabel || ""}
                    onChange={(event) =>
                      updateNodeControlConfig(selectedDagNode.id, { trueLabel: event.target.value })
                    }
                    placeholder="Approved"
                  />
                </label>
                <label className="block">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                    False Label
                  </div>
                  <input
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                    value={controlConfig.falseLabel || ""}
                    onChange={(event) =>
                      updateNodeControlConfig(selectedDagNode.id, { falseLabel: event.target.value })
                    }
                    placeholder="Rejected"
                  />
                </label>
              </div>
            ) : null}

            {selectedDagNode.controlKind === "parallel" ? (
              <label className="block">
                <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                  Parallel Mode
                </div>
                <select
                  className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                  value={controlConfig.parallelMode || "fan_out"}
                  onChange={(event) =>
                    updateNodeControlConfig(selectedDagNode.id, {
                      parallelMode: event.target.value as "fan_out" | "fan_in",
                    })
                  }
                >
                  <option value="fan_out">Fan Out</option>
                  <option value="fan_in">Fan In</option>
                </select>
              </label>
            ) : null}

            {selectedDagNode.controlKind === "switch" ? (
              <div className="rounded-2xl border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                      Cases
                    </div>
                    <div className="mt-1 text-xs text-text-lo">Add labels and match values for each route.</div>
                  </div>
                  <button
                    className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-semibold text-slate-700"
                    onClick={() => addSwitchCase(selectedDagNode.id)}
                  >
                    Add Case
                  </button>
                </div>
                <div className="mt-3 space-y-3">
                  {(controlConfig.switchCases || []).map((item, index) => (
                    <div key={item.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
                        <label className="block">
                          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                            Case Label
                          </div>
                          <input
                            className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                            value={item.label}
                            onChange={(event) =>
                              updateSwitchCase(selectedDagNode.id, item.id, { label: event.target.value })
                            }
                            placeholder={`Case ${index + 1}`}
                          />
                        </label>
                        <label className="block">
                          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                            Match Value
                          </div>
                          <input
                            className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                            value={item.match}
                            onChange={(event) =>
                              updateSwitchCase(selectedDagNode.id, item.id, { match: event.target.value })
                            }
                            placeholder="approved"
                          />
                        </label>
                        <div className="flex items-end">
                          <button
                            className="rounded-full border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] font-semibold text-rose-700"
                            onClick={() => removeSwitchCase(selectedDagNode.id, item.id)}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="mt-5 border-t border-slate-100 pt-3.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
              Inputs
            </div>
            <div className="mt-1 text-xs text-text-lo">
              Schema-defined fields are listed automatically. Each field can point at context data, step outputs, literals, memory, or workflow interface bindings.
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px]">
            <div className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">
              required {selectedDagNodeStatus?.requiredCount || 0}
            </div>
            <div className="rounded-full bg-emerald-50 px-3 py-1 text-emerald-700">
              context keys {contextPathSuggestions.length}
            </div>
          </div>
        </div>

        <div className="mt-2.5 flex gap-2">
          <input
            className="flex-1 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:bg-white"
            value={pendingInputField}
            onChange={(event) => setPendingInputField(event.target.value)}
            placeholder="Add custom input field"
          />
          <button
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700"
            onClick={() => {
              const field = pendingInputField.trim();
              if (!field) {
                return;
              }
              addCustomInputField(selectedDagNode.id, field);
              setPendingInputField("");
            }}
          >
            Add
          </button>
        </div>

        <div className="mt-2.5 space-y-2">
          {inputFields.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-5 text-sm text-text-lo">
              No inputs configured for this node.
            </div>
          ) : null}
          {inputFields.map((status) => {
            const binding = selectedDagNode.inputBindings[status.field];
            const bindingMode = bindingModeForField(binding);
            const sourceNodes = visualChainNodes.filter((candidate) => candidate.id !== selectedDagNode.id);
            const sourcePathListId = `studio-inspector-${selectedDagNode.id}-${status.field}-source-path-options`;
            const contextPathListId = `studio-inspector-${selectedDagNode.id}-${status.field}-context-path-options`;
            const literalValue = binding?.kind === "literal" ? binding.value : "";
            const enumOptions = schemaPropertyEnum(status.schemaProperty);
            const schemaDefaultValue = schemaPropertyDefault(status.schemaProperty);
            const schemaType = status.schemaType.trim().toLowerCase();
            const selectedSourceNode =
              binding?.kind === "step_output"
                ? visualChainNodes.find((candidate) => candidate.id === binding.sourceNodeId) ||
                  sourceNodes[sourceNodes.length - 1]
                : sourceNodes[sourceNodes.length - 1];
            const sourcePathOptions = outputPathSuggestionsForNode(selectedSourceNode);

            return (
              <div
                key={`studio-inspector-${selectedDagNode.id}-${status.field}`}
                ref={(element) => {
                  inspectorBindingRefs.current[`${selectedDagNode.id}::${status.field}`] = element;
                }}
                className={`rounded-[18px] border px-3 py-2.5 ${
                  activeComposerIssueFocus?.nodeId === selectedDagNode.id &&
                  activeComposerIssueFocus?.field === status.field
                    ? "border-sky-300 bg-sky-50"
                    : "border-slate-200 bg-slate-50"
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="text-sm font-semibold text-slate-800">{status.field}</div>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] ${
                          status.required
                            ? "bg-slate-900 text-slate-50"
                            : status.custom
                              ? "border border-slate-300 bg-white text-slate-600"
                              : "bg-sky-50 text-sky-700"
                        }`}
                      >
                        {status.required ? "required" : status.custom ? "custom" : "optional"}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] ${
                          status.status === "missing"
                            ? "bg-rose-100 text-rose-700"
                            : status.status === "from_chain"
                              ? "bg-sky-100 text-sky-700"
                              : status.status === "from_context"
                                ? "bg-emerald-100 text-emerald-700"
                                : "bg-amber-100 text-amber-700"
                        }`}
                      >
                        {status.status}
                      </span>
                    </div>
                    <div className="mt-1 text-[11px] text-text-lo">
                      {status.schemaType}
                      {status.schemaDescription ? ` • ${status.schemaDescription}` : ""}
                    </div>
                    {enumOptions.length > 0 || schemaDefaultValue ? (
                      <div className="mt-1 text-[11px] text-text-lo">
                        {enumOptions.length > 0 ? `Allowed: ${enumOptions.join(", ")}` : ""}
                        {enumOptions.length > 0 && schemaDefaultValue ? " • " : ""}
                        {schemaDefaultValue ? `Default: ${schemaDefaultValue}` : ""}
                      </div>
                    ) : null}
                    <div className="mt-1 text-[11px] text-text-lo">{status.detail}</div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {status.status === "missing" && sourceNodes.length > 0 && bindingMode !== "from" ? (
                      <button
                        className="rounded-full border border-slate-300 px-2.5 py-1 text-[11px] text-slate-700"
                        onClick={() => setVisualBindingFromPrevious(selectedDagNode.id, status.field)}
                      >
                        Wire Prev
                      </button>
                    ) : null}
                    <button
                      className="rounded-full border border-slate-300 px-2.5 py-1 text-[11px] text-slate-700"
                      onClick={() => clearVisualBinding(selectedDagNode.id, status.field)}
                    >
                      Clear
                    </button>
                    {status.custom ? (
                      <button
                        className="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-[11px] text-rose-700"
                        onClick={() => removeCustomInputField(selectedDagNode.id, status.field)}
                      >
                        Remove
                      </button>
                    ) : null}
                  </div>
                </div>

                <div className="mt-2.5 flex items-center gap-2">
                  <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                    Mapping
                  </label>
                  <select
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                    value={bindingMode}
                    onChange={(event) =>
                      setVisualBindingMode(
                        selectedDagNode.id,
                        status.field,
                        event.target.value as
                          | "context"
                          | "from"
                          | "literal"
                          | "memory"
                          | "workflow_input"
                          | "workflow_variable"
                      )
                    }
                  >
                    <option value="context">Context data</option>
                    <option value="from" disabled={sourceNodes.length === 0}>
                      Step output
                    </option>
                    <option value="literal">Literal value</option>
                    <option value="memory">Memory</option>
                    <option value="workflow_input">Workflow input</option>
                    <option value="workflow_variable">Workflow variable</option>
                  </select>
                </div>

                {bindingMode === "from" && binding?.kind === "step_output" ? (
                  <div className="mt-3 grid gap-2">
                    <select
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                      value={binding.sourceNodeId}
                      onChange={(event) =>
                        updateVisualBindingSourceNode(selectedDagNode.id, status.field, event.target.value)
                      }
                    >
                      {sourceNodes.map((candidateNode) => (
                        <option
                          key={`studio-inspector-source-${selectedDagNode.id}-${status.field}-${candidateNode.id}`}
                          value={candidateNode.id}
                        >
                          {candidateNode.taskName} ({candidateNode.capabilityId})
                        </option>
                      ))}
                    </select>
                    <input
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                      value={binding.sourcePath}
                      onChange={(event) =>
                        updateVisualBindingPath(selectedDagNode.id, status.field, event.target.value)
                      }
                      list={sourcePathListId}
                      placeholder="source output path"
                    />
                    <datalist id={sourcePathListId}>
                      {sourcePathOptions.map((option) => (
                        <option key={`${sourcePathListId}-${option}`} value={option} />
                      ))}
                    </datalist>
                  </div>
                ) : null}

                {bindingMode === "literal" ? (
                  <div className="mt-3 grid gap-2">
                    {enumOptions.length > 0 ? (
                      <select
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                        value={literalValue}
                        onChange={(event) =>
                          updateVisualBindingLiteral(selectedDagNode.id, status.field, event.target.value)
                        }
                      >
                        <option value="">Select value</option>
                        {enumOptions.map((option) => (
                          <option key={`studio-literal-${status.field}-${option}`} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    ) : schemaType === "boolean" ? (
                      <select
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                        value={literalValue}
                        onChange={(event) =>
                          updateVisualBindingLiteral(selectedDagNode.id, status.field, event.target.value)
                        }
                      >
                        <option value="">Select boolean</option>
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : schemaType === "number" || schemaType === "integer" ? (
                      <input
                        type="number"
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                        value={literalValue}
                        onChange={(event) =>
                          updateVisualBindingLiteral(selectedDagNode.id, status.field, event.target.value)
                        }
                        placeholder="literal number"
                      />
                    ) : schemaType === "object" || schemaType === "array" ? (
                      <textarea
                        className="min-h-[96px] w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                        value={literalValue}
                        onChange={(event) =>
                          updateVisualBindingLiteral(selectedDagNode.id, status.field, event.target.value)
                        }
                        placeholder={schemaType === "array" ? '[{"key":"value"}]' : '{"key":"value"}'}
                      />
                    ) : (
                      <input
                        className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                        value={literalValue}
                        onChange={(event) =>
                          updateVisualBindingLiteral(selectedDagNode.id, status.field, event.target.value)
                        }
                        placeholder="literal value"
                      />
                    )}
                    <div className="text-[11px] text-text-lo">
                      Literal values are stored as text in the draft and coerced by the target capability at run time.
                    </div>
                  </div>
                ) : null}

                {bindingMode === "context" ? (
                  <div className="mt-3 grid gap-2">
                    <input
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                      list={contextPathListId}
                      value={binding?.kind === "context" ? binding.path : status.field}
                      onChange={(event) =>
                        updateVisualBindingContextPath(selectedDagNode.id, status.field, event.target.value)
                      }
                      placeholder="context path"
                    />
                    <datalist id={contextPathListId}>
                      {contextPathSuggestions.map((option) => (
                        <option key={`${contextPathListId}-${option}`} value={option} />
                      ))}
                    </datalist>
                    <div className="text-[11px] text-text-lo">
                      Select a value from <code>context_json</code> or type a custom path.
                    </div>
                  </div>
                ) : null}

                {bindingMode === "memory" ? (
                  <div className="mt-3 grid gap-2">
                    <div className="grid gap-2 sm:grid-cols-3">
                      <select
                        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                        value={binding?.kind === "memory" ? binding.scope : "job"}
                        onChange={(event) =>
                          updateVisualBindingMemory(selectedDagNode.id, status.field, {
                            scope: event.target.value as "job" | "user" | "global",
                          })
                        }
                      >
                        <option value="job">job</option>
                        <option value="user">user</option>
                        <option value="global">global</option>
                      </select>
                      <input
                        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                        value={binding?.kind === "memory" ? binding.name : "task_outputs"}
                        onChange={(event) =>
                          updateVisualBindingMemory(selectedDagNode.id, status.field, {
                            name: event.target.value,
                          })
                        }
                        placeholder="memory name"
                      />
                      <input
                        className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                        value={binding?.kind === "memory" ? binding.key || "" : ""}
                        onChange={(event) =>
                          updateVisualBindingMemory(selectedDagNode.id, status.field, {
                            key: event.target.value,
                          })
                        }
                        placeholder="optional key"
                      />
                    </div>
                  </div>
                ) : null}

                {bindingMode === "workflow_input" ? (
                  <div className="mt-3 grid gap-2">
                    <select
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                      value={binding?.kind === "workflow_input" ? binding.inputKey : ""}
                      onChange={(event) =>
                        updateVisualBindingWorkflowInput(
                          selectedDagNode.id,
                          status.field,
                          event.target.value
                        )
                      }
                    >
                      <option value="">Select workflow input</option>
                      {workflowInterface.inputs.map((input) => (
                        <option key={`workflow-input-${input.id}`} value={input.key}>
                          {input.key || input.label || "Untitled input"}
                        </option>
                      ))}
                    </select>
                    <div className="text-[11px] text-text-lo">
                      Bind this field to a workflow-level input.
                    </div>
                  </div>
                ) : null}

                {bindingMode === "workflow_variable" ? (
                  <div className="mt-3 grid gap-2">
                    <select
                      className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                      value={binding?.kind === "workflow_variable" ? binding.variableKey : ""}
                      onChange={(event) =>
                        updateVisualBindingWorkflowVariable(
                          selectedDagNode.id,
                          status.field,
                          event.target.value
                        )
                      }
                    >
                      <option value="">Select workflow variable</option>
                      {workflowInterface.variables.map((variable) => (
                        <option key={`workflow-variable-${variable.id}`} value={variable.key}>
                          {variable.key || "Untitled variable"}
                        </option>
                      ))}
                    </select>
                    <div className="text-[11px] text-text-lo">
                      Bind this field to a workflow-level variable.
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-6 border-t border-slate-100 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
              Outputs
            </div>
            <div className="mt-1 text-xs text-text-lo">
              Model the fields other nodes should be able to reference from this step.
            </div>
          </div>
          <button
            className="rounded-full border border-slate-300 px-3 py-1.5 text-[11px] font-semibold text-slate-700"
            onClick={() => addNodeOutput(selectedDagNode.id)}
          >
            Add Output
          </button>
        </div>

        {outputSchemaFields.length > 0 ? (
          <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-slate-800">Available Schema Outputs</div>
                <div className="mt-1 text-[11px] text-text-lo">
                  Derived from the capability output schema for {selectedCapability?.id || selectedDagNode.capabilityId}.
                </div>
              </div>
              <div className="rounded-full bg-white px-3 py-1 text-[11px] text-slate-600">
                {outputSchemaFields.length} field{outputSchemaFields.length === 1 ? "" : "s"}
              </div>
            </div>
            <div className="mt-3 space-y-2">
              {outputSchemaFields.map((field) => (
                <div
                  key={`studio-schema-output-${selectedDagNode.id}-${field.path}`}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2"
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="text-sm font-semibold text-slate-800">{field.path}</div>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-slate-600">
                        {field.type}
                      </span>
                    </div>
                    {field.description ? (
                      <div className="mt-1 text-[11px] text-text-lo">{field.description}</div>
                    ) : null}
                  </div>
                  <button
                    className="rounded-full border border-slate-300 px-3 py-1 text-[11px] font-semibold text-slate-700"
                    onClick={() => upsertNodeOutputFromSchema(selectedDagNode.id, field)}
                  >
                    Add Alias
                  </button>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="mt-3 space-y-3">
          {selectedDagNode.outputs.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-5 text-sm text-text-lo">
              No extra outputs defined. Downstream nodes can still use the primary output path above.
            </div>
          ) : null}
          {selectedDagNode.outputs.map((output) => (
            <div
              key={`studio-node-output-${selectedDagNode.id}-${output.id}`}
              className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3"
            >
              <div className="grid gap-2">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-800">Named Output</div>
                  <button
                    className="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-[11px] text-rose-700"
                    onClick={() => removeNodeOutput(selectedDagNode.id, output.id)}
                  >
                    Remove
                  </button>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <input
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                    value={output.name}
                    onChange={(event) =>
                      updateNodeOutput(selectedDagNode.id, output.id, { name: event.target.value })
                    }
                    placeholder="output name"
                  />
                  <input
                    className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                    value={output.path}
                    onChange={(event) =>
                      updateNodeOutput(selectedDagNode.id, output.id, { path: event.target.value })
                    }
                    placeholder="output path used in references"
                  />
                </div>
                <input
                  className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                  value={output.description || ""}
                  onChange={(event) =>
                    updateNodeOutput(selectedDagNode.id, output.id, {
                      description: event.target.value,
                    })
                  }
                  placeholder="optional description"
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 border-t border-slate-100 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-lo">
              Variables
            </div>
            <div className="mt-1 text-xs text-text-lo">
              Design-time notes and aliases for this node. These are kept in the Studio draft only.
            </div>
          </div>
          <button
            className="rounded-full border border-slate-300 px-3 py-1.5 text-[11px] font-semibold text-slate-700"
            onClick={() => addNodeVariable(selectedDagNode.id)}
          >
            Add Variable
          </button>
        </div>

        <div className="mt-3 space-y-3">
          {selectedDagNode.variables.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-5 text-sm text-text-lo">
              No variables yet. Add names and values to capture local workflow intent while designing.
            </div>
          ) : null}
          {selectedDagNode.variables.map((variable) => (
            <div
              key={`studio-node-variable-${selectedDagNode.id}-${variable.id}`}
              className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-slate-800">Variable</div>
                <button
                  className="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 text-[11px] text-rose-700"
                  onClick={() => removeNodeVariable(selectedDagNode.id, variable.id)}
                >
                  Remove
                </button>
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <input
                  className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                  value={variable.key}
                  onChange={(event) =>
                    updateNodeVariable(selectedDagNode.id, variable.id, { key: event.target.value })
                  }
                  placeholder="variable name"
                />
                <input
                  className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                  value={variable.value}
                  onChange={(event) =>
                    updateNodeVariable(selectedDagNode.id, variable.id, { value: event.target.value })
                  }
                  placeholder="variable value"
                />
              </div>
              <input
                className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                value={variable.description || ""}
                onChange={(event) =>
                  updateNodeVariable(selectedDagNode.id, variable.id, {
                    description: event.target.value,
                  })
                }
                placeholder="optional description"
              />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
