"use client";

import type React from "react";

import {
  WorkflowNodePlateIcon,
  resolveWorkflowNodeVisual,
} from "../workflow/WorkflowNodeIcon";

type CanvasPoint = {
  x: number;
  y: number;
};

type ComposerDraftEdge = {
  fromNodeId: string;
  toNodeId: string;
  branchLabel?: string;
};

type ComposerDraftNode = {
  id: string;
  taskName: string;
  capabilityId: string;
  outputPath: string;
  nodeKind?: "capability" | "control";
  controlKind?: "if" | "if_else" | "switch" | "parallel" | null;
};

type DagCanvasEdge = {
  fromNodeId: string;
  toNodeId: string;
  edgeKey: string;
  fromTaskName: string;
  toTaskName: string;
  path: string;
  midX: number;
  midY: number;
  branchLabel?: string;
};

type DagCanvasNode = {
  node: ComposerDraftNode;
  position: CanvasPoint;
};

type DagConnectorDragState = {
  sourceNodeId: string;
  x: number;
  y: number;
  branchLabel?: string;
  sourcePortY?: number;
};

type ComposerDagCanvasProps = {
  visualChainNodes: ComposerDraftNode[];
  dagEdgeDraftSourceNodeId: string | null;
  setDagEdgeDraftSourceNodeId: React.Dispatch<React.SetStateAction<string | null>>;
  setDagConnectorDrag: React.Dispatch<React.SetStateAction<DagConnectorDragState | null>>;
  setDagConnectorHoverTargetNodeId: React.Dispatch<React.SetStateAction<string | null>>;
  autoLayoutDagCanvas: () => void;
  dagCanvasViewportRef: React.RefObject<HTMLDivElement | null>;
  dagCanvasRef: React.RefObject<HTMLDivElement | null>;
  dagCanvasSurface: { width: number; height: number };
  dagCanvasEdges: DagCanvasEdge[];
  hoveredDagEdgeKey: string | null;
  setHoveredDagEdgeKey: React.Dispatch<React.SetStateAction<string | null>>;
  removeDagEdge: (fromNodeId: string, toNodeId: string) => void;
  dagConnectorPreview: { path: string } | null;
  dagCanvasNodes: DagCanvasNode[];
  composerDraftEdges: ComposerDraftEdge[];
  dagNodeAdjacency: {
    incoming: Record<string, number>;
    outgoing: Record<string, number>;
  };
  visualChainNodeStatusById: Map<
    string,
    {
      missingCount: number;
      requiredCount: number;
    }
  >;
  selectedDagNodeId: string | null;
  setSelectedDagNodeId: React.Dispatch<React.SetStateAction<string | null>>;
  dagConnectorDrag: DagConnectorDragState | null;
  dagCanvasDraggingNodeId: string | null;
  dagConnectorHoverTargetNodeId: string | null;
  addDagEdge: (fromNodeId: string, toNodeId: string, branchLabel?: string) => void;
  beginDagNodeDrag: (event: React.MouseEvent<HTMLDivElement>, nodeId: string) => void;
  isInteractiveCanvasTarget: (target: EventTarget | null) => boolean;
  beginDagConnectorDrag: (
    event: React.MouseEvent<HTMLButtonElement>,
    nodeId: string,
    options?: { branchLabel?: string; sourcePortY?: number }
  ) => void;
  centerDagNodeInView: (nodeId: string) => void;
  nodeWidth: number;
  nodeHeight: number;
  dagCanvasZoom?: number;
  showToolbar?: boolean;
  showBlueprintPreview?: boolean;
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  zoomInDisabled?: boolean;
  zoomOutDisabled?: boolean;
  onRunWorkflow?: () => void;
  runWorkflowPending?: boolean;
  runWorkflowDisabled?: boolean;
};

const toolbarButtonClassName =
  "inline-flex h-8 items-center rounded-lg border border-black/15 bg-[rgba(54,68,84,0.94)] px-2.5 text-[10px] font-semibold tracking-[0.04em] text-slate-50 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] transition hover:border-white/18 hover:bg-[rgba(61,77,95,0.98)] disabled:cursor-not-allowed disabled:opacity-40";

type BlueprintPreviewNode = {
  id: string;
  x: number;
  y: number;
  title: string;
  subtitle: string;
  caption?: string;
  tone: "slate" | "sky" | "emerald" | "amber" | "rose" | "steel";
  capabilityId: string;
  nodeKind?: "capability" | "control";
  controlKind?: "if" | "if_else" | "switch" | "parallel" | null;
};

type BlueprintPreviewEdge = {
  id: string;
  path: string;
  color: string;
  label?: string;
  labelX?: number;
  labelY?: number;
};

const hexToRgba = (hex: string, alpha: number) => {
  const normalized = hex.replace("#", "");
  const expanded =
    normalized.length === 3
      ? normalized
          .split("")
          .map((char) => `${char}${char}`)
          .join("")
      : normalized;
  const value = Number.parseInt(expanded, 16);
  if (!Number.isFinite(value)) {
    return `rgba(148, 163, 184, ${alpha})`;
  }
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const blueprintToneStyles: Record<
  BlueprintPreviewNode["tone"],
  {
    border: string;
    background: string;
    caption: string;
    shadow: string;
    subtitle: string;
    title: string;
  }
> = {
  slate: {
    border: "#93abc8",
    background: "linear-gradient(180deg, #a6bbd6 0%, #8096b6 100%)",
    caption: "rgba(241,245,249,0.9)",
    shadow: "0 14px 28px rgba(30, 41, 59, 0.28)",
    subtitle: "rgba(241,245,249,0.92)",
    title: "#f8fafc",
  },
  sky: {
    border: "#4da9ea",
    background: "linear-gradient(180deg, #c9ecff 0%, #9fd6ff 100%)",
    caption: "rgba(71,85,105,0.9)",
    shadow: "0 14px 28px rgba(59, 130, 246, 0.18)",
    subtitle: "rgba(30,41,59,0.88)",
    title: "#0f172a",
  },
  emerald: {
    border: "#33a26f",
    background: "linear-gradient(180deg, #b6efd3 0%, #7ee1b6 100%)",
    caption: "rgba(22,101,52,0.88)",
    shadow: "0 14px 28px rgba(16, 185, 129, 0.16)",
    subtitle: "rgba(20,83,45,0.86)",
    title: "#052e16",
  },
  amber: {
    border: "#d69a2a",
    background: "linear-gradient(180deg, #ffd783 0%, #ffc45a 100%)",
    caption: "rgba(120,53,15,0.86)",
    shadow: "0 14px 28px rgba(217, 119, 6, 0.16)",
    subtitle: "rgba(120,53,15,0.86)",
    title: "#111827",
  },
  rose: {
    border: "#d87484",
    background: "linear-gradient(180deg, #f8c5cf 0%, #f3a7b7 100%)",
    caption: "rgba(127,29,29,0.86)",
    shadow: "0 14px 28px rgba(244, 63, 94, 0.14)",
    subtitle: "rgba(127,29,29,0.84)",
    title: "#111827",
  },
  steel: {
    border: "#94a9c7",
    background: "linear-gradient(180deg, #a4b8d5 0%, #7c94b6 100%)",
    caption: "rgba(241,245,249,0.9)",
    shadow: "0 14px 28px rgba(51, 65, 85, 0.24)",
    subtitle: "rgba(241,245,249,0.92)",
    title: "#f8fafc",
  },
};

type ComposerPortTone = "default" | "success" | "danger";

type ComposerNodePort = {
  key: string;
  label: string;
  branchLabel?: string;
  tone: ComposerPortTone;
  y: number;
};

const portToneStyles: Record<
  ComposerPortTone,
  { background: string; border: string; text: string }
> = {
  default: {
    background: "#d7e9fb",
    border: "#6fb7ea",
    text: "#215e90",
  },
  success: {
    background: "#93ecac",
    border: "#2fa85b",
    text: "#14532d",
  },
  danger: {
    background: "#f7a6b1",
    border: "#d65c71",
    text: "#881337",
  },
};

const toneForVisual = (
  visual: ReturnType<typeof resolveWorkflowNodeVisual>
): BlueprintPreviewNode["tone"] => {
  if (visual.tone === "llm" || visual.tone === "io") {
    return "sky";
  }
  if (visual.tone === "transform") {
    return "emerald";
  }
  if (visual.tone === "validate") {
    return "rose";
  }
  if (visual.tone === "memory") {
    return "steel";
  }
  if (visual.tone === "control" || visual.tone === "render") {
    return "amber";
  }
  return "slate";
};

const subtitleForNode = (
  node: ComposerDraftNode,
  visual: ReturnType<typeof resolveWorkflowNodeVisual>
) => {
  if (node.nodeKind === "control") {
    return "Logic Gate";
  }
  if (visual.tone === "llm") {
    return "LLM Request";
  }
  if (visual.tone === "validate") {
    return "Schema Check";
  }
  if (visual.tone === "memory") {
    return "State Storage";
  }
  if (visual.tone === "render") {
    return "Document Process";
  }
  if (visual.tone === "transform") {
    return "Data Processing";
  }
  if (visual.tone === "io") {
    return "Integration";
  }
  if (visual.tone === "code") {
    return "Code Action";
  }
  return "Workflow Step";
};

const statusForNode = (
  node: ComposerDraftNode,
  missingCount: number,
  requiredCount: number
) => {
  if (node.nodeKind === "control") {
    return {
      badgeBackground: "rgba(217, 119, 6, 0.92)",
      badgeColor: "#fff7ed",
      badgeLabel: "•",
      label: node.controlKind === "parallel" ? "Branch Group" : "Conditional Logic",
    };
  }
  if (missingCount > 0) {
    return {
      badgeBackground: "rgba(220, 38, 38, 0.92)",
      badgeColor: "#fff1f2",
      badgeLabel: "!",
      label: `${missingCount} missing field${missingCount === 1 ? "" : "s"}`,
    };
  }
  if (requiredCount > 0) {
    return {
      badgeBackground: "rgba(37, 99, 235, 0.88)",
      badgeColor: "#eff6ff",
      badgeLabel: "✓",
      label: "Ready",
    };
  }
  return {
    badgeBackground: "rgba(71, 85, 105, 0.82)",
    badgeColor: "#e2e8f0",
    badgeLabel: "•",
    label: "Configured",
  };
};

const outputPortsForNode = (
  node: ComposerDraftNode,
  visual: ReturnType<typeof resolveWorkflowNodeVisual>,
  nodeHeight: number
): ComposerNodePort[] => {
  if (node.nodeKind === "control" && node.controlKind === "if_else") {
    return [
      {
        key: "true",
        label: "True",
        branchLabel: "true",
        tone: "success",
        y: 40,
      },
      {
        key: "false",
        label: "False",
        branchLabel: "false",
        tone: "danger",
        y: 64,
      },
    ];
  }
  if (node.nodeKind === "control") {
    return [
      {
        key: "branch",
        label: "Branch",
        tone: "default",
        y: nodeHeight / 2,
      },
    ];
  }
  if (visual.tone === "validate") {
    return [{ key: "result", label: "Result", tone: "danger", y: nodeHeight / 2 }];
  }
  if (visual.tone === "memory") {
    return [{ key: "state", label: "State", tone: "default", y: nodeHeight / 2 }];
  }
  return [{ key: "output", label: "Output", tone: "default", y: nodeHeight / 2 }];
};

const emptyBlueprintNodes: BlueprintPreviewNode[] = [
  {
    id: "preview-control",
    x: 170,
    y: 270,
    title: "Conditional Check",
    subtitle: "Logic Gate",
    caption: "Conditional Logic",
    tone: "amber",
    capabilityId: "workflow.control",
    nodeKind: "control",
    controlKind: "if_else",
  },
  {
    id: "preview-summarize",
    x: 520,
    y: 110,
    title: "Summarize Text",
    subtitle: "LLM Request",
    caption: "Ready",
    tone: "sky",
    capabilityId: "llm.text.generate",
  },
  {
    id: "preview-reason",
    x: 520,
    y: 245,
    title: "GPT-4 Reasoning",
    subtitle: "LLM Request",
    caption: "Ready",
    tone: "sky",
    capabilityId: "llm.reason",
  },
  {
    id: "preview-process-top",
    x: 890,
    y: 250,
    title: "Processing PDF",
    subtitle: "Document Process",
    caption: "Configured",
    tone: "amber",
    capabilityId: "document.process",
  },
  {
    id: "preview-extract",
    x: 520,
    y: 430,
    title: "Extract Data",
    subtitle: "Data Processing",
    caption: "Ready",
    tone: "emerald",
    capabilityId: "document.process",
  },
  {
    id: "preview-process-bottom",
    x: 520,
    y: 610,
    title: "Processing PDF",
    subtitle: "Document Process",
    caption: "Configured",
    tone: "amber",
    capabilityId: "document.process",
  },
  {
    id: "preview-validate",
    x: 980,
    y: 450,
    title: "Data Validation",
    subtitle: "Schema Check",
    caption: "Failed: Missing Fields",
    tone: "rose",
    capabilityId: "validation.schema",
  },
  {
    id: "preview-notify",
    x: 1330,
    y: 455,
    title: "Notify Admin",
    subtitle: "Workflow Step",
    caption: "Configured",
    tone: "slate",
    capabilityId: "notification.send",
  },
];

const emptyBlueprintEdges: BlueprintPreviewEdge[] = [
  {
    id: "control-summary",
    path: "M 390 315 C 460 315, 450 150, 520 150",
    color: "rgba(116, 137, 158, 0.94)",
    label: "If true",
    labelX: 430,
    labelY: 236,
  },
  {
    id: "control-reason",
    path: "M 390 325 C 450 325, 455 285, 520 285",
    color: "rgba(116, 137, 158, 0.94)",
  },
  {
    id: "control-extract",
    path: "M 390 338 C 455 338, 450 470, 520 470",
    color: "rgba(116, 137, 158, 0.94)",
    label: "Else",
    labelX: 428,
    labelY: 394,
  },
  {
    id: "control-process-bottom",
    path: "M 390 348 C 450 348, 455 650, 520 650",
    color: "rgba(116, 137, 158, 0.94)",
  },
  {
    id: "reason-process-top",
    path: "M 740 285 C 810 285, 820 285, 890 285",
    color: "rgba(124, 146, 168, 0.92)",
  },
  {
    id: "process-top-extract",
    path: "M 1110 290 C 1170 290, 1175 420, 740 470",
    color: "rgba(124, 146, 168, 0.72)",
  },
  {
    id: "extract-validate",
    path: "M 740 470 C 860 470, 860 485, 980 485",
    color: "rgba(116, 137, 158, 0.94)",
  },
  {
    id: "process-bottom-validate",
    path: "M 740 650 C 860 650, 860 500, 980 500",
    color: "rgba(116, 137, 158, 0.94)",
  },
  {
    id: "validate-notify",
    path: "M 1200 490 C 1260 490, 1270 490, 1330 490",
    color: "rgba(124, 146, 168, 0.9)",
  },
];

export default function ComposerDagCanvas({
  visualChainNodes,
  dagEdgeDraftSourceNodeId,
  setDagEdgeDraftSourceNodeId,
  setDagConnectorDrag,
  setDagConnectorHoverTargetNodeId,
  autoLayoutDagCanvas,
  dagCanvasViewportRef,
  dagCanvasRef,
  dagCanvasSurface,
  dagCanvasEdges,
  hoveredDagEdgeKey,
  setHoveredDagEdgeKey,
  removeDagEdge,
  dagConnectorPreview,
  dagCanvasNodes,
  composerDraftEdges,
  dagNodeAdjacency,
  visualChainNodeStatusById,
  selectedDagNodeId,
  setSelectedDagNodeId,
  dagConnectorDrag,
  dagCanvasDraggingNodeId,
  dagConnectorHoverTargetNodeId,
  addDagEdge,
  beginDagNodeDrag,
  isInteractiveCanvasTarget,
  beginDagConnectorDrag,
  centerDagNodeInView,
  nodeWidth,
  nodeHeight,
  dagCanvasZoom = 1,
  showToolbar = false,
  showBlueprintPreview = false,
  onZoomIn,
  onZoomOut,
  zoomInDisabled = false,
  zoomOutDisabled = false,
  onRunWorkflow,
  runWorkflowPending = false,
  runWorkflowDisabled = false,
}: ComposerDagCanvasProps) {
  const showEmptyBlueprint = showBlueprintPreview && visualChainNodes.length === 0;

  return (
    <div className="relative h-full overflow-hidden rounded-[18px] border border-[#7c8da3]/30 bg-[#566c80] shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_16px_40px_rgba(15,23,42,0.18)]">
      {showToolbar ? (
        <div className="pointer-events-none absolute right-4 top-4 z-20 flex justify-end">
          <div className="pointer-events-auto flex items-center gap-1.5 rounded-[14px] border border-black/15 bg-[rgba(53,67,83,0.88)] p-1.5 shadow-[0_10px_24px_rgba(15,23,42,0.18)] backdrop-blur">
            <button
              className={toolbarButtonClassName}
              onClick={onZoomIn}
              disabled={zoomInDisabled}
              type="button"
            >
              + Zoom
            </button>
            <button
              className={toolbarButtonClassName}
              onClick={onZoomOut}
              disabled={zoomOutDisabled}
              type="button"
            >
              - Zoom
            </button>
            <div className="flex h-8 items-center rounded-lg border border-white/10 bg-black/10 px-2.5 text-[10px] font-semibold tracking-[0.06em] text-slate-200">
              {Math.round(dagCanvasZoom * 100)}%
            </div>
            <button
              className={toolbarButtonClassName}
              onClick={autoLayoutDagCanvas}
              disabled={visualChainNodes.length === 0}
              type="button"
            >
              Layout
            </button>
            <button
              className={`${toolbarButtonClassName} border-white/16 bg-[rgba(38,48,61,0.98)]`}
              onClick={() => {
                onRunWorkflow?.();
              }}
              disabled={runWorkflowDisabled}
              type="button"
            >
              {runWorkflowPending ? "Starting..." : "Run"}
            </button>
          </div>
        </div>
      ) : null}

      <div ref={dagCanvasViewportRef} className="h-full overflow-auto bg-[#566c80]">
        <div
          className="relative min-h-full min-w-full [background-image:linear-gradient(rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.08)_1px,transparent_1px),radial-gradient(circle_at_16%_18%,rgba(255,255,255,0.06),transparent_16%),radial-gradient(circle_at_82%_24%,rgba(255,255,255,0.05),transparent_14%),linear-gradient(180deg,rgba(26,42,57,0.16),rgba(15,24,35,0.22))] [background-size:20px_20px,20px_20px,100%_100%,100%_100%,100%_100%]"
          style={{
            width: dagCanvasSurface.width * dagCanvasZoom,
            height: dagCanvasSurface.height * dagCanvasZoom,
          }}
        >
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_14%,rgba(255,255,255,0.06),transparent_16%),radial-gradient(circle_at_74%_22%,rgba(255,255,255,0.05),transparent_14%),linear-gradient(180deg,rgba(10,18,30,0.08),rgba(10,18,30,0.22))]" />
          <div
            ref={dagCanvasRef}
            className="relative"
            style={{
              width: dagCanvasSurface.width,
              height: dagCanvasSurface.height,
              transform: `scale(${dagCanvasZoom})`,
              transformOrigin: "top left",
            }}
          >
          {showEmptyBlueprint ? (
            <svg
              className="pointer-events-none absolute left-0 top-0"
              width={dagCanvasSurface.width}
              height={dagCanvasSurface.height}
              viewBox={`0 0 ${dagCanvasSurface.width} ${dagCanvasSurface.height}`}
            >
              {emptyBlueprintEdges.map((edge) => (
                <g key={`empty-blueprint-edge-${edge.id}`}>
                  <path d={edge.path} stroke={edge.color} strokeWidth="2.4" fill="none" />
                  {edge.label && edge.labelX && edge.labelY ? (
                    <g>
                      <rect
                        x={edge.labelX - 32}
                        y={edge.labelY - 16}
                        width="64"
                        height="24"
                        rx="9"
                        fill="rgba(55, 69, 84, 0.94)"
                        stroke="rgba(255,255,255,0.12)"
                      />
                      <text
                        x={edge.labelX}
                        y={edge.labelY}
                        textAnchor="middle"
                        fontSize="11"
                        fill="#e2e8f0"
                      >
                        {edge.label}
                      </text>
                    </g>
                  ) : null}
                </g>
              ))}
            </svg>
          ) : null}

          <svg
            className="absolute left-0 top-0"
            width={dagCanvasSurface.width}
            height={dagCanvasSurface.height}
            viewBox={`0 0 ${dagCanvasSurface.width} ${dagCanvasSurface.height}`}
          >
            <defs>
              <marker
                id="composer-arrow"
                markerWidth="10"
                markerHeight="10"
                refX="8"
                refY="3"
                orient="auto"
              >
                <path d="M0,0 L0,6 L9,3 z" fill="#7dd3fc" />
              </marker>
            </defs>
            {dagCanvasEdges.map((edge) => {
              const isHovered = hoveredDagEdgeKey === edge.edgeKey;
              return (
                <g
                  key={`composer-edge-${edge.edgeKey}`}
                  onMouseEnter={() => setHoveredDagEdgeKey(edge.edgeKey)}
                  onMouseLeave={() =>
                    setHoveredDagEdgeKey((prev) => (prev === edge.edgeKey ? null : prev))
                  }
                >
                  <path
                    d={edge.path}
                    stroke={isHovered ? "rgba(15,23,42,0.55)" : "rgba(15,23,42,0.34)"}
                    strokeWidth={isHovered ? "6.4" : "5.2"}
                    fill="none"
                    strokeLinecap="round"
                  />
                  <path
                    d={edge.path}
                    stroke={isHovered ? "#d7ecff" : "rgba(163, 187, 212, 0.9)"}
                    strokeWidth={isHovered ? "2.9" : "2.2"}
                    fill="none"
                    strokeLinecap="round"
                    markerEnd="url(#composer-arrow)"
                  />
                  <path
                    d={edge.path}
                    stroke="transparent"
                    strokeWidth="12"
                    fill="none"
                    className="cursor-pointer"
                    onClick={() => removeDagEdge(edge.fromNodeId, edge.toNodeId)}
                  />
                  {edge.branchLabel ? (
                    <g>
                      <rect
                        x={edge.midX - 30}
                        y={edge.midY - 21}
                        rx="10"
                        ry="10"
                        width="60"
                        height="22"
                        fill="rgba(50, 63, 79, 0.94)"
                        stroke="rgba(214, 228, 241, 0.22)"
                      />
                      <text
                        x={edge.midX}
                        y={edge.midY - 6}
                        textAnchor="middle"
                        fontSize="10"
                        fill="#f8fafc"
                      >
                        {edge.branchLabel}
                      </text>
                    </g>
                  ) : null}
                  {isHovered ? (
                    <g
                      className="cursor-pointer"
                      onClick={() => removeDagEdge(edge.fromNodeId, edge.toNodeId)}
                    >
                      <circle
                        cx={edge.midX}
                        cy={edge.midY}
                        r="11"
                        fill="rgba(8, 15, 29, 0.96)"
                        stroke="rgba(251, 113, 133, 0.65)"
                      />
                      <text
                        x={edge.midX}
                        y={edge.midY + 4}
                        textAnchor="middle"
                        fontSize="12"
                        fill="#fecdd3"
                      >
                        ×
                      </text>
                    </g>
                  ) : null}
                </g>
              );
            })}
            {dagConnectorPreview ? (
              <>
                <path
                  d={dagConnectorPreview.path}
                  stroke="rgba(15,23,42,0.35)"
                  strokeWidth="5"
                  fill="none"
                  strokeLinecap="round"
                />
                <path
                  d={dagConnectorPreview.path}
                  stroke="#8ed3ff"
                  strokeWidth="2.4"
                  fill="none"
                  strokeLinecap="round"
                  strokeDasharray="8 5"
                  markerEnd="url(#composer-arrow)"
                />
              </>
            ) : null}
          </svg>

          {showEmptyBlueprint
            ? emptyBlueprintNodes.map((node) => {
                const tone = blueprintToneStyles[node.tone];
                const visual = resolveWorkflowNodeVisual({
                  capabilityId: node.capabilityId,
                  controlKind: node.controlKind,
                  nodeKind: node.nodeKind,
                  taskName: node.title,
                });
                const previewNode: ComposerDraftNode = {
                  id: node.id,
                  taskName: node.title,
                  capabilityId: node.capabilityId,
                  outputPath: "result",
                  nodeKind: node.nodeKind,
                  controlKind: node.controlKind,
                };
                const ports = outputPortsForNode(previewNode, visual, 96);
                return (
                  <div
                    key={`empty-blueprint-node-${node.id}`}
                    className="pointer-events-none absolute rounded-[18px] border"
                    style={{
                      left: node.x,
                      top: node.y,
                      width: 248,
                      height: 96,
                      borderColor: tone.border,
                      background: tone.background,
                      boxShadow: tone.shadow,
                    }}
                  >
                    <div
                      className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold"
                      style={{
                        background:
                          node.tone === "rose"
                            ? "rgba(220, 38, 38, 0.92)"
                            : "rgba(37, 99, 235, 0.84)",
                        color: node.tone === "rose" ? "#fff1f2" : "#eff6ff",
                      }}
                    >
                      {node.tone === "rose" ? "!" : "✓"}
                    </div>
                    <div className="flex h-full flex-col px-4 py-3">
                      <div className="flex items-start gap-3 pr-16">
                        <WorkflowNodePlateIcon visual={visual} size={46} />
                        <div className="min-w-0 flex-1">
                          <div
                            className="truncate text-[13px] font-semibold"
                            style={{ color: tone.title }}
                          >
                            {node.title}
                          </div>
                          <div
                            className="mt-0.5 truncate text-[11px] leading-5"
                            style={{ color: tone.subtitle }}
                          >
                            {node.subtitle}
                          </div>
                        </div>
                      </div>
                      {node.caption ? (
                        <div
                          className="mt-auto pr-16 text-center text-[11px] font-medium"
                          style={{ color: tone.caption }}
                        >
                          {node.caption}
                        </div>
                      ) : null}
                    </div>
                    {ports.map((port) => {
                      const portTone = portToneStyles[port.tone];
                      return (
                        <div
                          key={`empty-blueprint-port-${node.id}-${port.key}`}
                          className="absolute right-3 flex items-center gap-2"
                          style={{ top: port.y, transform: "translateY(-50%)" }}
                        >
                          <span
                            className="text-[11px] font-medium"
                            style={{ color: portTone.text }}
                          >
                            {port.label}
                          </span>
                          <span
                            className="flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-semibold"
                            style={{
                              borderColor: portTone.border,
                              background: portTone.background,
                              color: portTone.text,
                            }}
                          >
                            +
                          </span>
                        </div>
                      );
                    })}
                  </div>
                );
              })
            : null}

          {dagCanvasNodes.map(({ node, position }) => {
            const nodeStatus = visualChainNodeStatusById.get(node.id);
            const missingCount = nodeStatus?.missingCount || 0;
            const requiredCount = nodeStatus?.requiredCount || 0;
            const isSelected = selectedDagNodeId === node.id;
            const visual = resolveWorkflowNodeVisual({
              capabilityId: node.capabilityId,
              controlKind: node.controlKind,
              nodeKind: node.nodeKind,
              taskName: node.taskName,
            });
            const tone = blueprintToneStyles[toneForVisual(visual)];
            const status = statusForNode(node, missingCount, requiredCount);
            const ports = outputPortsForNode(node, visual, nodeHeight);
            const isConnectorHoverTarget =
              dagConnectorDrag &&
              dagConnectorDrag.sourceNodeId !== node.id &&
              dagConnectorHoverTargetNodeId === node.id;
            const borderColor = isConnectorHoverTarget
              ? "#22c55e"
              : dagEdgeDraftSourceNodeId === node.id
                ? "#d97706"
              : isSelected
                ? "#2563eb"
                : tone.border;
            const cardShadow = isSelected
              ? `${tone.shadow}, 0 0 0 2px rgba(37, 99, 235, 0.22)`
              : dagEdgeDraftSourceNodeId === node.id
                ? `${tone.shadow}, 0 0 0 2px rgba(217, 119, 6, 0.18)`
                : tone.shadow;
            return (
              <div
                key={`composer-node-${node.id}`}
                className="absolute rounded-[18px] border"
                style={{
                  left: position.x,
                  top: position.y,
                  width: nodeWidth,
                  height: nodeHeight,
                  cursor: dagCanvasDraggingNodeId === node.id ? "grabbing" : "grab",
                  borderColor,
                  background: tone.background,
                  boxShadow: cardShadow,
                }}
                onClick={() => setSelectedDagNodeId(node.id)}
                onMouseEnter={() => {
                  if (dagConnectorDrag && dagConnectorDrag.sourceNodeId !== node.id) {
                    setDagConnectorHoverTargetNodeId(node.id);
                  }
                }}
                onMouseLeave={() => {
                  setDagConnectorHoverTargetNodeId((prev) => (prev === node.id ? null : prev));
                }}
                onMouseUp={(event) => {
                  if (dagConnectorDrag && dagConnectorDrag.sourceNodeId !== node.id) {
                    event.preventDefault();
                    event.stopPropagation();
                    addDagEdge(
                      dagConnectorDrag.sourceNodeId,
                      node.id,
                      dagConnectorDrag.branchLabel
                    );
                    setDagConnectorDrag(null);
                    setDagConnectorHoverTargetNodeId(null);
                    setDagEdgeDraftSourceNodeId(null);
                  }
                }}
                onMouseDown={(event) => {
                  if (isInteractiveCanvasTarget(event.target)) {
                    return;
                  }
                  event.preventDefault();
                  beginDagNodeDrag(event, node.id);
                }}
              >
                <div
                  className="absolute -left-[6px] top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border"
                  style={{
                    borderColor: isConnectorHoverTarget ? "#22c55e" : "rgba(255,255,255,0.54)",
                    background: isConnectorHoverTarget
                      ? "#86efac"
                      : "rgba(241, 245, 249, 0.88)",
                    boxShadow: isConnectorHoverTarget
                      ? "0 0 0 4px rgba(34, 197, 94, 0.14)"
                      : "0 0 0 4px rgba(15, 23, 42, 0.08)",
                  }}
                />
                <div
                  className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold"
                  style={{
                    background: status.badgeBackground,
                    color: status.badgeColor,
                  }}
                  title={status.label}
                >
                  {status.badgeLabel}
                </div>

                <div className="flex h-full flex-col px-4 py-3">
                  <div className="flex items-start gap-3 pr-16">
                    <WorkflowNodePlateIcon visual={visual} size={46} />
                    <div className="min-w-0 flex-1">
                      <div
                        className="truncate text-[13px] font-semibold"
                        style={{ color: tone.title }}
                      >
                        {node.taskName}
                      </div>
                      <div
                        className="mt-0.5 truncate text-[11px] leading-5"
                        style={{ color: tone.subtitle }}
                      >
                        {subtitleForNode(node, visual)}
                      </div>
                    </div>
                  </div>

                  <div
                    className="mt-auto pr-16 text-center text-[11px] font-medium"
                    style={{ color: tone.caption }}
                  >
                    {status.label}
                  </div>
                </div>

                {ports.map((port) => {
                  const portTone = portToneStyles[port.tone];
                  const isActivePort =
                    dagConnectorDrag?.sourceNodeId === node.id &&
                    (dagConnectorDrag.branchLabel || "") === (port.branchLabel || "");
                  return (
                    <div
                      key={`composer-port-${node.id}-${port.key}`}
                      className="absolute right-3 flex items-center gap-2"
                      style={{ top: port.y, transform: "translateY(-50%)" }}
                    >
                      <span
                        className="text-[11px] font-medium"
                        style={{ color: portTone.text }}
                      >
                        {port.label}
                      </span>
                      <button
                        type="button"
                        className="flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-semibold transition"
                        style={{
                          borderColor: isActivePort ? "#111827" : portTone.border,
                          background: isActivePort ? portTone.border : portTone.background,
                          color: isActivePort ? "#ffffff" : portTone.text,
                          boxShadow: isActivePort
                            ? `0 0 0 4px ${hexToRgba(portTone.border, 0.24)}`
                            : "none",
                        }}
                        title={`Drag ${port.label} connector`}
                        onMouseDown={(event) => {
                          event.stopPropagation();
                          beginDagConnectorDrag(event, node.id, {
                            branchLabel: port.branchLabel,
                            sourcePortY: port.y,
                          });
                        }}
                      >
                        +
                      </button>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
        </div>
      </div>
    </div>
  );
}
