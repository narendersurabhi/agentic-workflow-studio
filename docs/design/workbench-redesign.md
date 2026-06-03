# Workbench Redesign — Agent + Capability Workbench

**Status:** Draft  
**Date:** 2026-05-28  
**Scope:** `StudioWorkbenchSurface.tsx` (3070 lines) and its entry point in `WorkflowStudio.tsx`

---

## Problem Statement

The current workbench asks users to make a mode choice before they understand what they need. Selecting "Capability Sandbox" vs "Agent Sandbox" at the top of the page is a concept-level gate that blocks casual users and confuses new ones. Once inside, the three simultaneous columns — catalog, form, and JSON preview — overwhelm the viewport with equal visual weight, leaving users unsure what to act on first.

Specific pain points:

1. **Upfront mode selection.** "Capability Sandbox" and "Agent Sandbox" are internal implementation terms, not user tasks. Users think in terms of "I want to run X" or "I want to build something with Y", not "I want a sandbox mode."
2. **Right column is always-on developer output.** The schema/RunSpec/ExecutionRequest JSON previews are permanently visible and take up ~30% of horizontal space. They are useful for debugging but distracting during normal use.
3. **Agent profile management buried in the run form.** Save / Save as / Publish / Delete / version selector live inside the same form as run inputs. These are lifecycle operations, not run configuration.
4. **The bottom run-results panel requires scrolling.** After launching, users scroll past the entire configuration form to see what happened.
5. **Retry policy and raw JSON override are always visible.** These are advanced escape hatches but they take up vertical space even for the 95% of runs that don't need them.
6. **Multi-step agent composition is a parallel UI.** The structured agent editor (primary step + N additional steps with dependency management) is a completely separate form tree from the capability sandbox, rather than a natural extension of it.

---

## Goals

- A user who knows nothing about "capability mode vs agent mode" can pick a capability and run it within 3 clicks.
- Advanced features (raw JSON, retry policy, multi-step composition, profile management) remain accessible but are not visible by default.
- Run output is immediately visible after launch without scrolling.
- The catalog, configuration, and output never compete for equal visual weight at the same time.

---

## Non-Goals

- Removing any existing feature. The redesign reorganises, hides behind progressive disclosure, and rewords — it does not delete run flows, profile management, replay, fork, or workflow promotion.
- Redesigning the DAG canvas ("Studio" surface). That stays as-is.

---

## Proposed Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ AppShell header: Workflow Studio  [Studio | Workbench]  New Workflow  │
├───────────────────┬──────────────────────────────────────────────────┤
│                   │                                                    │
│  CATALOG          │   CONFIGURE + RUN                                 │
│  (collapsible,    │                                                    │
│  240px)           │   ┌─────────────────────────────────────────────┐│
│                   │   │ Capability  [codegen.autonomous          ▾ ] ││
│  [search...]      │   │                                              ││
│                   │   │ — auto-detected: agentic capability —        ││
│  ▸ CODEGEN        │   │                                              ││
│    codegen.auto   │   │ Goal        [________________________________]││
│    codegen.gen    │   │ Workspace   [workbench-agent               ]  ││
│                   │   │ Max steps   [6  ]                            ││
│  ▸ GITHUB         │   │                                              ││
│    github.repo.…  │   │ ▸ Additional steps (0)        [+ Add Step]  ││
│    github.pr.…    │   │                                              ││
│                   │   │ ▸ Advanced  (context, retry, raw JSON)       ││
│  ▸ LLM            │   │                                              ││
│    llm.generate   │   │ ┌──────────────────────────────────────────┐││
│    llm.extract    │   │ │            ▶  Run                        │││
│                   │   │ └──────────────────────────────────────────┘││
│  ▸ DOCUMENTS      │   └─────────────────────────────────────────────┘│
│  ▸ FILESYSTEM     │                                                    │
│  ▸ MEMORY         │   RUN OUTPUT                                      │
│  ▸ RAG            │   ┌─────────────────────────────────────────────┐│
│  ▸ UTILITY        │   │ ● succeeded  ·  3 steps  ·  run abc12345    ││
│                   │   │                                              ││
│  [collapse ‹]     │   │ Step 1  codegen.autonomous   ✓              ││
│                   │   │ Step 2  github.pr.create      ✓              ││
│                   │   │ Step 3  llm.generate          ✓              ││
│                   │   │                                              ││
│                   │   │ Artifacts · Execution Log  [Promote ▸]  [Fork]││
│                   │   └─────────────────────────────────────────────┘│
└───────────────────┴──────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Remove the mode toggle — unify around capability selection

The current "Capability Sandbox" / "Agent Sandbox" toggle is replaced by a single capability selector at the top of the form. When a capability is selected:

- If it is agentic (`tags includes "autonomous"` or `id includes ".autonomous"`), the form automatically shows agentic fields: Goal, Workspace Path, Max Steps, Constraints.
- If it is a standard capability, the form shows the schema-driven input fields.

"Add Step" expands multi-step composition inline, naturally extending the single-step form. This preserves all agent functionality without requiring users to pre-select a mode.

### 2. Catalog becomes a collapsible left panel

The catalog is always available but defaults to collapsed on narrow viewports and after a capability is selected. It groups capabilities by tag/group with expand/collapse per group. Clicking any catalog item inserts it into the capability field (or adds it as a new step if in multi-step mode).

The three filter dropdowns (group, risk tier, idempotency) consolidate into a single filter row with pills.

### 3. Run Output replaces the right column

The JSON preview column (capability schema, RunSpec, ExecutionRequest) moves behind a collapsible "Developer Preview" disclosure inside the Advanced section. It is no longer permanently visible.

The right-column space below the configure form becomes the **Run Output** area — visible as soon as a run is launched, without scrolling. It shows:
- Status bar (status · steps count · run ID)
- Step cards (name, capability, status, errors)
- Tabbed output: Artifacts | Execution Log | Raw Debugger

### 4. Agent profile management moves to a Profile Drawer

Save / Save as / Publish / Delete / version history are moved out of the inline form into a slide-in drawer triggered by a "Manage Profile" button in the form header. This separates lifecycle operations from run configuration, which have different frequencies of use.

The profile picker (which profile is active) stays in the form header as a compact select.

### 5. Progressive disclosure for advanced inputs

The following are hidden by default behind a collapsible "Advanced" row:
- Context JSON
- Retry policy JSON
- Raw RunSpec override
- Developer preview (schema, RunSpec, ExecutionRequest JSON)

The default path is: pick a capability → fill in the prompted fields → run.

---

## Component Structure After Redesign

```
WorkflowStudio.tsx
  └── StudioWorkbenchSurface.tsx  (replaces current file)
        ├── WorkbenchCatalogPanel.tsx     (left, collapsible)
        │     ├── capability search input
        │     ├── filter pills
        │     └── grouped capability list
        ├── WorkbenchConfigurePanel.tsx   (center)
        │     ├── CapabilitySelector      (top — single input with autocomplete)
        │     ├── AgentFieldsSection      (shown if agentic capability)
        │     ├── CapabilityInputsForm    (schema-driven, shown for standard capability)
        │     ├── AdditionalStepsSection  (collapsed by default, expandable)
        │     ├── ProfileHeader           (compact select + "Manage Profile" button)
        │     ├── AdvancedSection         (collapsed: context JSON, retry, raw, dev preview)
        │     └── RunButton
        └── WorkbenchOutputPanel.tsx      (below configure, appears after first run)
              ├── RunStatusBar
              ├── StepCardList
              └── OutputTabs              (Artifacts | Execution Log | Raw Debugger)
                    + Fork button
                    + Promote to Workflow button
```

---

## State Changes

| Current state | After redesign |
|---|---|
| `workbenchMode: "capability" \| "agent"` | Removed. Mode inferred from selected capability. |
| `agentEditorMode: "structured" \| "raw"` | Preserved. Moved to Advanced section toggle. |
| `agentSteps[]` | Preserved. Drives AdditionalStepsSection. |
| `agentProfileDraft` | Preserved. Managed through ProfileDrawer. |
| Right-column preview visibility | Always collapsed by default; opt-in via Advanced. |
| Run results visibility | Always shown below configure panel after first launch. |

---

## Migration Notes

- All existing API calls (`launchCapabilityRun`, `launchAgentRun`, `fetchRunDebugger`, profile CRUD) are unchanged.
- The replay, fork, and promote-to-workflow flows are preserved exactly; they now surface in `WorkbenchOutputPanel`.
- `StudioWorkbenchSurface` is the only file changed. `WorkflowStudio.tsx` receives the refactored component unchanged via its existing prop interface.
- The capability detection logic (`isAgenticCapability`) already exists and drives the field-adaptive form.

---

## Phased Implementation

**Phase 1 — Layout restructure and mode removal**
- Remove the mode toggle
- Build `WorkbenchCatalogPanel` (extract existing catalog JSX)
- Build `WorkbenchConfigurePanel` with adaptive fields based on selected capability
- Build `WorkbenchOutputPanel` (extract existing run results JSX)
- Move developer JSON previews into Advanced disclosure

**Phase 2 — Progressive disclosure**
- Collapse context JSON, retry policy, raw RunSpec behind Advanced row
- Collapse Additional Steps behind an "Add Step" button

**Phase 3 — Profile Drawer**
- Extract profile management (save / save-as / publish / delete / version select) into a `WorkbenchProfileDrawer` slide-in
- Replace inline profile management with compact profile picker + "Manage" button

---

## Open Questions

1. **Profile picker placement.** Should the active profile selector appear at the very top of the configure panel (always visible) or only when "agent-like" composition is in use? Profiles only matter for multi-step runs, so showing it by default for single-step capability runs may be noise.

2. **Catalog collapsed by default on first load?** The catalog is the main discovery surface for new users. Collapsing it by default may hinder discoverability. A middle ground: open on first visit, collapse after first capability selection, remember state in localStorage.

3. **Step dependency editor.** The current structured agent editor has a "Depends on" text field for DAG edges. In the new step list, should this stay as a text field or become a visual connector (matching the Chaining Composer in Run from Prompt)?
