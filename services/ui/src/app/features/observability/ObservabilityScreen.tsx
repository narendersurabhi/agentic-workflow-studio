"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useShell } from "../../lib/shell";
import FeedbackInsightsPanel from "../../components/feedback/FeedbackInsightsPanel";
import { apiFetch } from "../../lib/auth";
import type { FeedbackSummaryResponse } from "../../lib/feedback";
import { useAppTheme } from "../../lib/theme";

const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";

type EventEnvelope = {
  type: string;
  payload: Record<string, unknown>;
  job_id?: string;
  occurred_at?: string;
};

type Job = {
  id: string;
  goal: string;
  status: string;
  created_at: string;
  updated_at: string;
  planning_mode?: string;
  current_revision_number?: number;
  metadata?: Record<string, unknown>;
};

type Task = {
  id: string;
  name: string;
  status: string;
  capability_id?: string | null;
  error?: string | null;
};

type JobDetails = {
  job_id: string;
  job_status?: string | null;
  job_error?: string | null;
  tasks?: Task[];
  planning_mode?: string;
  current_revision_number?: number;
};

const STATUS_COLORS: Record<string, string> = {
  succeeded: "border-emerald-300/25 bg-accent-emerald text-text-emerald-token",
  completed: "border-emerald-300/25 bg-accent-emerald text-text-emerald-token",
  accepted: "border-emerald-300/25 bg-accent-emerald text-text-emerald-token",
  failed: "border-rose-300/20 bg-accent-rose text-text-rose-token",
  canceled: "border-rose-300/20 bg-accent-rose text-text-rose-token",
  running: "border-sky-300/22 bg-accent-sky text-text-sky-token",
  pending: "border-amber-300/22 bg-accent-amber text-text-amber-token",
};

function jobStatusColor(status: string): string {
  return STATUS_COLORS[status] ?? "border-subtle bg-surface-1 text-text-md";
}

export default function ObservabilityScreen() {
  const { theme } = useAppTheme();
  const isStudio = theme === "dark";
  const searchParams = useSearchParams();
  const initialJobId = searchParams.get("job");

  const [feedbackSummary, setFeedbackSummary] = useState<FeedbackSummaryResponse | null>(null);
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set());

  // Jobs state
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(initialJobId);
  const [jobDetails, setJobDetails] = useState<JobDetails | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [showAllJobs, setShowAllJobs] = useState(false);
  const selectedJobIdRef = useRef<string | null>(initialJobId);

  const loadJobs = useCallback(async () => {
    setJobsLoading(true);
    setJobsError(null);
    try {
      const res = await apiFetch(`${apiUrl}/jobs?limit=100`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as { items?: Job[] } | Job[];
      setJobs(Array.isArray(data) ? data : (data.items ?? []));
    } catch (e) {
      setJobsError(e instanceof Error ? e.message : "Failed to load jobs.");
    } finally {
      setJobsLoading(false);
    }
  }, []);

  const loadJobDetails = useCallback(async (jobId: string) => {
    setDetailsLoading(true);
    setDetailsError(null);
    setJobDetails(null);
    try {
      const res = await apiFetch(`${apiUrl}/jobs/${encodeURIComponent(jobId)}/details`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as JobDetails;
      setJobDetails(data);
    } catch (e) {
      setDetailsError(e instanceof Error ? e.message : "Failed to load job details.");
    } finally {
      setDetailsLoading(false);
    }
  }, []);

  const loadFeedbackSummary = useCallback(async () => {
    setFeedbackLoading(true);
    setFeedbackError(null);
    try {
      const res = await apiFetch(`${apiUrl}/feedback/summary?limit=500`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as FeedbackSummaryResponse;
      setFeedbackSummary(data);
    } catch (e) {
      setFeedbackError(e instanceof Error ? e.message : "Failed to load feedback summary.");
    } finally {
      setFeedbackLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFeedbackSummary();
  }, [loadFeedbackSummary]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  // Auto-open job from URL query param
  useEffect(() => {
    if (initialJobId) {
      selectedJobIdRef.current = initialJobId;
      void loadJobDetails(initialJobId);
    }
  }, [initialJobId, loadJobDetails]);

  // Keep ref in sync for EventSource handler
  useEffect(() => {
    selectedJobIdRef.current = selectedJobId;
  }, [selectedJobId]);

  useEffect(() => {
    const source = new EventSource(`${apiUrl}/events/stream`);
    source.onmessage = (e) => {
      try {
        const envelope = JSON.parse(e.data) as EventEnvelope;
        if (envelope.type === "task.heartbeat") return;
        setEvents((prev) => [envelope, ...prev].slice(0, 50));
        // Refresh jobs list on terminal events
        if (envelope.type === "task.completed" || envelope.type === "task.failed") {
          void loadJobs();
          const activeId = selectedJobIdRef.current;
          if (activeId && envelope.job_id === activeId) {
            void loadJobDetails(activeId);
          }
        }
      } catch {
        return;
      }
    };
    source.onerror = () => {
      // silently ignore; browser will reconnect automatically for EventSource
    };
    return () => source.close();
  }, [loadJobs, loadJobDetails]);

  useEffect(() => {
    setExpandedEvents(new Set());
  }, [events.length]);

  const toggleEvent = (index: number) => {
    setExpandedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  useShell({ title: "Observability", breadcrumbs: [{ label: "Observability" }] });

  return (
    <div className="mx-auto max-w-5xl space-y-4 px-4 py-6">
        <FeedbackInsightsPanel
          summary={feedbackSummary}
          loading={feedbackLoading}
          error={feedbackError}
          onRefresh={() => void loadFeedbackSummary()}
          theme={isStudio ? "studio" : "default"}
        />

        {/* ── Jobs ── */}
        <section className={`rounded-[24px] p-4 ${isStudio ? "border border-subtle bg-gradient-panel text-text-hi shadow-[0_12px_32px_rgba(15,23,42,0.14),inset_0_1px_0_rgba(255,255,255,0.05)]" : "border border-slate-100 bg-white shadow-sm text-slate-900"}`}>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold">Jobs</h2>
              <p className="mt-1 text-xs text-text-md">All submitted runs — click to inspect.</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                className="rounded-lg border border-subtle bg-surface-1 px-3 py-1.5 text-xs text-text-md transition hover:bg-surface-2"
                onClick={() => void loadJobs()}
              >
                Refresh
              </button>
              <button
                className="rounded-lg border border-subtle bg-surface-1 px-3 py-1.5 text-xs text-text-md transition hover:bg-surface-2"
                onClick={() => setShowAllJobs((p) => !p)}
              >
                {showAllJobs ? "Show recent" : "Show all"}
              </button>
            </div>
          </div>

          {jobsLoading ? (
            <div className="mt-4 text-xs text-text-md">Loading jobs…</div>
          ) : jobsError ? (
            <div className="mt-4 rounded-xl border border-rose-300/20 bg-accent-rose px-3 py-2 text-xs text-text-rose-token">{jobsError}</div>
          ) : jobs.length === 0 ? (
            <div className="mt-4 rounded-xl border border-dashed border-subtle py-8 text-center text-sm text-text-lo">No jobs yet.</div>
          ) : (
            <div className="mt-4 space-y-2">
              {(showAllJobs ? jobs : jobs.slice(0, 10)).map((job) => {
                const isSelected = selectedJobId === job.id;
                return (
                  <div
                    key={job.id}
                    className={`rounded-2xl border p-4 transition ${isSelected ? "border-sky-300/30 bg-accent-sky" : "border-subtle bg-surface-1 hover:bg-surface-2"}`}
                  >
                    <button
                      type="button"
                      className="w-full text-left"
                      onClick={() => {
                        if (isSelected) {
                          setSelectedJobId(null);
                          setJobDetails(null);
                        } else {
                          setSelectedJobId(job.id);
                          void loadJobDetails(job.id);
                        }
                      }}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-sm font-medium text-text-hi line-clamp-2">{job.goal}</p>
                        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${jobStatusColor(job.status)}`}>
                          {job.status}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-text-lo">
                        <span className="font-mono">{job.id.slice(0, 12)}…</span>
                        {job.planning_mode ? <span>{job.planning_mode}</span> : null}
                        <span>{new Date(job.created_at).toLocaleString()}</span>
                      </div>
                    </button>

                    {isSelected ? (
                      <div className="mt-4 border-t border-subtle pt-4">
                        {detailsLoading ? (
                          <div className="text-xs text-text-md">Loading details…</div>
                        ) : detailsError ? (
                          <div className="rounded-xl border border-rose-300/20 bg-accent-rose px-3 py-2 text-xs text-text-rose-token">{detailsError}</div>
                        ) : jobDetails ? (
                          <div className="space-y-4">
                            {jobDetails.job_error ? (
                              <div className="rounded-xl border border-rose-300/20 bg-accent-rose px-3 py-2 text-xs text-text-rose-token">
                                {jobDetails.job_error}
                              </div>
                            ) : null}

                            {/* Tasks */}
                            {jobDetails.tasks && jobDetails.tasks.length > 0 ? (
                              <div>
                                <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-lo">
                                  Tasks ({jobDetails.tasks.length})
                                </div>
                                <div className="space-y-1.5">
                                  {jobDetails.tasks.map((task) => (
                                    <div
                                      key={task.id}
                                      className="flex items-center justify-between gap-3 rounded-xl border border-subtle bg-surface-1 px-3 py-2"
                                    >
                                      <div className="min-w-0">
                                        <div className="truncate text-xs font-medium text-text-hi">{task.name}</div>
                                        {task.capability_id ? (
                                          <div className="truncate font-mono text-[11px] text-text-lo">{task.capability_id}</div>
                                        ) : null}
                                        {task.error ? (
                                          <div className="mt-1 text-[11px] text-text-rose-token">{task.error}</div>
                                        ) : null}
                                      </div>
                                      <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] ${jobStatusColor(task.status)}`}>
                                        {task.status}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ) : null}

                            {/* Deep link to Run from Prompt for full debugger */}
                            <a
                              href={`/compose?job=${encodeURIComponent(job.id)}`}
                              className="inline-flex items-center gap-1.5 rounded-xl border border-sky-300/26 bg-accent-sky px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-hi transition hover:border-sky-300/40"
                            >
                              Open full debugger in Run from Prompt →
                            </a>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* ── Recent Events ── */}
        <section className={`rounded-[24px] p-4 ${isStudio ? "border border-subtle bg-gradient-panel text-text-hi shadow-[0_12px_32px_rgba(15,23,42,0.14),inset_0_1px_0_rgba(255,255,255,0.05)]" : "border border-slate-100 bg-white shadow-sm text-slate-900"}`}>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-text-hi">Recent Events</h2>
              <p className="mt-1 text-xs text-text-md">Live event stream — last 50 events, newest first.</p>
            </div>
            <span className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-xs text-text-md">
              {events.length} shown
            </span>
          </div>

          {events.length === 0 ? (
            <div className="mt-4 rounded-xl border border-dashed border-subtle py-8 text-center text-sm text-text-lo">
              Waiting for events…
            </div>
          ) : (
            <ul className="mt-4 space-y-2">
              {events.map((event, index) => (
                <li
                  key={index}
                  className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-xs font-semibold text-text-hi">{event.type}</span>
                      {event.occurred_at ? (
                        <span className="text-[11px] text-text-lo">
                          {new Date(event.occurred_at).toLocaleTimeString()}
                        </span>
                      ) : null}
                      {event.job_id ? (
                        <span className="truncate font-mono text-[11px] text-text-lo">{event.job_id}</span>
                      ) : null}
                    </div>
                    <button
                      className="shrink-0 rounded-full border border-subtle bg-surface-2 px-2 py-0.5 text-[11px] text-text-md transition hover:bg-surface-1"
                      onClick={() => toggleEvent(index)}
                    >
                      {expandedEvents.has(index) ? "Hide" : "Show"}
                    </button>
                  </div>
                  {expandedEvents.has(index) ? (
                    <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-text-md">
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
    </div>
  );
}
