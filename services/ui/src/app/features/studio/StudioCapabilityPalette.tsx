"use client";

import {
  WorkflowNodeIcon,
  resolveWorkflowNodeVisual,
} from "../../components/workflow/WorkflowNodeIcon";
import type { CapabilityItem, StudioControlKind } from "./types";
import { getCapabilityRequiredInputs } from "./utils";

type StudioCapabilityPaletteProps = {
  capabilities: CapabilityItem[];
  groups: string[];
  loading: boolean;
  error: string | null;
  query: string;
  selectedGroup: string;
  onQueryChange: (value: string) => void;
  onGroupChange: (value: string) => void;
  onAddCapability: (capabilityId: string) => void;
  onAddControl: (kind: StudioControlKind) => void;
};

const inputClassName =
  "mt-1 w-full rounded-xl border border-white/10 bg-slate-950/18 px-3 py-2 text-sm text-white outline-none transition placeholder:text-slate-300/42 focus:border-sky-300/35 focus:bg-slate-950/28";

const actionClassName =
  "shrink-0 rounded-full border border-white/12 bg-slate-950/16 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-100 transition hover:border-sky-300/35 hover:bg-sky-400/12";

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
  onQueryChange,
  onGroupChange,
  onAddCapability,
  onAddControl,
}: StudioCapabilityPaletteProps) {
  const controlNodes: Array<{
    kind: StudioControlKind;
    title: string;
    description: string;
  }> = [
    { kind: "if", title: "If", description: "Single-condition branch gate." },
    { kind: "if_else", title: "If / Else", description: "Binary branch with true and false paths." },
    { kind: "switch", title: "Switch", description: "Route by expression and named cases." },
    { kind: "parallel", title: "Parallel", description: "Design fan-out or fan-in branch groups." },
  ];

  return (
    <aside className="h-full rounded-[18px] border border-white/10 bg-[linear-gradient(180deg,rgba(44,56,69,0.96),rgba(39,50,63,0.98))] p-3 text-slate-100 shadow-[0_18px_34px_rgba(15,23,42,0.14)]">
      <div className="rounded-[14px] border border-white/10 bg-black/10 px-3 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
        <div className="flex items-center justify-between gap-3">
          <div className="text-lg font-semibold text-white">Node Palette</div>
          <div className="rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-200">
            {capabilities.length} visible
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3">
        <label className="block">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-300/75">
            Search
          </div>
          <input
            className={inputClassName}
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="llm.generate, github, validate..."
          />
        </label>
        <label className="block">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-300/75">
            Group
          </div>
          <select
            className={inputClassName}
            value={selectedGroup}
            onChange={(event) => onGroupChange(event.target.value)}
          >
            <option value="all">All groups</option>
            {groups.map((group) => (
              <option key={`studio-group-${group}`} value={group}>
                {group}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading ? (
        <div className="mt-4 rounded-2xl border border-sky-300/15 bg-sky-400/10 px-3 py-2 text-sm text-sky-100">
          Loading capability catalog...
        </div>
      ) : null}
      {error ? (
        <div className="mt-4 rounded-2xl border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-100">
          {error}
        </div>
      ) : null}

      <div className="mt-4 rounded-[18px] border border-amber-300/20 bg-[linear-gradient(180deg,rgba(245,158,11,0.14),rgba(31,41,55,0.18))] p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-100/85">
              Control Flow
            </div>
            <div className="mt-1 text-sm text-amber-50/90">
              Branching and fan-out primitives for workflow logic.
            </div>
          </div>
          <div className="rounded-full border border-amber-200/20 bg-amber-400/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-100">
            Studio only
          </div>
        </div>

        <div className="mt-3 grid gap-3">
          {controlNodes.map((item) => {
            const visual = resolveWorkflowNodeVisual({
              nodeKind: "control",
              controlKind: item.kind,
              taskName: item.title,
            });
            return (
              <div
                key={`studio-control-${item.kind}`}
                className="rounded-[24px] border px-4 py-3"
                style={{
                  borderColor: hexToRgba(visual.stroke, 0.35),
                  backgroundImage: `linear-gradient(135deg, ${hexToRgba(
                    visual.fill,
                    0.44
                  )} 0%, rgba(8, 15, 29, 0.84) 84%)`,
                }}
              >
                <div className="flex items-start gap-3">
                  <WorkflowNodeIcon visual={visual} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-white">{item.title}</div>
                    <div className="mt-1 text-xs text-slate-300/82">{item.description}</div>
                    <div className="mt-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300/65">
                      {visual.label}
                    </div>
                  </div>
                  <button className={actionClassName} onClick={() => onAddControl(item.kind)}>
                    Add
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-300/75">
            Capabilities
          </div>
          <div className="text-[11px] text-slate-400">
            Filtered by {selectedGroup === "all" ? "all groups" : selectedGroup}
          </div>
        </div>

        {capabilities.length === 0 && !loading ? (
          <div className="rounded-[24px] border border-dashed border-white/12 bg-white/[0.04] px-4 py-5 text-sm text-slate-300/72">
            No capabilities match this filter.
          </div>
        ) : null}

        {capabilities.map((item) => {
          const requiredInputs = getCapabilityRequiredInputs(item);
          const visual = resolveWorkflowNodeVisual({
            capabilityId: item.id,
            taskName: item.id,
          });
          return (
            <div
              key={`studio-capability-${item.id}`}
              className="rounded-[24px] border px-4 py-3"
              style={{
                borderColor: hexToRgba(visual.stroke, item.enabled ? 0.32 : 0.16),
                backgroundImage: `linear-gradient(135deg, ${hexToRgba(
                  visual.fill,
                  item.enabled ? 0.4 : 0.18
                )} 0%, rgba(8, 15, 29, 0.9) 82%)`,
                opacity: item.enabled ? 1 : 0.6,
              }}
            >
              <div className="flex items-start gap-3">
                <WorkflowNodeIcon visual={visual} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-white">{item.id}</div>
                      <div className="mt-1 text-xs text-slate-400">
                        {[item.group || "ungrouped", item.subgroup || null]
                          .filter(Boolean)
                          .join(" / ")}
                      </div>
                    </div>
                    <button
                      className={actionClassName}
                      onClick={() => onAddCapability(item.id)}
                      disabled={!item.enabled}
                    >
                      Add
                    </button>
                  </div>

                  {item.description ? (
                    <div className="mt-2 line-clamp-3 text-sm text-slate-300/84">
                      {item.description}
                    </div>
                  ) : null}

                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className="rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-100">
                      {visual.label}
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
                      required {requiredInputs.length}
                    </span>
                    <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
                      {item.risk_tier || "unknown"}
                    </span>
                    {item.tags.slice(0, 2).map((tag) => (
                      <span
                        key={`studio-capability-tag-${item.id}-${tag}`}
                        className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] text-slate-300"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
