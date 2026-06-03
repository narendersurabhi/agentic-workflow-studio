# Canvas UX Improvements — Process Flow Designer

**Status:** Draft  
**Date:** 2026-06-03  
**Scope:** `WorkflowStudio.tsx` — stage canvas and `ComposerDagCanvas.tsx`

---

## Problem Statement

The current canvas is functional but has a steep cold-start curve and lacks the interaction affordances expected of a graph editor. Specific pain points:

1. **No empty state.** A new user lands on a blank dot-grid with no guidance. There is no prompt, no starter template, and no obvious first action. The only way to add a node is to find it in the floating catalog panel.
2. **No keyboard shortcuts.** Deleting a node requires opening the inspector and clicking a button. Duplicating, deselecting, fitting the view, and undoing are not possible from the keyboard at all.
3. **No orientation aid when zoomed in.** Once a graph has 6+ nodes and the user zooms in on one area, there is no way to see where the rest of the graph is without zooming out manually.
4. **Connection intent is invisible.** When dragging a connector toward a target node, there is no feedback about whether the connection is valid. The user discovers cycles and other errors only after releasing the mouse.
5. **Node alignment is manual.** Nodes dropped anywhere on canvas must be manually aligned. There is no snapping, so graphs grow messy as they get larger.
6. **Toolbar lacks fit-to-screen.** Focus Graph mode maximises the canvas but does not centre or scale the current nodes to fill the view. A one-click "fit all nodes" action is absent.
7. **No per-node context menu.** Common node actions (inspect, duplicate, remove, disconnect) require either the keyboard (not available) or the inspector panel (requires clicking the node first, then finding the action in the panel).
8. **Edge paths are not highlighted on hover.** In a complex graph it is hard to trace a dependency chain. Hovering an edge does not highlight the full upstream path.

---

## Goals

- A user with no prior knowledge of the canvas can add their first node and connect two steps within 60 seconds.
- A power user can manipulate the graph primarily from the keyboard without reaching for the inspector panel for common operations.
- The canvas remains readable at any zoom level and graph size.

## Non-Goals

- Node grouping / swim-lanes — deferred until there is user demand.
- Undo/redo history — tracked separately; requires a command-pattern refactor outside this scope.
- Collaborative multi-cursor editing.

---

## Proposed Improvements

### 1. Empty State (Priority: High)

**When:** Canvas has zero nodes.

**What to show:**

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│                  ┌──────────────────┐                   │
│                  │  + Add first     │                   │
│                  │    step          │                   │
│                  └──────────────────┘                   │
│                                                         │
│           Start from a template:                        │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Single step │  │  Sequential  │  │  Branching   │  │
│  │  Run one     │  │  A → B → C   │  │  A → B       │  │
│  │  capability  │  │  chain       │  │      → C     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

- **"+ Add first step"** button opens the capability picker inline on the canvas (same picker used in the catalog panel) and places the new node at canvas centre.
- **Template cards** insert a pre-wired set of nodes: "Single step" (1 node), "Sequential" (3 nodes in a chain), "Branching" (1 node → 2 parallel nodes).
- Empty state disappears as soon as the first node is added.

**Files:** `WorkflowStudio.tsx` (stage section), potentially a new `CanvasEmptyState.tsx` component.

---

### 2. Keyboard Shortcuts (Priority: High)

| Key | Action |
|---|---|
| `Delete` / `Backspace` | Remove the selected node (with confirmation if it has edges) |
| `D` | Duplicate the selected node (places copy offset by +40px, +40px) |
| `Escape` | Deselect current node; cancel in-progress connector drag |
| `F` | Fit all nodes to view (centre + scale to fill stage) — distinct from Focus Graph mode |
| `Shift+F` | Toggle Focus Graph mode (existing, now documented) |
| `+` / `=` | Zoom in |
| `-` | Zoom out |
| `0` | Reset zoom to 100% |
| `Space+drag` | Pan the canvas (alternative to scroll) |

**Implementation:** Add a `useEffect` on the stage `div` that listens for `keydown` when the canvas is focused. Guard behind `!isEditingInput` to avoid firing while the user types in a panel field.

**Files:** `WorkflowStudio.tsx` — add keyboard handler near the existing `dagCanvasZoom` shortcuts.

---

### 3. Mini-Map (Priority: High)

A fixed 140×90px overview panel in the bottom-right corner of the stage.

```
┌─────────────────────┐
│  · · ■ ·  · ·  ·   │  ← full graph, scaled to fit
│  · · ·  ■──■  ·    │
│  · · ·  ·  ■  ·    │
│  ┌──────┐          │  ← viewport rect (draggable)
│  │      │          │
│  └──────┘          │
└─────────────────────┘
```

- Each node is a small coloured rect (status colour: emerald = ready, rose = missing inputs, sky = selected).
- A translucent rectangle shows the current viewport. Clicking or dragging inside the mini-map pans the main canvas.
- Toggled with a button in the toolbar (default: visible). Hidden in Focus Graph mode.

**Files:** New `CanvasMiniMap.tsx` component; rendered as an `absolute` child of the stage div. Receives `dagCanvasNodes`, `dagCanvasSurface`, viewport offset/zoom as props.

---

### 4. Connection Validation Feedback (Priority: Medium)

When a connector drag is in progress and the cursor hovers a target node:

- **Valid connection** (no cycle, not already connected): target node ring turns emerald green (`ring-2 ring-emerald-400/60`), connector preview line turns emerald.
- **Invalid — would create cycle**: target node ring turns rose red (`ring-2 ring-rose-400/60`), connector preview line turns rose, a tooltip shows "Creates a cycle".
- **Invalid — already connected**: same rose treatment, tooltip "Already connected".

**Implementation:** Extend `dagConnectorHoverTargetNodeId` state to also carry a `valid: boolean` flag. Cycle check runs in the existing `dagNodeAdjacency` adjacency map with a DFS from the target node.

**Files:** `WorkflowStudio.tsx` (connector hover logic), `ComposerDagCanvas.tsx` (ring rendering).

---

### 5. Snap-to-Grid (Priority: Medium)

On drag-end, snap node position to the nearest 28px grid point (matching the dot-grid spacing on the canvas background).

```typescript
const snap = (value: number, grid = 28) => Math.round(value / grid) * grid;
```

Applied to `x` and `y` when `beginDagNodeDrag` finalises its drop position.

- Hold `Alt` during drag to temporarily disable snapping (free placement).
- Auto-layout already produces clean positions — snap only applies to manual drags.

**Files:** `WorkflowStudio.tsx` — snap in the `mousemove`/`mouseup` handler that updates `dagCanvasNodes`.

---

### 6. Fit-to-Screen Button (Priority: Medium)

A toolbar button (icon: ⊡) that computes the bounding box of all nodes and sets the viewport offset and zoom so all nodes are centred and fully visible with a 40px margin.

```
zoom = min(
  (stageWidth - 80) / graphWidth,
  (stageHeight - 80) / graphHeight,
  DAG_CANVAS_ZOOM_MAX
)
panX = (stageWidth - graphWidth * zoom) / 2 - minX * zoom
panY = (stageHeight - graphHeight * zoom) / 2 - minY * zoom
```

Distinct from Focus Graph mode: fit-to-screen adjusts viewport without hiding panels.

**Files:** `WorkflowStudio.tsx` — add `fitNodesToView()` handler; add button to `ComposerDagCanvas` toolbar (next to existing zoom buttons).

---

### 7. Right-Click Context Menu (Priority: Medium)

Right-clicking a node opens a small context menu:

```
┌─────────────────────┐
│  Inspect            │
│  Duplicate          │
│  Disconnect all     │
│  ─────────────────  │
│  Remove             │
└─────────────────────┘
```

Right-clicking the canvas background (no node):

```
┌─────────────────────┐
│  Add step here      │
│  Fit to screen      │
│  Reset layout       │
└─────────────────────┘
```

Dismissed on click-outside or Escape.

**Implementation:** `onContextMenu` handler on the node div and on the stage. Renders an absolutely-positioned menu div at cursor coordinates.

**Files:** New `CanvasContextMenu.tsx`; wired in `ComposerDagCanvas.tsx` and `WorkflowStudio.tsx`.

---

### 8. Edge Path Highlight on Hover (Priority: Low)

When the cursor hovers an edge:

- The hovered edge strokes thicker and brighter (existing: `hoveredDagEdgeKey` already drives some styling).
- **All upstream ancestors** of the edge's target node are highlighted with a lighter accent stroke to show the full dependency chain.
- All non-highlighted edges dim to 30% opacity.

**Implementation:** On hover, walk `dagNodeAdjacency` upward from the target node, collect all ancestor edge keys, apply accent class. Reset on mouse-leave.

**Files:** `ComposerDagCanvas.tsx` — extend the existing `hoveredDagEdgeKey` logic.

---

## Phased Implementation

| Phase | Items | Effort |
|---|---|---|
| 1 | Empty state, Keyboard shortcuts, Fit-to-screen button | ~2 days |
| 2 | Mini-map, Snap-to-grid | ~2 days |
| 3 | Connection validation feedback, Right-click context menu | ~2 days |
| 4 | Edge path highlight | ~0.5 days |

Phase 1 delivers the highest user-facing value with the least risk (no structural changes to the canvas engine). Phases 2–4 layer on top without requiring Phase 1 to be complete first.

---

## Open Questions

1. **Undo/redo**: Keyboard shortcut `Ctrl+Z` is listed as out-of-scope but is the most-requested canvas feature. Should Phase 1 reserve the key binding (no-op with a toast "Undo coming soon") or omit it entirely?
2. **Mini-map visibility default**: Should the mini-map be shown by default or hidden until the user enables it? Default-on is more discoverable; default-off avoids clutter for small graphs.
3. **Snap grid size**: 28px matches the dot-grid background. Should this be configurable or fixed?
4. **Context menu on touch**: Touch devices don't have right-click. Should long-press open the context menu, or should there be an explicit action button on the node card?
