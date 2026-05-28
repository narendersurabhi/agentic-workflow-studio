"use client";

import { useEffect, useRef, useState } from "react";
import type { CapabilityItem, Skill } from "./types";

type Props = {
  skills: Skill[];
  capabilities: CapabilityItem[];
  onSelectSkill: (expanded: string) => void;
  onSelectCapability: (id: string) => void;
  onClose: () => void;
};

export default function SkillCommandPalette({
  skills,
  capabilities,
  onSelectSkill,
  onSelectCapability,
  onClose,
}: Props) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const q = query.toLowerCase();
  const filteredSkills = skills.filter(
    (s) => !q || s.name.toLowerCase().includes(q) || s.description?.toLowerCase().includes(q)
  );
  const filteredCaps = capabilities.filter(
    (c) => !q || c.id.toLowerCase().includes(q) || c.description?.toLowerCase().includes(q)
  );

  const expandSkill = (skill: Skill, args = ""): string => {
    const parts: string[] = [];
    if (skill.instructions) parts.push(skill.instructions.trim());
    for (const step of skill.steps) {
      if (step.condition) {
        const { operator, value } = step.condition;
        if (operator === "exists" && !args.trim()) continue;
        if (operator === "not_exists" && args.trim()) continue;
        if (operator === "contains" && value && !args.includes(value)) continue;
      }
      if (step.type === "goal_text" && step.goal_template) {
        parts.push(step.goal_template.replace(/\$ARGUMENTS/g, args));
      }
    }
    return parts.join("\n\n");
  };

  const handleSkillSelect = (skill: Skill) => {
    const expanded = expandSkill(skill, "");
    onSelectSkill(expanded || `/${skill.name} `);
  };

  return (
    <div className="absolute bottom-full left-0 right-0 z-50 mb-2 overflow-hidden rounded-2xl border border-subtle bg-surface-1 shadow-[0_24px_60px_rgba(15,23,42,0.28)]">
      <div className="flex items-center gap-2 border-b border-subtle px-4 py-3">
        <span className="text-sm font-medium text-text-lo">/</span>
        <input
          ref={inputRef}
          className="flex-1 bg-transparent text-sm text-text-hi placeholder:text-text-lo focus:outline-none"
          placeholder="Search skills and capabilities…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <kbd className="rounded border border-subtle px-1.5 py-0.5 text-[11px] text-text-lo">esc</kbd>
      </div>

      <div className="max-h-80 overflow-y-auto">
        {filteredSkills.length > 0 ? (
          <div>
            <div className="px-4 py-2 text-[11px] font-semibold uppercase tracking-widest text-text-lo">
              Skills
            </div>
            {filteredSkills.map((skill) => (
              <button
                key={skill.id}
                className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition hover:bg-surface-2"
                onClick={() => handleSkillSelect(skill)}
              >
                <span className="mt-0.5 text-sm text-cyan-500">⚡</span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-text-hi">{skill.name}</div>
                  {skill.description ? (
                    <div className="truncate text-xs text-text-lo">{skill.description}</div>
                  ) : null}
                  <div className="mt-0.5 text-[11px] text-text-lo">
                    {skill.steps.length} step{skill.steps.length !== 1 ? "s" : ""}
                    {skill.built_in ? " · built-in" : ""}
                  </div>
                </div>
              </button>
            ))}
          </div>
        ) : null}

        {filteredCaps.length > 0 ? (
          <div>
            <div className="px-4 py-2 text-[11px] font-semibold uppercase tracking-widest text-text-lo">
              Capabilities
            </div>
            {filteredCaps.slice(0, 20).map((cap) => (
              <button
                key={cap.id}
                className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition hover:bg-surface-2"
                onClick={() => onSelectCapability(cap.id)}
              >
                <span className="mt-0.5 text-sm text-text-lo">◈</span>
                <div className="min-w-0">
                  <div className="font-mono text-xs font-semibold text-text-hi">{cap.id}</div>
                  {cap.description ? (
                    <div className="truncate text-xs text-text-lo">{cap.description}</div>
                  ) : null}
                </div>
              </button>
            ))}
          </div>
        ) : null}

        {filteredSkills.length === 0 && filteredCaps.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-text-lo">No results for "{query}"</div>
        ) : null}
      </div>
    </div>
  );
}
