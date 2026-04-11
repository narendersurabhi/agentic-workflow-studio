"use client";

import type React from "react";

import {
  WorkflowNodeIcon,
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

type ComposerDagCanvasProps = {
  visualChainNodes: ComposerDraftNode[];
  dagEdgeDraftSourceNodeId: string | null;
  setDagEdgeDraftSourceNodeId: React.Dispatch<React.SetStateAction<string | null>>;
  setDagConnectorDrag: React.Dispatch<
    React.SetStateAction<{ sourceNodeId: string; x: number; y: number } | null>
  >;
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
  dagConnectorDrag: { sourceNodeId: string; x: number; y: number } | null;
  dagCanvasDraggingNodeId: string | null;
  dagConnectorHoverTargetNodeId: string | null;
  addDagEdge: (fromNodeId: string, toNodeId: string) => void;
  beginDagNodeDrag: (event: React.MouseEvent<HTMLDivElement>, nodeId: string) => void;
  isInteractiveCanvasTarget: (target: EventTarget | null) => boolean;
  beginDagConnectorDrag: (event: React.MouseEvent<HTMLButtonElement>, nodeId: string) => void;
  centerDagNodeInView: (nodeId: string) => void;
  nodeWidth: number;
  nodeHeight: number;
  showToolbar?: boolean;
  showBlueprintPreview?: boolean;
  onRunWorkflow?: () => void;
  runWorkflowPending?: boolean;
  runWorkflowDisabled?: boolean;
};

const toolbarButtonClassName =
  "inline-flex items-center rounded-xl border border-black/15 bg-[rgba(54,68,84,0.94)] px-3 py-1.5 text-[11px] font-semibold tracking-[0.04em] text-slate-50 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] transition hover:border-white/18 hover:bg-[rgba(61,77,95,0.98)] disabled:cursor-not-allowed disabled:opacity-40";

const secondaryButtonClassName =
  "rounded-full border border-white/12 bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-100 transition hover:border-sky-300/40 hover:bg-white/[0.08]";

type BlueprintPreviewNode = {
  id: string;
  x: number;
  y: number;
  title: string;
  subtitle: string;
  caption?: string;
  tone: "slate" | "sky" | "emerald" | "amber" | "rose";
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
  { border: string; background: string; iconTint: string; caption: string }
> = {
  slate: {
    border: "rgba(148, 163, 184, 0.45)",
    background: "linear-gradient(180deg, rgba(49, 61, 74, 0.96), rgba(40, 51, 63, 0.96))",
    iconTint: "rgba(148, 163, 184, 0.18)",
    caption: "#cbd5e1",
  },
  sky: {
    border: "rgba(56, 189, 248, 0.58)",
    background: "linear-gradient(180deg, rgba(34, 76, 117, 0.98), rgba(44, 57, 73, 0.96))",
    iconTint: "rgba(56, 189, 248, 0.2)",
    caption: "#dbeafe",
  },
  emerald: {
    border: "rgba(52, 211, 153, 0.52)",
    background: "linear-gradient(180deg, rgba(31, 93, 87, 0.98), rgba(40, 55, 69, 0.96))",
    iconTint: "rgba(52, 211, 153, 0.2)",
    caption: "#d1fae5",
  },
  amber: {
    border: "rgba(251, 191, 36, 0.54)",
    background: "linear-gradient(180deg, rgba(124, 90, 33, 0.98), rgba(50, 58, 70, 0.96))",
    iconTint: "rgba(251, 191, 36, 0.18)",
    caption: "#fde68a",
  },
  rose: {
    border: "rgba(251, 113, 133, 0.58)",
    background: "linear-gradient(180deg, rgba(120, 60, 77, 0.98), rgba(49, 56, 70, 0.96))",
    iconTint: "rgba(251, 113, 133, 0.18)",
    caption: "#fecdd3",
  },
};

const emptyBlueprintNodes: BlueprintPreviewNode[] = [
  {
    id: "preview-control",
    x: 170,
    y: 270,
    title: "Conditional Check",
    subtitle: "If true",
    tone: "slate",
    capabilityId: "workflow.control",
    nodeKind: "control",
    controlKind: "if_else",
  },
  {
    id: "preview-summarize",
    x: 520,
    y: 110,
    title: "Summarize Text",
    subtitle: "LLM.generate",
    tone: "sky",
    capabilityId: "llm.text.generate",
  },
  {
    id: "preview-reason",
    x: 520,
    y: 245,
    title: "GPT-4 Reasoning",
    subtitle: "LLM.reason",
    tone: "sky",
    capabilityId: "llm.reason",
  },
  {
    id: "preview-process-top",
    x: 890,
    y: 250,
    title: "Processing PDF",
    subtitle: "Running",
    tone: "amber",
    capabilityId: "document.process",
  },
  {
    id: "preview-extract",
    x: 520,
    y: 430,
    title: "Extract Data",
    subtitle: "Document.process",
    tone: "emerald",
    capabilityId: "document.process",
  },
  {
    id: "preview-process-bottom",
    x: 520,
    y: 610,
    title: "Processing PDF",
    subtitle: "Running",
    tone: "amber",
    capabilityId: "document.process",
  },
  {
    id: "preview-validate",
    x: 980,
    y: 450,
    title: "Data Validation",
    subtitle: "Rose error",
    tone: "rose",
    capabilityId: "validation.schema",
  },
  {
    id: "preview-notify",
    x: 1330,
    y: 455,
    title: "Notify Admin",
    subtitle: "Running",
    tone: "rose",
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
  showToolbar = false,
  showBlueprintPreview = false,
  onRunWorkflow,
  runWorkflowPending = false,
  runWorkflowDisabled = false,
}: ComposerDagCanvasProps) {
  const showEmptyBlueprint = showBlueprintPreview && visualChainNodes.length === 0;

  return (
    <div className="relative h-full overflow-hidden rounded-[18px] border border-[#7c8da3]/30 bg-[#566c80] shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_16px_40px_rgba(15,23,42,0.18)]">
      {showToolbar ? (
        <div className="pointer-events-none absolute inset-x-4 top-4 z-20 flex justify-end">
          <div className="pointer-events-auto flex flex-wrap items-center gap-2 rounded-[14px] border border-black/15 bg-[rgba(53,67,83,0.88)] p-2 shadow-[0_10px_24px_rgba(15,23,42,0.18)] backdrop-blur">
            <button className={toolbarButtonClassName} type="button">
              Zoom In (+)
            </button>
            <button className={toolbarButtonClassName} type="button">
              Zoom Out (-)
            </button>
            <button
              className={toolbarButtonClassName}
              onClick={autoLayoutDagCanvas}
              disabled={visualChainNodes.length === 0}
              type="button"
            >
              Auto Layout
            </button>
            <button
              className={toolbarButtonClassName}
              onClick={() => {
                onRunWorkflow?.();
              }}
              disabled={runWorkflowDisabled}
              type="button"
            >
              {runWorkflowPending ? "Starting..." : "Run Workflow"}
            </button>
          </div>
        </div>
      ) : null}

      <div ref={dagCanvasViewportRef} className="h-full overflow-auto bg-[#566c80]">
        <div
          ref={dagCanvasRef}
          className="relative [background-image:linear-gradient(rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.08)_1px,transparent_1px),radial-gradient(circle_at_16%_18%,rgba(255,255,255,0.06),transparent_16%),radial-gradient(circle_at_82%_24%,rgba(255,255,255,0.05),transparent_14%),linear-gradient(180deg,rgba(26,42,57,0.16),rgba(15,24,35,0.22))] [background-size:20px_20px,20px_20px,100%_100%,100%_100%,100%_100%]"
          style={{
            width: dagCanvasSurface.width,
            height: dagCanvasSurface.height,
            minHeight: "100%",
          }}
        >
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_14%,rgba(255,255,255,0.06),transparent_16%),radial-gradient(circle_at_74%_22%,rgba(255,255,255,0.05),transparent_14%),linear-gradient(180deg,rgba(10,18,30,0.08),rgba(10,18,30,0.22))]" />

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
                    stroke={isHovered ? "#bae6fd" : "rgba(148, 163, 184, 0.72)"}
                    strokeWidth={isHovered ? "2.8" : "1.9"}
                    fill="none"
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
                        x={edge.midX - 28}
                        y={edge.midY - 20}
                        rx="9"
                        ry="9"
                        width="56"
                        height="20"
                        fill="rgba(7, 16, 29, 0.92)"
                        stroke="rgba(125, 211, 252, 0.35)"
                      />
                      <text
                        x={edge.midX}
                        y={edge.midY - 7}
                        textAnchor="middle"
                        fontSize="10"
                        fill="#dbeafe"
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
              <path
                d={dagConnectorPreview.path}
                stroke="#38bdf8"
                strokeWidth="2.2"
                fill="none"
                strokeDasharray="7 5"
                markerEnd="url(#composer-arrow)"
              />
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
                return (
                  <div
                    key={`empty-blueprint-node-${node.id}`}
                    className="pointer-events-none absolute rounded-[16px] border px-4 py-3 shadow-[0_18px_36px_rgba(15,23,42,0.24)]"
                    style={{
                      left: node.x,
                      top: node.y,
                      width: node.nodeKind === "control" ? 230 : 220,
                      borderColor: tone.border,
                      background: tone.background,
                    }}
                  >
                    <div className="flex items-start gap-3">
                      <div
                        className="flex h-12 w-12 items-center justify-center rounded-[14px]"
                        style={{ backgroundColor: tone.iconTint }}
                      >
                        <WorkflowNodeIcon visual={visual} size={38} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-semibold text-white">
                          {node.title}
                        </div>
                        <div className="mt-1 text-xs text-slate-100/78">{node.subtitle}</div>
                        {node.caption ? (
                          <div className="mt-3 text-xs" style={{ color: tone.caption }}>
                            {node.caption}
                          </div>
                        ) : null}
                      </div>
                      <span
                        className="mt-1 h-3 w-3 rounded-full"
                        style={{ backgroundColor: tone.border }}
                      />
                    </div>
                  </div>
                );
              })
            : null}

          {dagCanvasNodes.map(({ node, position }) => {
            const edgeFromSource =
              dagEdgeDraftSourceNodeId &&
              dagEdgeDraftSourceNodeId !== node.id &&
              composerDraftEdges.some(
                (edge) =>
                  edge.fromNodeId === dagEdgeDraftSourceNodeId && edge.toNodeId === node.id
              );
            const incomingCount = dagNodeAdjacency.incoming[node.id] || 0;
            const outgoingCount = dagNodeAdjacency.outgoing[node.id] || 0;
            const nodeStatus = visualChainNodeStatusById.get(node.id);
            const missingCount = nodeStatus?.missingCount || 0;
            const requiredCount = nodeStatus?.requiredCount || 0;
            const isSelected = selectedDagNodeId === node.id;
            const isControlNode = node.nodeKind === "control";
            const visual = resolveWorkflowNodeVisual({
              capabilityId: node.capabilityId,
              controlKind: node.controlKind,
              nodeKind: node.nodeKind,
              taskName: node.taskName,
            });
            const isConnectorHoverTarget =
              dagConnectorDrag &&
              dagConnectorDrag.sourceNodeId !== node.id &&
              dagConnectorHoverTargetNodeId === node.id;
            const statusLabel = isControlNode
              ? `control ${node.controlKind || "node"}`
              : requiredCount > 0
                ? missingCount > 0
                  ? `${missingCount} missing`
                  : "ready"
                : "draft";
            const statusDotColor = isControlNode
              ? "#fbbf24"
              : missingCount > 0
                ? "#fb7185"
                : requiredCount > 0
                  ? "#34d399"
                  : "#94a3b8";
            const outputLabel = node.outputPath.trim() || "result";
            const borderColor = isConnectorHoverTarget
              ? "#34d399"
              : isSelected
                ? "#7dd3fc"
                : visual.stroke;
            const backgroundImage = `linear-gradient(135deg, ${hexToRgba(visual.fill, 0.46)} 0%, ${hexToRgba(
              visual.fill,
              0.12
            )} 24%, rgba(8, 15, 29, 0.96) 78%)`;
            const cardShadow = isSelected
              ? `0 0 0 1px ${hexToRgba(borderColor, 0.65)}, 0 18px 48px rgba(2, 8, 23, 0.48)`
              : `0 14px 36px rgba(2, 8, 23, 0.38)`;
            return (
              <div
                key={`composer-node-${node.id}`}
                className="absolute rounded-[28px] border backdrop-blur"
                style={{
                  left: position.x,
                  top: position.y,
                  width: nodeWidth,
                  minHeight: nodeHeight,
                  cursor: dagCanvasDraggingNodeId === node.id ? "grabbing" : "grab",
                  borderColor,
                  backgroundImage,
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
                    addDagEdge(dagConnectorDrag.sourceNodeId, node.id);
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
                  className="absolute -left-[7px] top-1/2 h-3.5 w-3.5 -translate-y-1/2 rounded-full border"
                  style={{
                    borderColor: isConnectorHoverTarget ? "#6ee7b7" : "rgba(226, 232, 240, 0.38)",
                    background: isConnectorHoverTarget
                      ? "rgba(52, 211, 153, 0.96)"
                      : "rgba(8, 15, 29, 0.96)",
                    boxShadow: isConnectorHoverTarget
                      ? "0 0 0 4px rgba(52, 211, 153, 0.16)"
                      : "0 0 0 4px rgba(15, 23, 42, 0.2)",
                  }}
                />
                <button
                  type="button"
                  className="absolute -right-[10px] top-1/2 h-6 w-6 -translate-y-1/2 rounded-full border text-[11px] font-semibold shadow-[0_10px_20px_rgba(2,8,23,0.45)] transition"
                  style={{
                    borderColor:
                      dagConnectorDrag?.sourceNodeId === node.id
                        ? "#7dd3fc"
                        : "rgba(226, 232, 240, 0.28)",
                    background:
                      dagConnectorDrag?.sourceNodeId === node.id
                        ? "rgba(14, 165, 233, 0.9)"
                        : "rgba(8, 15, 29, 0.95)",
                    color:
                      dagConnectorDrag?.sourceNodeId === node.id ? "#eff6ff" : "#cbd5e1",
                  }}
                  title="Drag to connect"
                  onMouseDown={(event) => {
                    event.stopPropagation();
                    beginDagConnectorDrag(event, node.id);
                  }}
                >
                  +
                </button>

                <div className="flex h-full flex-col gap-3 px-4 py-4">
                  <div className="flex items-start gap-3 pr-8">
                    <WorkflowNodeIcon
                      visual={visual}
                      className="shrink-0 shadow-[0_10px_18px_rgba(2,8,23,0.2)]"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-base font-semibold text-white">
                            {node.taskName}
                          </div>
                          <div className="mt-1 truncate text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-300/72">
                            {visual.label}
                          </div>
                        </div>
                        <span
                          className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{
                            backgroundColor: statusDotColor,
                            boxShadow: `0 0 0 5px ${hexToRgba(statusDotColor, 0.18)}`,
                          }}
                          title={statusLabel}
                        />
                      </div>
                      <div className="mt-2 truncate text-[12px] text-slate-300/88">
                        {node.capabilityId || node.controlKind || "workflow.node"}
                      </div>
                    </div>
                  </div>

                  <div className="mt-auto flex flex-wrap items-center gap-2">
                    <span
                      className="rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em]"
                      style={{
                        borderColor: hexToRgba(statusDotColor, 0.42),
                        backgroundColor: hexToRgba(statusDotColor, 0.16),
                        color:
                          missingCount > 0
                            ? "#fecdd3"
                            : requiredCount > 0
                              ? "#d1fae5"
                              : isControlNode
                                ? "#fde68a"
                                : "#e2e8f0",
                      }}
                    >
                      {statusLabel}
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-200">
                      Output {outputLabel}
                    </span>
                    <span className="rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-300">
                      {incomingCount} in · {outgoingCount} out
                    </span>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    <button
                      className={secondaryButtonClassName}
                      onClick={() => {
                        setSelectedDagNodeId(node.id);
                        centerDagNodeInView(node.id);
                      }}
                    >
                      Focus
                    </button>
                    <button
                      className={secondaryButtonClassName}
                      style={
                        dagEdgeDraftSourceNodeId === node.id
                          ? {
                              borderColor: "rgba(252, 211, 77, 0.45)",
                              background: "rgba(251, 191, 36, 0.12)",
                              color: "#fde68a",
                            }
                          : undefined
                      }
                      onClick={() => {
                        setSelectedDagNodeId(node.id);
                        setDagEdgeDraftSourceNodeId(node.id);
                      }}
                    >
                      {dagEdgeDraftSourceNodeId === node.id ? "Source" : "Edge"}
                    </button>
                    {dagEdgeDraftSourceNodeId && dagEdgeDraftSourceNodeId !== node.id ? (
                      <button
                        className={secondaryButtonClassName}
                        style={
                          edgeFromSource
                            ? {
                                borderColor: "rgba(251, 113, 133, 0.4)",
                                background: "rgba(251, 113, 133, 0.12)",
                                color: "#fecdd3",
                              }
                            : {
                                borderColor: "rgba(52, 211, 153, 0.38)",
                                background: "rgba(52, 211, 153, 0.12)",
                                color: "#d1fae5",
                              }
                        }
                        onClick={() => {
                          if (edgeFromSource) {
                            removeDagEdge(dagEdgeDraftSourceNodeId, node.id);
                          } else {
                            addDagEdge(dagEdgeDraftSourceNodeId, node.id);
                          }
                          setSelectedDagNodeId(node.id);
                          setDagEdgeDraftSourceNodeId(null);
                        }}
                      >
                        {edgeFromSource ? "Disconnect" : "Connect"}
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
