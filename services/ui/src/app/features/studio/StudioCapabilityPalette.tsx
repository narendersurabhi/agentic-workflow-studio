"use client";

import { useMemo, useState } from "react";

import {
  WorkflowNodePlateIcon,
  resolveWorkflowNodeVisual,
} from "../../components/workflow/WorkflowNodeIcon";
import type { AgentDefinition, CapabilityItem, StudioControlKind } from "./types";
import { getCapabilityRequiredInputs, taskNameFromCapability } from "./utils";

type StudioCapabilityPaletteProps = {
  capabilities: CapabilityItem[];
  groups: string[];
  loading: boolean;
  error: string | null;
  query: string;
  selectedGroup: string;
  agentDefinitions?: AgentDefinition[];
  onQueryChange: (value: string) => void;
  onGroupChange: (value: string) => void;
  onAddCapability: (capabilityId: string) => void;
  onAddControl: (kind: StudioControlKind) => void;
  onAddAgent?: (definitionId: string, definition: AgentDefinition) => void;
};

type PaletteControlItem = {
  description: string;
  kind: StudioControlKind;
  title: string;
};

type PaletteSection =
  | {
      id: string;
      kind: "control";
      title: string;
      items: PaletteControlItem[];
    }
  | {
      id: string;
      kind: "capability";
      title: string;
      items: CapabilityItem[];
    }
  | {
      id: string;
      kind: "agent";
      title: string;
      items: AgentDefinition[];
    };

const inputClassName =
  "w-full rounded-lg border border-subtle bg-surface-1 px-2.5 py-1.5 text-xs text-text-hi outline-none transition placeholder:text-text-lo focus:border-sky-300/35 focus:bg-surface-1";

const panelClassName =
  "rounded-[12px] border border-subtle bg-gradient-panel p-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]";

const formatPaletteLabel = (value: string) => {
  const acronyms = new Set(["ai", "api", "csv", "html", "json", "llm", "pdf", "sql", "ui", "url", "xml"]);
  return value
    .trim()
    .split(/[\s/_-]+/)
    .filter(Boolean)
    .map((segment) => {
      const lower = segment.toLowerCase();
      if (acronyms.has(lower)) {
        return lower.toUpperCase();
      }
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
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

export default function StudioCapabilityPalette({
  capabilities,
  groups,
  loading,
  error,
  query,
  selectedGroup,
  agentDefinitions = [],
  onQueryChange,
  onGroupChange,
  onAddCapability,
  onAddControl,
  onAddAgent,
}: StudioCapabilityPaletteProps) {
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  const normalizedQuery = query.trim().toLowerCase();
  const hasFilters = normalizedQuery.length > 0 || selectedGroup !== "all";
  const controlNodes: PaletteControlItem[] = [
    { kind: "if", title: "If", description: "Single-condition branch gate." },
    { kind: "if_else", title: "If / Else", description: "True/false branch split." },
    { kind: "switch", title: "Switch", description: "Route by named cases." },
    { kind: "parallel", title: "Parallel", description: "Fan-out or fan-in branches." },
  ];

  const visibleControlNodes = useMemo(
    () =>
      normalizedQuery
        ? controlNodes.filter((item) =>
            [item.title, item.description, item.kind].join(" ").toLowerCase().includes(normalizedQuery)
          )
        : controlNodes,
    [normalizedQuery]
  );

  const capabilitySections = useMemo(() => {
    const grouped = new Map<string, CapabilityItem[]>();
    capabilities.forEach((item) => {
      const groupName = item.group?.trim() || "Ungrouped";
      const items = grouped.get(groupName) || [];
      items.push(item);
      grouped.set(groupName, items);
    });
    return Array.from(grouped.entries())
      .map(([groupName, items]) => ({
        id: `group-${groupName.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
        title: formatPaletteLabel(groupName),
        items: [...items].sort((left, right) => left.id.localeCompare(right.id)),
      }))
      .sort((left, right) => left.title.localeCompare(right.title));
  }, [capabilities]);

  const visibleAgentDefinitions = useMemo(
    () =>
      normalizedQuery
        ? agentDefinitions.filter((def) =>
            [def.name, def.description || "", def.id].join(" ").toLowerCase().includes(normalizedQuery)
          )
        : agentDefinitions,
    [agentDefinitions, normalizedQuery]
  );

  const sections: PaletteSection[] = useMemo(() => {
    const next: PaletteSection[] = [];
    if (visibleAgentDefinitions.length > 0) {
      next.push({
        id: "agents",
        kind: "agent",
        title: "Agents",
        items: visibleAgentDefinitions,
      });
    }
    if (visibleControlNodes.length > 0) {
      next.push({
        id: "control-flow",
        kind: "control",
        title: "Control Flow",
        items: visibleControlNodes,
      });
    }
    capabilitySections.forEach((section) => {
      next.push({
        id: section.id,
        kind: "capability",
        title: section.title,
        items: section.items,
      });
    });
    return next;
  }, [capabilitySections, visibleAgentDefinitions, visibleControlNodes]);

  const visibleNodeCount = visibleAgentDefinitions.length + visibleControlNodes.length + capabilities.length;

  const toggleSection = (sectionId: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  };

  return (
    <aside className="flex h-full min-h-0 flex-col px-2.5 py-2.5 text-text-hi">
      <div className="grid gap-1.5">
        <input
          className={inputClassName}
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search nodes"
        />
        <div className="flex items-center gap-1.5">
          <select
            className={`${inputClassName} min-w-0 flex-1`}
            value={selectedGroup}
            onChange={(event) => onGroupChange(event.target.value)}
          >
            <option value="all">All groups</option>
            {groups.map((group) => (
              <option key={`studio-group-${group}`} value={group}>
                {formatPaletteLabel(group)}
              </option>
            ))}
          </select>
          {hasFilters ? (
            <button
              type="button"
              className="shrink-0 rounded-lg border border-subtle bg-surface-1 px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-md transition hover:text-text-hi"
              onClick={() => { onQueryChange(""); onGroupChange("all"); }}
            >
              Clear
            </button>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div className="mt-2 rounded-[10px] border border-sky-300/15 bg-accent-sky px-2.5 py-1.5 text-xs text-text-sky-token">
          Loading...
        </div>
      ) : null}
      {error ? (
        <div className="mt-2 rounded-[10px] border border-rose-300/20 bg-accent-rose px-2.5 py-1.5 text-xs text-text-rose-token">
          {error}
        </div>
      ) : null}

      <div className="mt-2 min-h-0 flex-1 overflow-y-auto pr-0.5">
        <div className="space-y-1.5 pb-1">
          {sections.map((section) => {
            const isCollapsed = collapsedSections.has(section.id);
            const isControlSection = section.kind === "control";
            const isAgentSection = section.kind === "agent";
            return (
              <section
                key={section.id}
                className={`${panelClassName} ${
                  isControlSection
                    ? "border-amber-300/18 bg-[linear-gradient(180deg,rgba(120,84,24,0.22),rgba(39,50,63,0.84))]"
                    : isAgentSection
                      ? "border-violet-300/18 bg-[linear-gradient(180deg,rgba(91,33,182,0.22),rgba(39,50,63,0.84))]"
                      : ""
                }`}
              >
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-3 text-left"
                  onClick={() => toggleSection(section.id)}
                >
                  <div>
                    <div
                      className={`text-[10px] font-semibold uppercase tracking-[0.18em] ${
                        isControlSection
                          ? "text-text-amber-token"
                          : isAgentSection
                            ? "text-violet-400"
                            : "text-text-md"
                      }`}
                    >
                      {section.title}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="rounded-full border border-subtle bg-surface-1 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-text-md">
                      {section.items.length}
                    </span>
                    <span className="flex h-5 w-5 items-center justify-center rounded-md border border-subtle bg-surface-1 text-[10px] text-text-md">
                      {isCollapsed ? "+" : "−"}
                    </span>
                  </div>
                </button>

                {isCollapsed ? null : (
                  <div className="mt-2 space-y-1.5">
                    {section.kind === "agent"
                      ? section.items.map((item) => {
                          const visual = resolveWorkflowNodeVisual({ nodeKind: "agent" });
                          return (
                            <button
                              key={`studio-agent-${item.id}`}
                              type="button"
                              draggable
                              onDragStart={(e) => {
                                e.dataTransfer.setData("text/plain", JSON.stringify({ type: "agent", id: item.id }));
                                e.dataTransfer.effectAllowed = "copy";
                              }}
                              className="group flex w-full cursor-grab items-center gap-3 rounded-[10px] border px-2.5 py-1.5 text-left transition hover:border-default-theme hover:bg-surface-1 active:cursor-grabbing"
                              style={{
                                borderColor: hexToRgba(visual.stroke, 0.28),
                                background: `linear-gradient(180deg, ${hexToRgba(visual.fill, 0.18)} 0%, rgba(26,35,46,0.58) 100%)`,
                              }}
                              onClick={() => onAddAgent?.(item.id, item)}
                            >
                              <WorkflowNodePlateIcon visual={visual} size={28} />
                              <div className="min-w-0 flex-1">
                                <div className="truncate text-xs font-semibold text-text-hi">
                                  {item.name}
                                </div>
                                <div className="truncate text-[10px] text-text-lo">
                                  {item.description || item.id}
                                </div>
                              </div>
                              <span className="flex h-6 w-6 items-center justify-center rounded-lg border border-subtle bg-surface-1 text-lg leading-none text-text-hi transition group-hover:border-violet-300/30 group-hover:bg-violet-900/20">
                                +
                              </span>
                            </button>
                          );
                        })
                      : section.kind === "control"
                        ? section.items.map((item) => {
                            const visual = resolveWorkflowNodeVisual({
                              nodeKind: "control",
                              controlKind: item.kind,
                              taskName: item.title,
                            });
                            return (
                              <button
                                key={`studio-control-${item.kind}`}
                                type="button"
                                draggable
                                onDragStart={(e) => {
                                  e.dataTransfer.setData("text/plain", JSON.stringify({ type: "control", id: item.kind }));
                                  e.dataTransfer.effectAllowed = "copy";
                                }}
                                className="group flex w-full cursor-grab items-center gap-3 rounded-[10px] border px-2.5 py-1.5 text-left transition hover:border-default-theme hover:bg-surface-1 active:cursor-grabbing"
                                style={{
                                  borderColor: hexToRgba(visual.stroke, 0.28),
                                  background: `linear-gradient(180deg, ${hexToRgba(
                                    visual.fill,
                                    0.18
                                  )} 0%, rgba(26,35,46,0.58) 100%)`,
                                }}
                                onClick={() => onAddControl(item.kind)}
                              >
                                <WorkflowNodePlateIcon visual={visual} size={28} />
                                <div className="min-w-0 flex-1">
                                  <div className="truncate text-xs font-semibold text-text-hi">
                                    {item.title}
                                  </div>
                                  <div className="truncate text-[10px] text-text-lo">
                                    {item.description}
                                  </div>
                                </div>
                                <span className="flex h-6 w-6 items-center justify-center rounded-lg border border-subtle bg-surface-1 text-lg leading-none text-text-hi transition group-hover:border-sky-300/30 group-hover:bg-accent-sky">
                                  +
                                </span>
                              </button>
                            );
                          })
                        : section.items.map((item) => {
                            const requiredInputs = getCapabilityRequiredInputs(item);
                            const visual = resolveWorkflowNodeVisual({
                              capabilityId: item.id,
                              taskName: item.id,
                            });
                            return (
                              <button
                                key={`studio-capability-${item.id}`}
                                type="button"
                                draggable={item.enabled}
                                onDragStart={(e) => {
                                  if (!item.enabled) { e.preventDefault(); return; }
                                  e.dataTransfer.setData("text/plain", JSON.stringify({ type: "capability", id: item.id }));
                                  e.dataTransfer.effectAllowed = "copy";
                                }}
                                className="group flex w-full cursor-grab items-center gap-3 rounded-[10px] border px-2.5 py-1.5 text-left transition hover:border-default-theme hover:bg-surface-1 disabled:cursor-not-allowed active:cursor-grabbing"
                                style={{
                                  borderColor: hexToRgba(visual.stroke, item.enabled ? 0.26 : 0.14),
                                  background: item.enabled
                                    ? `linear-gradient(180deg, ${hexToRgba(
                                        visual.fill,
                                        0.16
                                      )} 0%, rgba(26,35,46,0.56) 100%)`
                                    : "linear-gradient(180deg, rgba(71,85,105,0.16) 0%, rgba(26,35,46,0.44) 100%)",
                                  opacity: item.enabled ? 1 : 0.56,
                                }}
                                onClick={() => onAddCapability(item.id)}
                                disabled={!item.enabled}
                              >
                                <WorkflowNodePlateIcon visual={visual} size={28} />
                                <div className="min-w-0 flex-1">
                                  <div className="truncate text-xs font-semibold text-text-hi">
                                    {taskNameFromCapability(item.id)}
                                  </div>
                                  <div className="truncate text-[10px] text-text-lo">
                                    {item.id}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2">
                                  {requiredInputs.length > 0 ? (
                                    <span className="rounded-full border border-subtle bg-surface-1 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-md">
                                      {requiredInputs.length} req
                                    </span>
                                  ) : null}
                                  <span className="flex h-6 w-6 items-center justify-center rounded-lg border border-subtle bg-surface-1 text-lg leading-none text-text-hi transition group-hover:border-sky-300/30 group-hover:bg-accent-sky">
                                    +
                                  </span>
                                </div>
                              </button>
                            );
                          })}
                  </div>
                )}
              </section>
            );
          })}

          {capabilities.length === 0 && !loading ? (
            <div className="rounded-[16px] border border-dashed border-subtle bg-surface-1 px-4 py-5 text-sm text-text-md">
              No capability nodes match the current filters.
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
