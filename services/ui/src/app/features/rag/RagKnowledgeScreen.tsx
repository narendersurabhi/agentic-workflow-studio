"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, useAuth } from "../../lib/auth";

import AppShell from "../../components/AppShell";
import ScreenHeader from "../../components/ScreenHeader";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
const DEFAULT_COLLECTION = "rag_default";
const DEFAULT_NAMESPACE = "docs";
const CREATE_NEW_VALUE = "__create_new__";

type IndexMode = "markdown" | "text" | "workspace_file" | "workspace_directory";

type RagDocumentSummary = {
  document_id: string;
  source_uri: string;
  namespace?: string | null;
  tenant_id?: string | null;
  user_id?: string | null;
  workspace_id?: string | null;
  chunk_count: number;
  chunking_strategy?: string | null;
  content_type?: string | null;
  filename?: string | null;
  path?: string | null;
  repo?: string | null;
  indexed_at?: string | null;
  metadata: Record<string, unknown>;
};

type RagDocumentListResponse = {
  collection_name: string;
  truncated: boolean;
  scanned_point_count: number;
  documents: RagDocumentSummary[];
};

type RagDocumentChunk = {
  chunk_id: string;
  document_id: string;
  source_uri: string;
  text: string;
  chunk_index?: number | null;
  metadata: Record<string, unknown>;
};

type RagDocumentChunksResponse = {
  collection_name: string;
  document: RagDocumentSummary;
  chunks: RagDocumentChunk[];
};

type RagDeleteResponse = {
  collection_name: string;
  document_id: string;
  deleted_chunk_count: number;
};

type RagReplaceResponse = {
  deleted: RagDeleteResponse;
  indexed: Record<string, unknown>;
};

const INDEX_MODES: Array<{ id: IndexMode; label: string; description: string }> = [
  {
    id: "markdown",
    label: "Paste Markdown",
    description: "Chunk markdown by headings and index it as one logical document.",
  },
  {
    id: "text",
    label: "Paste Text",
    description: "Store raw text directly when you do not need markdown-aware sectioning.",
  },
  {
    id: "workspace_file",
    label: "Workspace File",
    description: "Index one file that already exists under the shared workspace.",
  },
  {
    id: "workspace_directory",
    label: "Workspace Directory",
    description: "Walk a workspace directory and index all allowed files in one run.",
  },
];

const fieldGroupClassName = "space-y-2 text-sm text-text-md";
const fieldLabelClassName =
  "text-[11px] font-semibold uppercase tracking-[0.18em] text-text-hi";
const fieldInputClassName =
  "w-full rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:bg-surface-1 focus:outline-none";

const prettyJson = (value: unknown) => JSON.stringify(value ?? {}, null, 2);

const formatTimestamp = (value?: string | null) => {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
};

const asErrorMessage = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

// ─── ScopeComboBox ───────────────────────────────────────────────────────────
// Dropdown that shows known options + "Create new…" and allows free-text entry.

function ScopeComboBox({
  label,
  value,
  options,
  placeholder,
  allowEmpty,
  onCreate,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  placeholder?: string;
  allowEmpty?: boolean;
  onCreate?: (name: string) => Promise<void>;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setCreating(false);
        setNewName("");
        setCreateError(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSelect = (option: string) => {
    if (option === CREATE_NEW_VALUE) {
      setCreating(true);
      setNewName("");
      setCreateError(null);
      return;
    }
    onChange(option);
    setOpen(false);
  };

  const handleCreate = async () => {
    const trimmed = newName.trim();
    if (!trimmed) return;
    if (onCreate) {
      setCreateError(null);
      try {
        await onCreate(trimmed);
      } catch (err) {
        setCreateError(err instanceof Error ? err.message : "Failed to create.");
        return;
      }
    }
    onChange(trimmed);
    setCreating(false);
    setNewName("");
    setOpen(false);
  };

  const displayOptions = allowEmpty ? ["", ...options] : options;
  const allOptions = [...displayOptions.filter((o) => o !== value), value].filter(
    (o, i, arr) => arr.indexOf(o) === i
  );

  return (
    <div ref={ref} className={fieldGroupClassName}>
      <span className={fieldLabelClassName}>{label}</span>
      <div className="relative">
        <button
          type="button"
          onClick={() => {
            setOpen((prev) => !prev);
            setCreating(false);
          }}
          className={`${fieldInputClassName} flex items-center justify-between gap-2 text-left`}
        >
          <span className={value ? "text-text-hi" : "text-text-lo"}>
            {value || placeholder || "—"}
          </span>
          <svg
            className={`h-4 w-4 shrink-0 text-text-md transition-transform ${open ? "rotate-180" : ""}`}
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fillRule="evenodd"
              d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
              clipRule="evenodd"
            />
          </svg>
        </button>

        {open && (
          <div className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-2xl border border-subtle bg-surface-1 shadow-[0_8px_24px_rgba(0,0,0,0.25)]">
            {creating ? (
              <div className="p-3 space-y-2">
                <input
                  autoFocus
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleCreate();
                    if (e.key === "Escape") { setCreating(false); setNewName(""); }
                  }}
                  placeholder={`New ${label.toLowerCase()} name…`}
                  className="w-full rounded-xl border border-subtle bg-surface-2 px-3 py-2 text-sm text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:outline-none"
                />
                {createError && (
                  <p className="text-[11px] text-rose-400">{createError}</p>
                )}
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void handleCreate()}
                    className="rounded-xl border border-sky-300/30 bg-accent-sky px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-sky-token"
                  >
                    Create
                  </button>
                  <button
                    type="button"
                    onClick={() => { setCreating(false); setNewName(""); }}
                    className="rounded-xl border border-subtle bg-surface-2 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-md"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <ul className="max-h-52 overflow-y-auto py-1">
                {allOptions.map((option) => (
                  <li key={option || "__empty__"}>
                    <button
                      type="button"
                      onClick={() => handleSelect(option)}
                      className={`w-full px-4 py-2.5 text-left text-sm transition hover:bg-surface-2 ${
                        option === value
                          ? "font-semibold text-text-hi"
                          : option
                          ? "text-text-md"
                          : "italic text-text-lo"
                      }`}
                    >
                      {option || "none (clear)"}
                    </button>
                  </li>
                ))}
                <li className="border-t border-subtle">
                  <button
                    type="button"
                    onClick={() => handleSelect(CREATE_NEW_VALUE)}
                    className="w-full px-4 py-2.5 text-left text-sm text-text-sky-token transition hover:bg-surface-2"
                  >
                    + Create new…
                  </button>
                </li>
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function RagModeButton({
  active,
  label,
  description,
  onClick,
}: {
  active: boolean;
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-2xl border px-4 py-3 text-left transition ${
        active
          ? "border-sky-300/35 bg-accent-sky text-text-hi shadow-[0_8px_18px_rgba(14,165,233,0.16)]"
          : "border-subtle bg-surface-1 text-text-md hover:border-subtle hover:bg-surface-1"
      }`}
    >
      <div className="text-base font-semibold tracking-[-0.02em]">{label}</div>
      <div className={`mt-1 text-sm leading-6 ${active ? "text-text-sky-token" : "text-text-md"}`}>
        {description}
      </div>
    </button>
  );
}

export default function RagKnowledgeScreen() {
  const { user: authUser } = useAuth();
  const [collectionName, setCollectionName] = useState(DEFAULT_COLLECTION);
  const [namespace, setNamespace] = useState(DEFAULT_NAMESPACE);
  const [userId, setUserId] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // Available options fetched from the API / derived from documents
  const [availableCollections, setAvailableCollections] = useState<string[]>([DEFAULT_COLLECTION]);
  const [collectionsLoading, setCollectionsLoading] = useState(true);

  const [documents, setDocuments] = useState<RagDocumentSummary[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);

  const [chunkResponse, setChunkResponse] = useState<RagDocumentChunksResponse | null>(null);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksError, setChunksError] = useState<string | null>(null);

  const [indexMode, setIndexMode] = useState<IndexMode>("markdown");
  const [documentIdInput, setDocumentIdInput] = useState("");
  const [sourceUriInput, setSourceUriInput] = useState("");
  const [markdownText, setMarkdownText] = useState("");
  const [plainText, setPlainText] = useState("");
  const [workspacePath, setWorkspacePath] = useState("docs/rag-playbook.md");
  const [directoryPath, setDirectoryPath] = useState("docs");
  const [recursiveDirectory, setRecursiveDirectory] = useState(true);
  const [metadataText, setMetadataText] = useState(prettyJson({}));
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [indexing, setIndexing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [replacing, setReplacing] = useState(false);

  // Facet options derived from loaded documents
  const availableNamespaces = useMemo(
    () => [...new Set(documents.map((d) => d.namespace).filter((v): v is string => Boolean(v)))],
    [documents]
  );
  const availableWorkspaceIds = useMemo(
    () => [...new Set(documents.map((d) => d.workspace_id).filter((v): v is string => Boolean(v)))],
    [documents]
  );
  const availableTenantIds = useMemo(
    () => [...new Set(documents.map((d) => d.tenant_id).filter((v): v is string => Boolean(v)))],
    [documents]
  );

  // Fetch available collections on mount
  useEffect(() => {
    setCollectionsLoading(true);
    apiFetch(`${apiUrl}/rag/collections`)
      .then((res) => res.json())
      .then((body: unknown) => {
        const cols = (body as { collections?: unknown }).collections;
        if (Array.isArray(cols)) {
          const names = cols.filter((c): c is string => typeof c === "string" && Boolean(c));
          setAvailableCollections(names.length > 0 ? names : [DEFAULT_COLLECTION]);
        }
      })
      .catch(() => {
        setAvailableCollections([DEFAULT_COLLECTION]);
      })
      .finally(() => setCollectionsLoading(false));
  }, []);

  useEffect(() => {
    if (authUser?.user_id) {
      setUserId(authUser.user_id);
    }
  }, [authUser?.user_id]);

  const selectedDocument = useMemo(() => {
    if (chunkResponse?.document && chunkResponse.document.document_id === selectedDocumentId) {
      return chunkResponse.document;
    }
    return documents.find((document) => document.document_id === selectedDocumentId) ?? null;
  }, [chunkResponse, documents, selectedDocumentId]);

  const scopeSummary = useMemo(
    () =>
      [
        collectionName.trim() ? `Collection ${collectionName.trim()}` : null,
        namespace.trim() ? `Namespace ${namespace.trim()}` : null,
        userId.trim() ? `User ${userId.trim()}` : null,
        workspaceId.trim() ? `Workspace ${workspaceId.trim()}` : null,
        tenantId.trim() ? `Tenant ${tenantId.trim()}` : null,
      ].filter((value): value is string => Boolean(value)),
    [collectionName, namespace, tenantId, userId, workspaceId]
  );

  const buildScopeParams = () => {
    const params = new URLSearchParams();
    if (collectionName.trim()) params.set("collection_name", collectionName.trim());
    if (namespace.trim()) params.set("namespace", namespace.trim());
    if (userId.trim()) params.set("user_id", userId.trim());
    if (workspaceId.trim()) params.set("workspace_id", workspaceId.trim());
    if (tenantId.trim()) params.set("tenant_id", tenantId.trim());
    if (searchQuery.trim()) params.set("query", searchQuery.trim());
    return params;
  };

  const refreshDocuments = async () => {
    setDocumentsLoading(true);
    setDocumentsError(null);
    try {
      const params = buildScopeParams();
      const response = await apiFetch(`${apiUrl}/rag/documents?${params.toString()}`);
      const body = (await response.json()) as RagDocumentListResponse | { detail?: string };
      if (!response.ok) {
        throw new Error(
          typeof (body as { detail?: string }).detail === "string"
            ? (body as { detail: string }).detail
            : `Failed to load knowledge documents (${response.status})`
        );
      }
      const nextDocuments = (body as RagDocumentListResponse).documents;
      setDocuments(nextDocuments);
      if (
        selectedDocumentId &&
        !nextDocuments.some((document) => document.document_id === selectedDocumentId)
      ) {
        setSelectedDocumentId(null);
        setChunkResponse(null);
      }
    } catch (error) {
      setDocumentsError(asErrorMessage(error, "Failed to load knowledge documents."));
    } finally {
      setDocumentsLoading(false);
    }
  };

  const loadDocumentChunks = async (documentId: string) => {
    setChunksLoading(true);
    setChunksError(null);
    try {
      const params = buildScopeParams();
      params.set("document_id", documentId);
      const response = await apiFetch(`${apiUrl}/rag/documents/chunks?${params.toString()}`);
      const body = (await response.json()) as RagDocumentChunksResponse | { detail?: string };
      if (!response.ok) {
        throw new Error(
          typeof (body as { detail?: string }).detail === "string"
            ? (body as { detail: string }).detail
            : `Failed to load document chunks (${response.status})`
        );
      }
      setChunkResponse(body as RagDocumentChunksResponse);
    } catch (error) {
      setChunksError(asErrorMessage(error, "Failed to load document chunks."));
    } finally {
      setChunksLoading(false);
    }
  };

  // Refresh collections list after creating a new one
  const refreshCollections = async () => {
    try {
      const res = await apiFetch(`${apiUrl}/rag/collections`);
      const body = (await res.json()) as { collections?: unknown };
      const cols = body.collections;
      if (Array.isArray(cols)) {
        const names = cols.filter((c): c is string => typeof c === "string" && Boolean(c));
        if (names.length > 0) setAvailableCollections(names);
      }
    } catch {
      // keep existing list
    }
  };

  const createCollection = async (name: string) => {
    const res = await apiFetch(`${apiUrl}/rag/collections/ensure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collection_name: name }),
    });
    if (!res.ok) {
      const body = (await res.json()) as { detail?: string };
      throw new Error(body.detail ?? `Failed to create collection (${res.status})`);
    }
    await refreshCollections();
  };

  useEffect(() => {
    if (!userId.trim()) return;
    void refreshDocuments();
  }, [collectionName, namespace, tenantId, userId, workspaceId]);

  const parseMetadata = () => {
    const parsed = JSON.parse(metadataText || "{}") as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Metadata must be a JSON object.");
    }
    return parsed as Record<string, unknown>;
  };

  const buildIndexPayload = (documentIdOverride?: string) => {
    const metadata = parseMetadata();
    const payload: Record<string, unknown> = {
      mode: indexMode,
      collection_name: collectionName.trim() || null,
      namespace: namespace.trim() || null,
      tenant_id: tenantId.trim() || null,
      user_id: userId.trim() || null,
      workspace_id: workspaceId.trim() || null,
      metadata,
    };
    const effectiveDocumentId = documentIdOverride || documentIdInput.trim();
    const effectiveSourceUri = sourceUriInput.trim() || documentIdOverride || documentIdInput.trim();
    if (effectiveDocumentId) payload.document_id = effectiveDocumentId;
    if (effectiveSourceUri) payload.source_uri = effectiveSourceUri;
    if (indexMode === "markdown") {
      const value = markdownText.trim();
      if (!value) throw new Error("Markdown content is required.");
      payload.markdown_text = value;
    } else if (indexMode === "text") {
      const value = plainText.trim();
      if (!value) throw new Error("Text content is required.");
      payload.text = value;
    } else if (indexMode === "workspace_file") {
      const value = workspacePath.trim();
      if (!value) throw new Error("Workspace path is required.");
      payload.path = value;
    } else {
      const value = directoryPath.trim();
      if (!value) throw new Error("Directory path is required.");
      payload.directory_path = value;
      payload.recursive = recursiveDirectory;
    }
    return payload;
  };

  const submitIndex = async () => {
    setFormError(null);
    setNotice(null);
    let payload: Record<string, unknown>;
    try {
      payload = buildIndexPayload();
    } catch (error) {
      setFormError(asErrorMessage(error, "Invalid knowledge indexing payload."));
      return;
    }
    setIndexing(true);
    try {
      const response = await apiFetch(`${apiUrl}/rag/index`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = (await response.json()) as Record<string, unknown> | { detail?: string };
      if (!response.ok) {
        throw new Error(
          typeof (body as { detail?: string }).detail === "string"
            ? (body as { detail: string }).detail
            : `Failed to index content (${response.status})`
        );
      }
      const result = body as Record<string, unknown>;
      setNotice("Indexed content into the knowledge base successfully.");
      const resultDocumentId =
        typeof result.document_id === "string" && result.document_id
          ? result.document_id
          : typeof payload.document_id === "string" && payload.document_id
            ? payload.document_id
            : null;
      await refreshDocuments();
      if (resultDocumentId) {
        setSelectedDocumentId(resultDocumentId);
        await loadDocumentChunks(resultDocumentId);
      }
    } catch (error) {
      setFormError(asErrorMessage(error, "Failed to index content."));
    } finally {
      setIndexing(false);
    }
  };

  const replaceSelectedDocument = async () => {
    if (!selectedDocumentId) {
      setFormError("Select a document to replace.");
      return;
    }
    if (indexMode !== "markdown" && indexMode !== "text") {
      setFormError("Replace currently supports pasted markdown or pasted text modes only.");
      return;
    }
    setFormError(null);
    setNotice(null);
    let payload: Record<string, unknown>;
    try {
      payload = buildIndexPayload(selectedDocumentId);
    } catch (error) {
      setFormError(asErrorMessage(error, "Invalid replacement payload."));
      return;
    }
    setReplacing(true);
    try {
      const response = await apiFetch(
        `${apiUrl}/rag/documents?document_id=${encodeURIComponent(selectedDocumentId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      const body = (await response.json()) as RagReplaceResponse | { detail?: string };
      if (!response.ok) {
        throw new Error(
          typeof (body as { detail?: string }).detail === "string"
            ? (body as { detail: string }).detail
            : `Failed to replace document (${response.status})`
        );
      }
      const result = body as RagReplaceResponse;
      setNotice("Replaced indexed document content.");
      await refreshDocuments();
      setSelectedDocumentId(result.deleted.document_id);
      await loadDocumentChunks(result.deleted.document_id);
    } catch (error) {
      setFormError(asErrorMessage(error, "Failed to replace document."));
    } finally {
      setReplacing(false);
    }
  };

  const deleteSelectedDocument = async () => {
    if (!selectedDocumentId) return;
    const confirmed = window.confirm(`Delete indexed document ${selectedDocumentId}?`);
    if (!confirmed) return;
    setDeleting(true);
    setFormError(null);
    setNotice(null);
    try {
      const params = buildScopeParams();
      params.set("document_id", selectedDocumentId);
      const response = await apiFetch(`${apiUrl}/rag/documents?${params.toString()}`, {
        method: "DELETE",
      });
      const body = (await response.json()) as RagDeleteResponse | { detail?: string };
      if (!response.ok) {
        throw new Error(
          typeof (body as { detail?: string }).detail === "string"
            ? (body as { detail: string }).detail
            : `Failed to delete document (${response.status})`
        );
      }
      const result = body as RagDeleteResponse;
      setNotice(`Deleted ${result.document_id} (${result.deleted_chunk_count} chunks removed).`);
      setSelectedDocumentId(null);
      setChunkResponse(null);
      await refreshDocuments();
    } catch (error) {
      setFormError(asErrorMessage(error, "Failed to delete document."));
    } finally {
      setDeleting(false);
    }
  };

  const clearForm = () => {
    setDocumentIdInput("");
    setSourceUriInput("");
    setMarkdownText("");
    setPlainText("");
    setWorkspacePath("docs/rag-playbook.md");
    setDirectoryPath("docs");
    setRecursiveDirectory(true);
    setMetadataText(prettyJson({}));
    setFormError(null);
    setNotice(null);
  };

  return (
    <AppShell
      activeScreen="rag"
      title="Knowledge Base"
      breadcrumbs={[
        { label: "Project", href: "/project" },
        { label: "Knowledge Base" },
      ]}
      actions={
        <>
          <button
            type="button"
            className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-sky-300/35 hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void refreshDocuments()}
            disabled={documentsLoading}
          >
            Refresh
          </button>
          <button
            type="button"
            className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-default-theme hover:bg-slate-950/35 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void submitIndex()}
            disabled={indexing}
          >
            {indexing ? "Indexing..." : "Index Now"}
          </button>
        </>
      }
    >
      <ScreenHeader
        eyebrow="Knowledge Base"
        title="Knowledge Base"
        description="Connect documents and workspace content so AI workflows can retrieve the right context."
        activeScreen="rag"
        theme="studio"
        compact
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <ScopeComboBox
            label="Collection"
            value={collectionName}
            options={collectionsLoading ? [DEFAULT_COLLECTION] : availableCollections}
            placeholder="rag_default"
            onCreate={createCollection}
            onChange={(v) => setCollectionName(v || DEFAULT_COLLECTION)}
          />
          <ScopeComboBox
            label="Namespace"
            value={namespace}
            options={availableNamespaces}
            placeholder="docs"
            allowEmpty
            onChange={setNamespace}
          />
          <ScopeComboBox
            label="Workspace ID"
            value={workspaceId}
            options={availableWorkspaceIds}
            placeholder="optional"
            allowEmpty
            onChange={setWorkspaceId}
          />
          <ScopeComboBox
            label="Tenant ID"
            value={tenantId}
            options={availableTenantIds}
            placeholder="optional"
            allowEmpty
            onChange={setTenantId}
          />
          <label className={fieldGroupClassName}>
            <span className={fieldLabelClassName}>Search</span>
            <div className="flex gap-2">
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                className={fieldInputClassName}
                placeholder="document, source, metadata..."
              />
              <button
                type="button"
                className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-sky-300/35 hover:bg-surface-1"
                onClick={() => void refreshDocuments()}
              >
                Go
              </button>
            </div>
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {scopeSummary.map((item) => (
            <div
              key={item}
              className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-hi"
            >
              {item}
            </div>
          ))}
        </div>
      </ScreenHeader>

      <div className="mt-3 grid gap-3 xl:grid-cols-[1.2fr,1fr,1fr]">
        <section className="rounded-[24px] border border-subtle bg-gradient-panel p-4 shadow-[0_12px_32px_rgba(15,23,42,0.14),inset_0_1px_0_rgba(255,255,255,0.05)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.24em] text-text-sky-token">
                Index New
              </div>
              <h2 className="mt-2 text-base font-semibold tracking-tight text-text-hi">Manual Indexing</h2>
              <p className="mt-2 text-sm leading-6 text-text-md">
                Choose a source mode, attach scope, then index new content or replace the currently
                selected document.
              </p>
            </div>
            <button
              type="button"
              className="rounded-full border border-subtle bg-surface-1 px-4 py-2 text-sm font-semibold text-text-hi transition hover:border-subtle hover:bg-surface-1"
              onClick={clearForm}
            >
              Clear Form
            </button>
          </div>

          <div className="mt-6 grid gap-3">
            {INDEX_MODES.map((mode) => (
              <RagModeButton
                key={mode.id}
                active={indexMode === mode.id}
                label={mode.label}
                description={mode.description}
                onClick={() => setIndexMode(mode.id)}
              />
            ))}
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className={fieldGroupClassName}>
              <span className={fieldLabelClassName}>Document ID</span>
              <input
                value={documentIdInput}
                onChange={(event) => setDocumentIdInput(event.target.value)}
                className="w-full rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:outline-none"
                placeholder="docs/user-guide.md"
              />
            </label>
            <label className={fieldGroupClassName}>
              <span className={fieldLabelClassName}>Source URI</span>
              <input
                value={sourceUriInput}
                onChange={(event) => setSourceUriInput(event.target.value)}
                className="w-full rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:outline-none"
                placeholder="docs/user-guide.md"
              />
            </label>
          </div>

          {indexMode === "markdown" ? (
            <label className={`mt-4 block ${fieldGroupClassName}`}>
              <span className={fieldLabelClassName}>Markdown Content</span>
              <textarea
                value={markdownText}
                onChange={(event) => setMarkdownText(event.target.value)}
                className="h-64 w-full rounded-3xl border border-subtle bg-surface-1 px-4 py-4 font-mono text-sm text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:outline-none"
                placeholder="# User Guide&#10;&#10;Paste markdown content here."
              />
            </label>
          ) : null}

          {indexMode === "text" ? (
            <label className={`mt-4 block ${fieldGroupClassName}`}>
              <span className={fieldLabelClassName}>Plain Text</span>
              <textarea
                value={plainText}
                onChange={(event) => setPlainText(event.target.value)}
                className="h-64 w-full rounded-3xl border border-subtle bg-surface-1 px-4 py-4 font-mono text-sm text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:outline-none"
                placeholder="Paste plain text content here."
              />
            </label>
          ) : null}

          {indexMode === "workspace_file" ? (
            <label className={`mt-4 block ${fieldGroupClassName}`}>
              <span className={fieldLabelClassName}>Workspace File Path</span>
              <input
                value={workspacePath}
                onChange={(event) => setWorkspacePath(event.target.value)}
                className="w-full rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:outline-none"
                placeholder="docs/rag-playbook.md"
              />
            </label>
          ) : null}

          {indexMode === "workspace_directory" ? (
            <div className="mt-3 grid gap-3 md:grid-cols-[1fr,auto]">
              <label className={fieldGroupClassName}>
                <span className={fieldLabelClassName}>Workspace Directory</span>
                <input
                  value={directoryPath}
                  onChange={(event) => setDirectoryPath(event.target.value)}
                  className="w-full rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:outline-none"
                  placeholder="docs"
                />
              </label>
              <label className="flex items-center gap-3 rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-text-hi">
                <input
                  type="checkbox"
                  checked={recursiveDirectory}
                  onChange={(event) => setRecursiveDirectory(event.target.checked)}
                  className="h-4 w-4 rounded border-subtle"
                />
                Recursive
              </label>
            </div>
          ) : null}

          <label className={`mt-4 block ${fieldGroupClassName}`}>
            <span className={fieldLabelClassName}>Metadata JSON</span>
            <textarea
              value={metadataText}
              onChange={(event) => setMetadataText(event.target.value)}
              className="h-44 w-full rounded-3xl border border-subtle bg-surface-1 px-4 py-4 font-mono text-sm text-text-hi placeholder:text-text-lo focus:border-sky-300/40 focus:outline-none"
            />
          </label>

          {formError ? (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {formError}
            </div>
          ) : null}
          {notice ? (
            <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
              {notice}
            </div>
          ) : null}

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              className="rounded-full border border-subtle bg-surface-1 px-5 py-3 text-sm font-semibold text-text-hi transition hover:border-default-theme hover:bg-slate-950/35 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => void submitIndex()}
              disabled={indexing}
            >
              {indexing ? "Indexing..." : "Index Now"}
            </button>
            <button
              type="button"
              className="rounded-full border border-subtle bg-surface-1 px-5 py-3 text-sm font-semibold text-text-hi transition hover:border-subtle hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => void replaceSelectedDocument()}
              disabled={replacing || !selectedDocumentId}
            >
              {replacing ? "Replacing..." : "Replace Selected"}
            </button>
          </div>
        </section>

        <section className="rounded-[24px] border border-subtle bg-gradient-panel p-4 shadow-[0_12px_32px_rgba(15,23,42,0.14),inset_0_1px_0_rgba(255,255,255,0.05)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.24em] text-text-sky-token">
                Documents
              </div>
              <h2 className="mt-2 text-base font-semibold tracking-tight text-text-hi">Indexed Inventory</h2>
              <p className="mt-2 text-sm leading-6 text-text-md">
                Review indexed documents in the active scope, then open one to inspect its stored
                chunks.
              </p>
            </div>
            <div className="rounded-2xl border border-subtle bg-surface-1 px-4 py-3 text-right">
              <div className="text-xs font-semibold uppercase tracking-[0.24em] text-text-md">
                Loaded
              </div>
              <div className="mt-1 text-base font-semibold tracking-tight text-text-hi">
                {documents.length}
              </div>
            </div>
          </div>

          {documentsError ? (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {documentsError}
            </div>
          ) : null}

          <div className="mt-6 space-y-3">
            {documentsLoading ? (
              <div className="rounded-3xl border border-dashed border-subtle bg-surface-1 px-4 py-12 text-center text-sm text-text-md">
                Loading indexed documents...
              </div>
            ) : documents.length === 0 ? (
              <div className="rounded-3xl border border-dashed border-subtle bg-surface-1 px-4 py-12 text-center text-sm text-text-md">
                No indexed documents match the current scope.
              </div>
            ) : (
              documents.map((document) => {
                const selected = document.document_id === selectedDocumentId;
                return (
                  <button
                    key={document.document_id}
                    type="button"
                    onClick={() => {
                      setSelectedDocumentId(document.document_id);
                      void loadDocumentChunks(document.document_id);
                    }}
                    className={`w-full rounded-3xl border p-4 text-left transition ${
                      selected
                        ? "border-sky-300/35 bg-accent-sky text-text-hi shadow-[0_8px_18px_rgba(14,165,233,0.16)]"
                        : "border-subtle bg-surface-1 text-text-hi hover:border-subtle hover:bg-surface-1"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="truncate text-lg font-semibold tracking-[-0.02em]">
                          {document.filename || document.document_id}
                        </div>
                        <div
                          className={`mt-1 truncate text-xs uppercase tracking-[0.14em] ${
                            selected ? "text-text-sky-token" : "text-text-md"
                          }`}
                        >
                          {document.source_uri}
                        </div>
                      </div>
                      <div
                        className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] ${
                          selected ? "bg-surface-2 text-text-hi" : "bg-surface-1 text-text-md"
                        }`}
                      >
                        {document.chunk_count} chunks
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {document.namespace ? (
                        <div
                          className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] ${
                            selected ? "bg-surface-1 text-text-hi" : "bg-surface-1 text-text-md"
                          }`}
                        >
                          {document.namespace}
                        </div>
                      ) : null}
                      {document.chunking_strategy ? (
                        <div
                          className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] ${
                            selected ? "bg-surface-1 text-text-hi" : "bg-surface-1 text-text-md"
                          }`}
                        >
                          {document.chunking_strategy}
                        </div>
                      ) : null}
                      {document.content_type ? (
                        <div
                          className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] ${
                            selected ? "bg-surface-1 text-text-hi" : "bg-surface-1 text-text-md"
                          }`}
                        >
                          {document.content_type}
                        </div>
                      ) : null}
                    </div>
                    <div
                      className={`mt-4 text-[11px] font-medium uppercase tracking-[0.14em] ${
                        selected ? "text-text-sky-token" : "text-text-md"
                      }`}
                    >
                      Indexed {formatTimestamp(document.indexed_at)}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        <section className="rounded-[24px] border border-subtle bg-gradient-panel p-4 shadow-[0_12px_32px_rgba(15,23,42,0.14),inset_0_1px_0_rgba(255,255,255,0.05)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.24em] text-text-sky-token">
                Inspector
              </div>
              <h2 className="mt-2 text-base font-semibold tracking-tight text-text-hi">Document Details</h2>
              <p className="mt-2 text-sm leading-6 text-text-md">
                Inspect document metadata and chunk payloads before you rerank or generate against
                them.
              </p>
            </div>
            <button
              type="button"
              className="rounded-full border border-subtle bg-surface-1 px-4 py-2 text-sm font-semibold text-text-hi transition hover:border-subtle hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => selectedDocumentId && void loadDocumentChunks(selectedDocumentId)}
              disabled={!selectedDocumentId || chunksLoading}
            >
              Reload
            </button>
          </div>

          {chunksError ? (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {chunksError}
            </div>
          ) : null}

          {!selectedDocument ? (
            <div className="mt-6 rounded-3xl border border-dashed border-subtle bg-surface-1 px-4 py-12 text-center text-sm text-text-md">
              Select a document to inspect its stored chunks and lifecycle actions.
            </div>
          ) : (
            <>
              <div className="mt-6 rounded-3xl border border-subtle bg-surface-1 p-4">
                <div className="text-base font-semibold tracking-tight text-text-hi">
                  {selectedDocument.filename || selectedDocument.document_id}
                </div>
                <div className="mt-2 break-all text-xs uppercase tracking-[0.14em] text-text-md">
                  {selectedDocument.source_uri}
                </div>
                <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
                  <div>
                    <dt className={fieldLabelClassName}>Document ID</dt>
                    <dd className="mt-1 break-all text-text-md">{selectedDocument.document_id}</dd>
                  </div>
                  <div>
                    <dt className={fieldLabelClassName}>Indexed</dt>
                    <dd className="mt-1 text-text-md">{formatTimestamp(selectedDocument.indexed_at)}</dd>
                  </div>
                  <div>
                    <dt className={fieldLabelClassName}>Namespace</dt>
                    <dd className="mt-1 text-text-md">{selectedDocument.namespace || "—"}</dd>
                  </div>
                  <div>
                    <dt className={fieldLabelClassName}>Chunk Count</dt>
                    <dd className="mt-1 text-text-md">{selectedDocument.chunk_count}</dd>
                  </div>
                </dl>
                <div className="mt-4 flex flex-wrap gap-3">
                  <button
                    type="button"
                    className="rounded-full border border-rose-300/20 bg-accent-rose px-4 py-2 text-sm font-semibold text-text-rose-token transition hover:border-rose-300/30 hover:bg-accent-rose disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => void deleteSelectedDocument()}
                    disabled={deleting}
                  >
                    {deleting ? "Deleting..." : "Delete Document"}
                  </button>
                  <button
                    type="button"
                    className="rounded-full border border-subtle bg-surface-1 px-4 py-2 text-sm font-semibold text-text-hi transition hover:border-subtle hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => void replaceSelectedDocument()}
                    disabled={replacing || (indexMode !== "markdown" && indexMode !== "text")}
                  >
                    {replacing ? "Replacing..." : "Replace With Form"}
                  </button>
                </div>
              </div>

              <div className="mt-6">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[22px] font-semibold tracking-[-0.03em] text-text-hi">Stored Chunks</div>
                  <div className="text-xs uppercase tracking-[0.24em] text-text-md">
                    {chunkResponse?.chunks.length ?? 0} loaded
                  </div>
                </div>
                <div className="mt-3 space-y-3">
                  {chunksLoading ? (
                    <div className="rounded-3xl border border-dashed border-subtle bg-surface-1 px-4 py-10 text-center text-sm text-text-md">
                      Loading chunks...
                    </div>
                  ) : (
                    chunkResponse?.chunks.map((chunk) => (
                      <article
                        key={chunk.chunk_id}
                        className="rounded-3xl border border-subtle bg-surface-1 p-4"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-base font-semibold tracking-[-0.02em] text-text-hi">
                            Chunk {chunk.chunk_index ?? "—"}
                          </div>
                          <div className="truncate text-[11px] uppercase tracking-[0.14em] text-text-md">
                            {chunk.chunk_id}
                          </div>
                        </div>
                        <div className="mt-3 whitespace-pre-wrap text-sm leading-6 text-text-md">
                          {chunk.text}
                        </div>
                        {Object.keys(chunk.metadata || {}).length > 0 ? (
                          <pre className="mt-3 overflow-x-auto rounded-2xl bg-slate-950 px-4 py-3 text-xs text-slate-50">
                            {prettyJson(chunk.metadata)}
                          </pre>
                        ) : null}
                      </article>
                    ))
                  )}
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </AppShell>
  );
}
