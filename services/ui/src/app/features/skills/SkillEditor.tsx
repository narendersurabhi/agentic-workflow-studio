"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/auth";
import type { CapabilityItem, Skill, SkillCondition, SkillStep } from "./types";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";

type Props = {
  skill: Skill | null;
  onSave: (name: string, description: string, instructions: string, steps: SkillStep[]) => void;
  onCancel: () => void;
};

function newStep(order: number): SkillStep {
  return {
    id: `step-${Date.now()}-${order}`,
    order,
    type: "goal_text",
    goal_template: "",
    inputs: {},
    condition: null,
  };
}

export default function SkillEditor({ skill, onSave, onCancel }: Props) {
  const [name, setName] = useState(skill?.name ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [instructions, setInstructions] = useState(skill?.instructions ?? "");
  const [steps, setSteps] = useState<SkillStep[]>(skill?.steps ?? []);
  const [capabilities, setCapabilities] = useState<CapabilityItem[]>([]);
  const [capSearch, setCapSearch] = useState("");
  const [showCapPicker, setShowCapPicker] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`${apiUrl}/capabilities?with_schemas=false`)
      .then((r) => r.json())
      .then((data) => setCapabilities(data.items ?? []))
      .catch(() => {});
  }, []);

  const filteredCaps = capabilities.filter(
    (c) =>
      !capSearch ||
      c.id.toLowerCase().includes(capSearch.toLowerCase()) ||
      c.description?.toLowerCase().includes(capSearch.toLowerCase())
  );

  const addCapabilityStep = (cap: CapabilityItem) => {
    const inputs: Record<string, string> = {};
    for (const req of cap.required_inputs ?? []) {
      inputs[req] = "$ARGUMENTS";
    }
    const step: SkillStep = {
      id: `step-${Date.now()}`,
      order: steps.length + 1,
      type: "capability",
      capability_id: cap.id,
      inputs,
      condition: null,
    };
    setSteps((prev) => [...prev, step]);
    setShowCapPicker(false);
    setCapSearch("");
  };

  const addGoalTextStep = () => {
    setSteps((prev) => [...prev, newStep(prev.length + 1)]);
  };

  const updateStep = (index: number, patch: Partial<SkillStep>) => {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const updateStepInput = (index: number, key: string, value: string) => {
    setSteps((prev) =>
      prev.map((s, i) =>
        i === index ? { ...s, inputs: { ...s.inputs, [key]: value } } : s
      )
    );
  };

  const updateCondition = (index: number, condition: SkillCondition | null) => {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, condition } : s)));
  };

  const moveStep = (index: number, direction: "up" | "down") => {
    setSteps((prev) => {
      const next = [...prev];
      const target = direction === "up" ? index - 1 : index + 1;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next.map((s, i) => ({ ...s, order: i + 1 }));
    });
  };

  const removeStep = (index: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== index).map((s, i) => ({ ...s, order: i + 1 })));
  };

  const handleSave = () => {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    setError(null);
    onSave(name.trim(), description.trim(), instructions.trim(), steps);
  };

  return (
    <div className="space-y-6">
      {error ? <div className="rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-600">{error}</div> : null}

      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-widest text-text-lo">Name</label>
          <input
            className="w-full rounded-lg border border-subtle bg-surface-1 px-3 py-2 text-sm text-text-hi focus:outline-none focus:ring-1 focus:ring-cyan-400"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Skill name"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-widest text-text-lo">Description</label>
          <input
            className="w-full rounded-lg border border-subtle bg-surface-1 px-3 py-2 text-sm text-text-hi focus:outline-none focus:ring-1 focus:ring-cyan-400"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="One-line description"
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs font-semibold uppercase tracking-widest text-text-lo">Instructions</label>
        <textarea
          className="w-full rounded-lg border border-subtle bg-surface-1 px-3 py-2 text-sm text-text-hi focus:outline-none focus:ring-1 focus:ring-cyan-400"
          rows={4}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder={"Stop if any step returns an error.\nAll file paths must be relative to the workspace root.\nDo not create GitHub repositories."}
        />
        <p className="mt-1 text-xs text-text-lo">
          Guides the agent on how to behave. Prepended to the goal at invocation time.
        </p>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-xs font-semibold uppercase tracking-widest text-text-lo">Steps</label>
          <div className="flex items-center gap-2">
            <button
              className="rounded-lg border border-subtle bg-surface-1 px-3 py-1 text-xs font-semibold text-text-hi transition hover:bg-surface-2"
              onClick={() => setShowCapPicker((p) => !p)}
            >
              + Add capability
            </button>
            <button
              className="rounded-lg border border-subtle bg-surface-1 px-3 py-1 text-xs font-semibold text-text-hi transition hover:bg-surface-2"
              onClick={addGoalTextStep}
            >
              + Add goal text
            </button>
          </div>
        </div>

        {showCapPicker ? (
          <div className="mb-3 rounded-xl border border-subtle bg-surface-1 shadow-lg">
            <div className="border-b border-subtle px-3 py-2">
              <input
                autoFocus
                className="w-full bg-transparent text-sm text-text-hi placeholder:text-text-lo focus:outline-none"
                placeholder="Search capabilities..."
                value={capSearch}
                onChange={(e) => setCapSearch(e.target.value)}
              />
            </div>
            <div className="max-h-56 overflow-y-auto">
              {filteredCaps.slice(0, 30).map((cap) => (
                <button
                  key={cap.id}
                  className="w-full px-3 py-2 text-left transition hover:bg-surface-2"
                  onClick={() => addCapabilityStep(cap)}
                >
                  <div className="text-xs font-semibold text-text-hi">{cap.id}</div>
                  <div className="text-xs text-text-lo">{cap.description}</div>
                  {cap.required_inputs?.length > 0 ? (
                    <div className="mt-0.5 text-[11px] text-text-lo">
                      required: {cap.required_inputs.join(", ")}
                    </div>
                  ) : null}
                </button>
              ))}
              {filteredCaps.length === 0 ? (
                <div className="px-3 py-3 text-xs text-text-lo">No capabilities found.</div>
              ) : null}
            </div>
          </div>
        ) : null}

        {steps.length === 0 ? (
          <div className="rounded-lg border border-dashed border-subtle py-6 text-center text-xs text-text-lo">
            No steps yet. Add a capability or goal text step above.
          </div>
        ) : (
          <div className="space-y-2">
            {steps.map((step, i) => (
              <div key={step.id} className="rounded-xl border border-subtle bg-surface-1 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-surface-2 text-[11px] font-semibold text-text-md">
                      {i + 1}
                    </span>
                    <span className="text-xs font-semibold text-text-md">
                      {step.type === "capability" ? `capability: ${step.capability_id}` : "goal text"}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      className="rounded px-1.5 py-0.5 text-[11px] text-text-lo transition hover:bg-surface-2 disabled:opacity-30"
                      onClick={() => moveStep(i, "up")}
                      disabled={i === 0}
                    >↑</button>
                    <button
                      className="rounded px-1.5 py-0.5 text-[11px] text-text-lo transition hover:bg-surface-2 disabled:opacity-30"
                      onClick={() => moveStep(i, "down")}
                      disabled={i === steps.length - 1}
                    >↓</button>
                    <button
                      className="rounded px-1.5 py-0.5 text-[11px] text-rose-500 transition hover:bg-rose-50"
                      onClick={() => removeStep(i)}
                    >✕</button>
                  </div>
                </div>

                {step.type === "goal_text" ? (
                  <textarea
                    className="mt-2 w-full rounded-lg border border-subtle bg-surface-2 px-2 py-1.5 text-xs text-text-hi focus:outline-none focus:ring-1 focus:ring-cyan-400"
                    rows={2}
                    value={step.goal_template ?? ""}
                    onChange={(e) => updateStep(i, { goal_template: e.target.value })}
                    placeholder="Goal text — use $ARGUMENTS where the user's input should appear"
                  />
                ) : (
                  <div className="mt-2 space-y-1">
                    {Object.keys(step.inputs).map((key) => (
                      <div key={key} className="flex items-center gap-2">
                        <span className="w-28 shrink-0 text-[11px] text-text-lo">{key}</span>
                        <input
                          className="flex-1 rounded border border-subtle bg-surface-2 px-2 py-1 text-xs text-text-hi focus:outline-none focus:ring-1 focus:ring-cyan-400"
                          value={String(step.inputs[key] ?? "")}
                          onChange={(e) => updateStepInput(i, key, e.target.value)}
                        />
                      </div>
                    ))}
                  </div>
                )}

                <div className="mt-2">
                  <select
                    className="rounded border border-subtle bg-surface-2 px-2 py-1 text-[11px] text-text-md"
                    value={step.condition?.operator ?? ""}
                    onChange={(e) => {
                      const op = e.target.value as SkillCondition["operator"] | "";
                      updateCondition(i, op ? { operator: op, value: step.condition?.value } : null);
                    }}
                  >
                    <option value="">No condition</option>
                    <option value="exists">$ARGUMENTS exists</option>
                    <option value="not_exists">$ARGUMENTS not exists</option>
                    <option value="contains">$ARGUMENTS contains…</option>
                  </select>
                  {step.condition?.operator === "contains" ? (
                    <input
                      className="ml-2 rounded border border-subtle bg-surface-2 px-2 py-1 text-[11px] text-text-hi focus:outline-none"
                      placeholder="substring"
                      value={step.condition.value ?? ""}
                      onChange={(e) =>
                        updateCondition(i, { operator: "contains", value: e.target.value })
                      }
                    />
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t border-subtle pt-4">
        <button
          className="rounded-lg border border-subtle px-4 py-2 text-sm font-semibold text-text-md transition hover:bg-surface-2"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-600"
          onClick={handleSave}
        >
          Save Skill
        </button>
      </div>
    </div>
  );
}
