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
    onSelectSkill(expandSkill(skill, "") || `/${skill.name} `);
  };

  return (
    <div className="absolute bottom-full left-0 z-50 mb-1.5 w-max min-w-[220px] max-w-[420px] overflow-hidden rounded-xl border border-subtle bg-gradient-sidebar shadow-[0_12px_32px_rgba(15,23,42,0.32)] backdrop-blur-sm">
      <div className="flex items-center gap-1.5 border-b border-subtle px-3 py-2">
        <span className="text-xs text-text-lo">/</span>
        <input
          ref={inputRef}
          className="flex-1 bg-transparent text-xs text-text-hi placeholder:text-text-lo focus:outline-none"
          placeholder="Search skills…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <kbd className="rounded border border-subtle px-1 py-0.5 text-[10px] text-text-lo">esc</kbd>
      </div>

      <div className="max-h-52 overflow-y-auto">
        {filteredSkills.length > 0 ? (
          <div>
            <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-text-lo">
              Skills
            </div>
            {filteredSkills.map((skill) => (
              <button
                key={skill.id}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition hover:bg-white/10"
                onClick={() => handleSkillSelect(skill)}
              >
                <span className="text-[11px] text-cyan-500">⚡</span>
                <span className="text-xs font-semibold text-text-hi">{skill.name}</span>
                {skill.description ? (
                  <span className="text-[11px] text-text-lo">{skill.description}</span>
                ) : null}
              </button>
            ))}
          </div>
        ) : null}

        {filteredCaps.length > 0 ? (
          <div>
            <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-text-lo">
              Capabilities
            </div>
            {filteredCaps.slice(0, 20).map((cap) => (
              <button
                key={cap.id}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition hover:bg-white/10"
                onClick={() => onSelectCapability(cap.id)}
              >
                <span className="text-[11px] text-text-lo">◈</span>
                <span className="font-mono text-xs font-semibold text-text-hi">{cap.id}</span>
                {cap.description ? (
                  <span className="text-[11px] text-text-lo">{cap.description}</span>
                ) : null}
              </button>
            ))}
          </div>
        ) : null}

        {filteredSkills.length === 0 && filteredCaps.length === 0 ? (
          <div className="px-3 py-4 text-center text-xs text-text-lo">No results for "{query}"</div>
        ) : null}
      </div>
    </div>
  );
}
