import { create } from "zustand";
import type { CanvasPoint } from "./types";

/**
 * Store shape for `WorkflowStudio.tsx`'s DAG canvas UI state.
 *
 * NOT wired into `WorkflowStudio.tsx` yet — that migration is Phase 4
 * (issue #135). This file exists so Phase 4 has a store shape to adopt
 * instead of re-deriving one from scratch, per Phase 1 (issue #132) scope.
 *
 * What's covered: the canvas-local interaction state currently prop-drilled
 * from `WorkflowStudio.tsx` down through `StudioComposerCanvas` (and
 * siblings) — node selection, node-drag, connector-drag, and viewport zoom.
 * Search `WorkflowStudio.tsx` for `selectedDagNodeId`, `dagConnectorDrag`,
 * `dagCanvasDraggingNodeId`, `dagConnectorHoverTargetNodeId`,
 * `dagEdgeDraftSourceNodeId`, `hoveredDagEdgeKey`, and `dagCanvasZoom` to see
 * every current call site.
 *
 * What's deliberately NOT covered:
 * - `composerNodePositions` (node x/y layout) — this is persisted draft
 *   data, not ephemeral UI state, so it stays in the draft/React-Query layer
 *   Phase 4 builds, not this store.
 * - Anything about *what* is on the canvas (nodes/edges/draft content) —
 *   only *how the user is currently interacting with it*.
 *
 * This store is intentionally scoped to a single open canvas. `WorkflowStudio`
 * does not currently support multiple simultaneously-mounted canvases, so a
 * single module-level store (rather than one instance per canvas) matches
 * current usage. If that changes, this needs to become a per-canvas store
 * (e.g. via a factory + context) instead of a single global.
 */

export type DagConnectorDragState = {
  sourceNodeId: string;
  x: number;
  y: number;
  branchLabel?: string;
  sourcePortY?: number;
};

type StudioCanvasSelectionState = {
  /** The currently selected DAG node, if any. Drives the inspector panel. */
  selectedDagNodeId: string | null;
  setSelectedDagNodeId: (nodeId: string | null) => void;
};

type StudioCanvasNodeDragState = {
  /** Node currently being dragged to reposition it on the canvas, if any. */
  dagCanvasDraggingNodeId: string | null;
  setDagCanvasDraggingNodeId: (nodeId: string | null) => void;
};

type StudioCanvasConnectorDragState = {
  /** In-flight drag from a node's output port to a new/target node. */
  dagConnectorDrag: DagConnectorDragState | null;
  setDagConnectorDrag: (drag: DagConnectorDragState | null) => void;
  /** Node currently hovered as a drop target while a connector drag is active. */
  dagConnectorHoverTargetNodeId: string | null;
  setDagConnectorHoverTargetNodeId: (nodeId: string | null) => void;
  /** Source node for an edge draft started via keyboard/menu rather than pointer drag. */
  dagEdgeDraftSourceNodeId: string | null;
  setDagEdgeDraftSourceNodeId: (nodeId: string | null) => void;
  /** Edge currently hovered (for highlight/delete affordance), keyed by a composite edge key. */
  hoveredDagEdgeKey: string | null;
  setHoveredDagEdgeKey: (edgeKey: string | null) => void;
};

type StudioCanvasViewportState = {
  dagCanvasZoom: number;
  setDagCanvasZoom: (zoom: number) => void;
};

export type StudioCanvasStoreState = StudioCanvasSelectionState &
  StudioCanvasNodeDragState &
  StudioCanvasConnectorDragState &
  StudioCanvasViewportState & {
    /** Clears all transient drag/hover state without touching selection or zoom. */
    resetDragState: () => void;
  };

export const DEFAULT_DAG_CANVAS_ZOOM = 1;

export const useStudioCanvasStore = create<StudioCanvasStoreState>((set) => ({
  selectedDagNodeId: null,
  setSelectedDagNodeId: (nodeId) => set({ selectedDagNodeId: nodeId }),

  dagCanvasDraggingNodeId: null,
  setDagCanvasDraggingNodeId: (nodeId) => set({ dagCanvasDraggingNodeId: nodeId }),

  dagConnectorDrag: null,
  setDagConnectorDrag: (drag) => set({ dagConnectorDrag: drag }),
  dagConnectorHoverTargetNodeId: null,
  setDagConnectorHoverTargetNodeId: (nodeId) => set({ dagConnectorHoverTargetNodeId: nodeId }),
  dagEdgeDraftSourceNodeId: null,
  setDagEdgeDraftSourceNodeId: (nodeId) => set({ dagEdgeDraftSourceNodeId: nodeId }),
  hoveredDagEdgeKey: null,
  setHoveredDagEdgeKey: (edgeKey) => set({ hoveredDagEdgeKey: edgeKey }),

  dagCanvasZoom: DEFAULT_DAG_CANVAS_ZOOM,
  setDagCanvasZoom: (zoom) => set({ dagCanvasZoom: zoom }),

  resetDragState: () =>
    set({
      dagCanvasDraggingNodeId: null,
      dagConnectorDrag: null,
      dagConnectorHoverTargetNodeId: null,
      dagEdgeDraftSourceNodeId: null,
    }),
}));

/**
 * Reference for how Phase 4 should read from this store: import individual
 * selectors rather than the whole state object, so a component that only
 * cares about (e.g.) selection doesn't re-render on every pointer-move
 * during a connector drag.
 *
 *   const selectedDagNodeId = useStudioCanvasStore((s) => s.selectedDagNodeId);
 *
 * `CanvasPoint` is re-exported here only to keep this file self-documenting
 * about the coordinate shape `DagConnectorDragState.x`/`.y` uses; the store
 * itself doesn't need it beyond that.
 */
export type { CanvasPoint };
