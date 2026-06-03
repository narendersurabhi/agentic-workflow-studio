"use client";

import { useCallback, useEffect, useState } from "react";
import AppShell from "../../components/AppShell";
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

export default function ObservabilityScreen() {
  const { theme } = useAppTheme();
  const isStudio = theme === "dark";

  const [feedbackSummary, setFeedbackSummary] = useState<FeedbackSummaryResponse | null>(null);
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set());

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
    const source = new EventSource(`${apiUrl}/events/stream`);
    source.onmessage = (e) => {
      try {
        const envelope = JSON.parse(e.data) as EventEnvelope;
        if (envelope.type === "task.heartbeat") return;
        setEvents((prev) => [envelope, ...prev].slice(0, 50));
      } catch {
        return;
      }
    };
    return () => source.close();
  }, []);

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

  return (
    <AppShell
      activeScreen="observability"
      title="Observability"
      breadcrumbs={[{ label: "Observability" }]}
    >
      <div className="mx-auto max-w-5xl space-y-6 px-6 py-8">
        <FeedbackInsightsPanel
          summary={feedbackSummary}
          loading={feedbackLoading}
          error={feedbackError}
          onRefresh={() => void loadFeedbackSummary()}
          theme={isStudio ? "studio" : "default"}
        />

        <section className={`rounded-2xl p-5 ${isStudio ? "border border-subtle bg-gradient-panel text-text-hi shadow-[0_24px_60px_rgba(15,23,42,0.18),inset_0_1px_0_rgba(255,255,255,0.05)]" : "border border-slate-100 bg-white shadow-sm text-slate-900"}`}>
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
    </AppShell>
  );
}
