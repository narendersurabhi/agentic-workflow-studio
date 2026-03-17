"use client";

import { useEffect, useMemo, useState } from "react";

import ScreenHeader, {
  screenHeaderPrimaryActionClassName,
  screenHeaderSecondaryActionClassName,
} from "../../components/ScreenHeader";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
const MEMORY_USER_ID_KEY = "ape.memory.user_id.v1";

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

const DEFAULT_USER_ID = "default-user";

const prettyJson = (value: unknown) => JSON.stringify(value ?? {}, null, 2);

const formatTimestamp = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

export default function GlobalMemoryScreen() {
  const [specs, setSpecs] = useState<MemorySpec[]>([]);
  const [specsLoading, setSpecsLoading] = useState(true);
  const [specsError, setSpecsError] = useState<string | null>(null);
  const [userId, setUserId] = useState(DEFAULT_USER_ID);
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
    if (typeof window === "undefined") {
      return;
    }
    const stored = window.localStorage.getItem(MEMORY_USER_ID_KEY);
    if (stored && stored.trim()) {
      setUserId(stored.trim());
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(MEMORY_USER_ID_KEY, userId);
  }, [userId]);

  useEffect(() => {
    let ignore = false;
    const loadSpecs = async () => {
      setSpecsLoading(true);
      setSpecsError(null);
      try {
        const response = await fetch(`${apiUrl}/memory/specs`);
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
      const response = await fetch(`${apiUrl}/memory/read?${params.toString()}`);
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
      const response = await fetch(`${apiUrl}/memory/write`, {
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
      const response = await fetch(`${apiUrl}/memory/delete?${params.toString()}`, {
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
    <div className="space-y-6">
      <ScreenHeader
        eyebrow="Global Memory"
        title="Manage user-scoped memory."
        description="View, create, update, and delete stable user memory entries without going through a workflow run."
        activeScreen="memory"
        actions={
          <>
            <button
              className={screenHeaderSecondaryActionClassName}
              onClick={resetEditor}
              disabled={saving || deleting}
            >
              New Entry
            </button>
            <button
              className={screenHeaderSecondaryActionClassName}
              onClick={() => void refreshEntries()}
              disabled={entriesLoading}
            >
              {entriesLoading ? "Refreshing..." : "Refresh"}
            </button>
            <button
              className={screenHeaderPrimaryActionClassName}
              onClick={saveEntry}
              disabled={saving}
            >
              {saving ? "Saving..." : "Save Memory"}
            </button>
          </>
        }
      />

      {notice ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {notice}
        </div>
      ) : null}
      {editorError ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {editorError}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Browser + Scope
          </div>
          <div className="mt-4 space-y-4">
            <label className="block">
              <div className="text-sm font-medium text-slate-700">User ID</div>
              <input
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                value={userId}
                onChange={(event) => setUserId(event.target.value)}
                placeholder={DEFAULT_USER_ID}
              />
            </label>
            <label className="block">
              <div className="text-sm font-medium text-slate-700">Memory Type</div>
              <select
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
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
            {specsLoading ? <div className="text-sm text-slate-500">Loading memory types...</div> : null}
            {specsError ? <div className="text-sm text-rose-600">{specsError}</div> : null}
            {selectedSpec ? (
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <div className="font-semibold text-slate-800">{selectedSpec.name}</div>
                <div className="mt-1">{selectedSpec.description}</div>
                <div className="mt-2 text-xs text-slate-500">
                  Scope: {selectedSpec.scope} {selectedSpec.ttl_seconds ? `· TTL ${selectedSpec.ttl_seconds}s` : "· no TTL"}
                </div>
              </div>
            ) : null}
          </div>

          <div className="mt-6">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                Entries
              </div>
              <div className="text-xs text-slate-500">{entries.length} loaded</div>
            </div>
            {entriesError ? <div className="mt-3 text-sm text-rose-600">{entriesError}</div> : null}
            <div className="mt-3 space-y-2">
              {entries.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
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
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-slate-200 bg-white text-slate-800 hover:border-slate-300"
                      }`}
                      onClick={() => loadEntryIntoEditor(entry)}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-semibold">{entry.key || "(no key)"}</div>
                        <div className={`text-[11px] ${selected ? "text-slate-300" : "text-slate-500"}`}>
                          {formatTimestamp(entry.updated_at)}
                        </div>
                      </div>
                      <div className={`mt-2 line-clamp-3 text-xs ${selected ? "text-slate-200" : "text-slate-500"}`}>
                        {prettyJson(entry.payload)}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </section>

        <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                Editor
              </div>
              <h2 className="mt-1 font-display text-2xl text-slate-900">
                {selectedEntry ? "Update Memory Entry" : "Create Memory Entry"}
              </h2>
            </div>
            <button
              className="rounded-full border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={deleteEntry}
              disabled={deleting || saving}
            >
              {deleting ? "Deleting..." : "Delete"}
            </button>
          </div>

          <div className="mt-5 grid gap-4">
            <label className="block">
              <div className="text-sm font-medium text-slate-700">Key</div>
              <input
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200"
                value={editorKey}
                onChange={(event) => setEditorKey(event.target.value)}
                placeholder="preferences"
              />
            </label>
            <label className="block">
              <div className="text-sm font-medium text-slate-700">Payload JSON</div>
              <textarea
                className="mt-1 min-h-[220px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 font-mono text-xs text-slate-900 outline-none transition focus:border-slate-400 focus:bg-white"
                value={payloadText}
                onChange={(event) => setPayloadText(event.target.value)}
              />
            </label>
            <label className="block">
              <div className="text-sm font-medium text-slate-700">Metadata JSON</div>
              <textarea
                className="mt-1 min-h-[120px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 font-mono text-xs text-slate-900 outline-none transition focus:border-slate-400 focus:bg-white"
                value={metadataText}
                onChange={(event) => setMetadataText(event.target.value)}
              />
            </label>
          </div>
        </section>
      </div>
    </div>
  );
}
