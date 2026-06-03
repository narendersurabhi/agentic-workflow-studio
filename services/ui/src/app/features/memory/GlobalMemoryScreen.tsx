"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, useAuth } from "../../lib/auth";

import AppShell from "../../components/AppShell";
import ScreenHeader from "../../components/ScreenHeader";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";

type MemoryScope = "request" | "session" | "user" | "project" | "global";

type MemorySpec = {
  name: string;
  description: string;
  scope: MemoryScope;
  ttl_seconds?: number | null;
};

type MemoryEntry = {
  id: string;
  name: string;
  scope: MemoryScope;
  payload: Record<string, unknown>;
  key?: string | null;
  user_id?: string | null;
  job_id?: string | null;
  project_id?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  expires_at?: string | null;
};


const prettyJson = (value: unknown) => JSON.stringify(value ?? {}, null, 2);

const formatTimestamp = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

export default function GlobalMemoryScreen() {
  const { user: authUser } = useAuth();
  const [specs, setSpecs] = useState<MemorySpec[]>([]);
  const [specsLoading, setSpecsLoading] = useState(true);
  const [specsError, setSpecsError] = useState<string | null>(null);
  const [userId, setUserId] = useState("");
  const [selectedName, setSelectedName] = useState("user_profile");
  const [entries, setEntries] = useState<MemoryEntry[]>([]);
  const [entriesLoading, setEntriesLoading] = useState(false);
  const [entriesError, setEntriesError] = useState<string | null>(null);
  const [selectedEntryId, setSelectedEntryId] = useState<string | null>(null);
  const [editorKey, setEditorKey] = useState("");
  const [payloadText, setPayloadText] = useState(prettyJson({}));
  const [metadataText, setMetadataText] = useState(prettyJson({}));
  const [editorError, setEditorError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (authUser?.user_id) {
      setUserId(authUser.user_id);
    }
  }, [authUser?.user_id]);

  useEffect(() => {
    let ignore = false;
    const loadSpecs = async () => {
      setSpecsLoading(true);
      setSpecsError(null);
      try {
        const response = await apiFetch(`${apiUrl}/memory/specs`);
        const body = (await response.json()) as MemorySpec[] | { detail?: string };
        if (!response.ok) {
          throw new Error(typeof (body as { detail?: string }).detail === "string" ? (body as { detail: string }).detail : `Failed to load memory specs (${response.status})`);
        }
        const userSpecs = (body as MemorySpec[]).filter((entry) => entry.scope === "user");
        if (!ignore) {
          setSpecs(userSpecs);
          if (userSpecs.length > 0 && !userSpecs.some((entry) => entry.name === selectedName)) {
            setSelectedName(userSpecs[0].name);
          }
        }
      } catch (error) {
        if (!ignore) {
          setSpecsError(error instanceof Error ? error.message : "Failed to load memory specs.");
        }
      } finally {
        if (!ignore) {
          setSpecsLoading(false);
        }
      }
    };
    void loadSpecs();
    return () => {
      ignore = true;
    };
  }, [selectedName]);

  const selectedSpec = useMemo(
    () => specs.find((entry) => entry.name === selectedName) || null,
    [selectedName, specs]
  );

  const selectedEntry = useMemo(
    () => entries.find((entry) => entry.id === selectedEntryId) || null,
    [entries, selectedEntryId]
  );

  const refreshEntries = async () => {
    if (!selectedName || !userId.trim()) {
      setEntries([]);
      return;
    }
    setEntriesLoading(true);
    setEntriesError(null);
    try {
      const params = new URLSearchParams({
        name: selectedName,
        scope: "user",
        user_id: userId.trim(),
        limit: "200",
      });
      const response = await apiFetch(`${apiUrl}/memory/read?${params.toString()}`);
      const body = (await response.json()) as MemoryEntry[] | { detail?: string };
      if (!response.ok) {
        throw new Error(typeof (body as { detail?: string }).detail === "string" ? (body as { detail: string }).detail : `Failed to load memory entries (${response.status})`);
      }
      const nextEntries = body as MemoryEntry[];
      setEntries(nextEntries);
      if (selectedEntryId && !nextEntries.some((entry) => entry.id === selectedEntryId)) {
        setSelectedEntryId(null);
      }
    } catch (error) {
      setEntriesError(error instanceof Error ? error.message : "Failed to load memory entries.");
    } finally {
      setEntriesLoading(false);
    }
  };

  useEffect(() => {
    void refreshEntries();
  }, [selectedName, userId]);

  const resetEditor = () => {
    setSelectedEntryId(null);
    setEditorKey("");
    setPayloadText(prettyJson({}));
    setMetadataText(prettyJson({}));
    setEditorError(null);
  };

  const loadEntryIntoEditor = (entry: MemoryEntry) => {
    setSelectedEntryId(entry.id);
    setEditorKey(entry.key || "");
    setPayloadText(prettyJson(entry.payload));
    setMetadataText(prettyJson(entry.metadata));
    setEditorError(null);
    setNotice(`Loaded ${entry.name}${entry.key ? `:${entry.key}` : ""}.`);
  };

  const saveEntry = async () => {
    setEditorError(null);
    setNotice(null);
    if (!selectedName || !userId.trim()) {
      setEditorError("User ID and memory type are required.");
      return;
    }
    let payload: Record<string, unknown> = {};
    let metadata: Record<string, unknown> = {};
    try {
      payload = JSON.parse(payloadText || "{}");
      metadata = JSON.parse(metadataText || "{}");
    } catch (error) {
      setEditorError(error instanceof Error ? `Invalid JSON: ${error.message}` : "Invalid JSON.");
      return;
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      setEditorError("Payload must be a JSON object.");
      return;
    }
    if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
      setEditorError("Metadata must be a JSON object.");
      return;
    }
    setSaving(true);
    try {
      const response = await apiFetch(`${apiUrl}/memory/write`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: selectedName,
          scope: "user",
          user_id: userId.trim(),
          key: editorKey.trim() || null,
          payload,
          metadata,
          if_match_updated_at: selectedEntry?.updated_at || null,
        }),
      });
      const body = (await response.json()) as MemoryEntry | { detail?: string };
      if (!response.ok) {
        throw new Error(typeof (body as { detail?: string }).detail === "string" ? (body as { detail: string }).detail : `Failed to save memory (${response.status})`);
      }
      const entry = body as MemoryEntry;
      setSelectedEntryId(entry.id);
      setNotice(`Saved ${entry.name}${entry.key ? `:${entry.key}` : ""}.`);
      await refreshEntries();
    } catch (error) {
      setEditorError(error instanceof Error ? error.message : "Failed to save memory.");
    } finally {
      setSaving(false);
    }
  };

  const deleteEntry = async () => {
    setEditorError(null);
    setNotice(null);
    if (!selectedName || !userId.trim()) {
      setEditorError("User ID and memory type are required.");
      return;
    }
    if (!selectedEntry && !editorKey.trim()) {
      setEditorError("Select an entry or provide a key to delete.");
      return;
    }
    setDeleting(true);
    try {
      const params = new URLSearchParams({
        name: selectedName,
        scope: "user",
        user_id: userId.trim(),
      });
      const key = selectedEntry?.key || editorKey.trim();
      if (key) {
        params.set("key", key);
      }
      const response = await apiFetch(`${apiUrl}/memory/delete?${params.toString()}`, {
        method: "DELETE",
      });
      const body = (await response.json()) as MemoryEntry | { detail?: string };
      if (!response.ok) {
        throw new Error(typeof (body as { detail?: string }).detail === "string" ? (body as { detail: string }).detail : `Failed to delete memory (${response.status})`);
      }
      const entry = body as MemoryEntry;
      setNotice(`Deleted ${entry.name}${entry.key ? `:${entry.key}` : ""}.`);
      resetEditor();
      await refreshEntries();
    } catch (error) {
      setEditorError(error instanceof Error ? error.message : "Failed to delete memory.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <AppShell
      activeScreen="memory"
      title="User Context Memory"
      breadcrumbs={[
        { label: "Project", href: "/project" },
        { label: "User Context Memory" },
      ]}
      actions={
        <>
          <button
            className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-sky-300/35 hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={resetEditor}
            disabled={saving || deleting}
          >
            New Entry
          </button>
          <button
            className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-sky-300/35 hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void refreshEntries()}
            disabled={entriesLoading}
          >
            {entriesLoading ? "Refreshing..." : "Refresh"}
          </button>
          <button
            className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-default-theme hover:bg-slate-950/35 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={saveEntry}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save Context"}
          </button>
        </>
      }
    >
      <div className="space-y-5">
      <ScreenHeader
        eyebrow="User Context Memory"
        title="User Context Memory"
        description="Manage reusable user and project context so repeated details do not need to be re-entered."
        activeScreen="memory"
        theme="studio"
        compact
      />

      {notice ? (
        <div className="rounded-2xl border border-emerald-300/20 bg-accent-emerald px-4 py-3 text-sm text-text-emerald-token">
          {notice}
        </div>
      ) : null}
      {editorError ? (
        <div className="rounded-2xl border border-rose-300/20 bg-accent-rose px-4 py-3 text-sm text-text-rose-token">
          {editorError}
        </div>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-[320px_minmax(0,1fr)]">
        <section className="rounded-[24px] border border-subtle bg-gradient-panel p-4 shadow-[0_12px_32px_rgba(15,23,42,0.14),inset_0_1px_0_rgba(255,255,255,0.05)]">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-lo">
            Browser + Scope
          </div>
          <div className="mt-4 space-y-4">
            <label className="block">
              <div className="text-sm font-medium text-text-hi">Context Type</div>
              <select
                className="mt-1 w-full rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-sm text-text-hi shadow-sm outline-none transition focus:border-sky-300/40 focus:ring-2 focus:ring-sky-300/20"
                value={selectedName}
                onChange={(event) => {
                  setSelectedName(event.target.value);
                  resetEditor();
                }}
              >
                {specs.map((spec) => (
                  <option key={spec.name} value={spec.name}>
                    {spec.name}
                  </option>
                ))}
              </select>
            </label>
            {specsLoading ? <div className="text-sm text-text-md">Loading memory types...</div> : null}
            {specsError ? <div className="text-sm text-rose-600">{specsError}</div> : null}
            {selectedSpec ? (
              <div className="rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-sm text-text-md">
                <div className="font-semibold text-text-hi">{selectedSpec.name}</div>
                <div className="mt-1">{selectedSpec.description}</div>
                <div className="mt-2 text-xs text-text-md">
                  Scope: {selectedSpec.scope} {selectedSpec.ttl_seconds ? `· TTL ${selectedSpec.ttl_seconds}s` : "· no TTL"}
                </div>
              </div>
            ) : null}
          </div>

            <div className="mt-6">
              <div className="flex items-center justify-between gap-3">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-sky-token">
                Entries
              </div>
              <div className="text-xs text-text-md">{entries.length} loaded</div>
            </div>
            {entriesError ? <div className="mt-3 text-sm text-rose-600">{entriesError}</div> : null}
            <div className="mt-3 space-y-2">
              {entries.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-subtle bg-surface-1 px-4 py-6 text-sm text-text-md">
                  No entries found for this user and memory type.
                </div>
              ) : (
                entries.map((entry) => {
                  const selected = entry.id === selectedEntryId;
                  return (
                    <button
                      key={entry.id}
                      className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                        selected
                          ? "border-sky-300/35 bg-accent-sky text-text-hi shadow-[0_8px_18px_rgba(14,165,233,0.16)]"
                          : "border-subtle bg-surface-1 text-text-hi hover:border-subtle hover:bg-surface-1"
                      }`}
                      onClick={() => loadEntryIntoEditor(entry)}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-semibold">{entry.key || "(no key)"}</div>
                        <div className={`text-[11px] ${selected ? "text-text-sky-token" : "text-text-md"}`}>
                          {formatTimestamp(entry.updated_at)}
                        </div>
                      </div>
                      <div className={`mt-2 line-clamp-3 text-xs ${selected ? "text-text-sky-token" : "text-text-md"}`}>
                        {prettyJson(entry.payload)}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </section>

        <section className="rounded-[24px] border border-subtle bg-gradient-panel p-4 shadow-[0_12px_32px_rgba(15,23,42,0.14),inset_0_1px_0_rgba(255,255,255,0.05)]">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-sky-token">
                Editor
              </div>
              <h2 className="mt-1 text-base font-semibold tracking-tight text-text-hi">
                {selectedEntry ? "Update Context Entry" : "Create Context Entry"}
              </h2>
            </div>
            <button
              className="rounded-full border border-rose-300/20 bg-accent-rose px-4 py-2 text-sm font-semibold text-text-rose-token transition hover:border-rose-300/30 hover:bg-accent-rose disabled:cursor-not-allowed disabled:opacity-50"
              onClick={deleteEntry}
              disabled={deleting || saving}
            >
              {deleting ? "Deleting..." : "Delete"}
            </button>
          </div>

          <div className="mt-3 grid gap-3">
            <label className="block">
              <div className="text-sm font-medium text-text-hi">Key</div>
              <input
                className="mt-1 w-full rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-sm text-text-hi shadow-sm outline-none transition placeholder:text-text-lo focus:border-sky-300/40 focus:ring-2 focus:ring-sky-300/20"
                value={editorKey}
                onChange={(event) => setEditorKey(event.target.value)}
                placeholder="preferences"
              />
            </label>
            <label className="block">
              <div className="text-sm font-medium text-text-hi">Payload JSON</div>
              <textarea
                className="mt-1 min-h-[220px] w-full rounded-2xl border border-subtle bg-surface-1 px-3 py-3 font-mono text-xs text-text-hi outline-none transition placeholder:text-text-lo focus:border-sky-300/40 focus:bg-surface-1"
                value={payloadText}
                onChange={(event) => setPayloadText(event.target.value)}
              />
            </label>
            <label className="block">
              <div className="text-sm font-medium text-text-hi">Metadata JSON</div>
              <textarea
                className="mt-1 min-h-[120px] w-full rounded-2xl border border-subtle bg-surface-1 px-3 py-3 font-mono text-xs text-text-hi outline-none transition placeholder:text-text-lo focus:border-sky-300/40 focus:bg-surface-1"
                value={metadataText}
                onChange={(event) => setMetadataText(event.target.value)}
              />
            </label>
          </div>
        </section>
      </div>
      </div>
    </AppShell>
  );
}
