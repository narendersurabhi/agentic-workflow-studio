"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../../lib/auth";
import AppShell from "../../components/AppShell";
import SkillEditor from "./SkillEditor";
import type { Skill, SkillStep } from "./types";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
const OWNER_ID = "default";

export default function SkillsManager() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Skill | null | "new">(null);
  const [saving, setSaving] = useState(false);

  const loadSkills = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`${apiUrl}/skills?owner_id=${OWNER_ID}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSkills(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load skills");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadSkills(); }, [loadSkills]);

  const handleSave = async (
    name: string,
    description: string,
    instructions: string,
    steps: SkillStep[]
  ) => {
    setSaving(true);
    try {
      const body = { name, description, instructions, steps };
      if (editing === "new") {
        const res = await apiFetch(`${apiUrl}/skills?owner_id=${OWNER_ID}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
      } else if (editing) {
        const res = await apiFetch(`${apiUrl}/skills/${editing.id}?owner_id=${OWNER_ID}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
      }
      setEditing(null);
      await loadSkills();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (skill: Skill) => {
    if (!confirm(`Delete skill "${skill.name}"?`)) return;
    try {
      await apiFetch(`${apiUrl}/skills/${skill.id}?owner_id=${OWNER_ID}`, { method: "DELETE" });
      await loadSkills();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const builtIns = skills.filter((s) => s.built_in);
  const mySkills = skills.filter((s) => !s.built_in);

  if (editing !== null) {
    return (
      <AppShell
        activeScreen="skills"
        title={editing === "new" ? "New Skill" : `Edit: ${(editing as Skill).name}`}
        breadcrumbs={[{ label: "Skills", href: "/skills" }, { label: editing === "new" ? "New" : "Edit" }]}
      >
        <div className="mx-auto max-w-2xl px-6 py-8">
          {saving ? (
            <div className="mb-4 rounded-lg bg-surface-1 px-4 py-2 text-sm text-text-md">Saving…</div>
          ) : null}
          {error ? (
            <div className="mb-4 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-600">{error}</div>
          ) : null}
          <SkillEditor
            skill={editing === "new" ? null : editing as Skill}
            onSave={handleSave}
            onCancel={() => { setEditing(null); setError(null); }}
          />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      activeScreen="skills"
      title="Skills"
      breadcrumbs={[{ label: "Skills" }]}
    >
      <div className="mx-auto max-w-3xl px-6 py-8">
        {error ? (
          <div className="mb-4 rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-600">{error}</div>
        ) : null}

        <div className="mb-6 flex items-center justify-between">
          <p className="text-sm text-text-lo">
            Skills are reusable workflow programs invoked with{" "}
            <code className="rounded bg-surface-2 px-1 py-0.5 text-xs">/skill-name $ARGUMENTS</code>{" "}
            in the goal input.
          </p>
          <button
            className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-600"
            onClick={() => setEditing("new")}
          >
            + New Skill
          </button>
        </div>

        {loading ? (
          <div className="py-12 text-center text-sm text-text-lo">Loading…</div>
        ) : (
          <div className="space-y-8">
            {builtIns.length > 0 ? (
              <section>
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-text-lo">Built-in</h2>
                <div className="space-y-2">
                  {builtIns.map((skill) => (
                    <SkillRow key={skill.id} skill={skill} onView={() => setEditing(skill)} />
                  ))}
                </div>
              </section>
            ) : null}

            <section>
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-text-lo">My Skills</h2>
              {mySkills.length === 0 ? (
                <div className="rounded-xl border border-dashed border-subtle py-10 text-center text-sm text-text-lo">
                  No skills yet.{" "}
                  <button className="underline" onClick={() => setEditing("new")}>
                    Create one
                  </button>
                  .
                </div>
              ) : (
                <div className="space-y-2">
                  {mySkills.map((skill) => (
                    <SkillRow
                      key={skill.id}
                      skill={skill}
                      onEdit={() => setEditing(skill)}
                      onDelete={() => handleDelete(skill)}
                    />
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </AppShell>
  );
}

function SkillRow({
  skill,
  onView,
  onEdit,
  onDelete,
}: {
  skill: Skill;
  onView?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-subtle bg-surface-1 px-4 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-text-hi">{skill.name}</span>
          {skill.built_in ? (
            <span className="rounded-full border border-subtle bg-surface-2 px-2 py-0.5 text-[10px] uppercase tracking-widest text-text-lo">
              Built-in
            </span>
          ) : (
            <span className="text-[11px] text-text-lo">v{skill.version}</span>
          )}
        </div>
        {skill.description ? (
          <p className="mt-0.5 truncate text-xs text-text-lo">{skill.description}</p>
        ) : null}
        <p className="mt-0.5 text-[11px] text-text-lo">
          {skill.steps.length} step{skill.steps.length !== 1 ? "s" : ""}
          {skill.instructions ? " · has instructions" : ""}
        </p>
      </div>
      <div className="ml-4 flex shrink-0 items-center gap-2">
        {skill.built_in ? (
          <button
            className="rounded-lg border border-subtle px-3 py-1.5 text-xs font-semibold text-text-md transition hover:bg-surface-2"
            onClick={onView}
          >
            View
          </button>
        ) : (
          <>
            <button
              className="rounded-lg border border-subtle px-3 py-1.5 text-xs font-semibold text-text-md transition hover:bg-surface-2"
              onClick={onEdit}
            >
              Edit
            </button>
            <button
              className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-semibold text-rose-500 transition hover:bg-rose-50"
              onClick={onDelete}
            >
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}
