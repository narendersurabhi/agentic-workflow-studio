"use client";

import {
  formatFeedbackRate,
  type FeedbackBreakdownBucket,
  type FeedbackReasonBucket,
  type FeedbackSummaryResponse
} from "../../lib/feedback";

type FeedbackInsightsPanelProps = {
  summary: FeedbackSummaryResponse | null;
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
  theme?: "default" | "studio";
};

const renderBucketList = (
  buckets: FeedbackBreakdownBucket[],
  emptyLabel: string,
  formatter?: (bucket: FeedbackBreakdownBucket) => string,
  isStudioTheme = false
) => {
  if (!buckets.length) {
    return (
      <div className={`text-xs ${isStudioTheme ? "text-slate-300/72" : "text-slate-500"}`}>
        {emptyLabel}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {buckets.map((bucket) => (
        <div
          key={`feedback-bucket-${bucket.key}`}
          className={`flex items-center justify-between gap-3 text-sm ${
            isStudioTheme ? "text-slate-100" : "text-slate-700"
          }`}
        >
          <span className="truncate">{bucket.key}</span>
          <span
            className={`shrink-0 text-xs ${isStudioTheme ? "text-slate-300/78" : "text-slate-500"}`}
          >
            {formatter ? formatter(bucket) : `${bucket.total}`}
          </span>
        </div>
      ))}
    </div>
  );
};

const renderReasonList = (reasons: FeedbackReasonBucket[], isStudioTheme = false) => {
  if (!reasons.length) {
    return (
      <div className={`text-xs ${isStudioTheme ? "text-slate-300/72" : "text-slate-500"}`}>
        No negative or partial reasons yet.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {reasons.map((reason) => (
        <div
          key={`feedback-reason-${reason.reason_code}`}
          className={`flex items-center justify-between gap-3 text-sm ${
            isStudioTheme ? "text-slate-100" : "text-slate-700"
          }`}
        >
          <span className="truncate">{reason.reason_code}</span>
          <span
            className={`shrink-0 text-xs ${isStudioTheme ? "text-slate-300/78" : "text-slate-500"}`}
          >
            {reason.count}
          </span>
        </div>
      ))}
    </div>
  );
};

export default function FeedbackInsightsPanel({
  summary,
  loading = false,
  error = null,
  onRefresh,
  theme = "default",
}: FeedbackInsightsPanelProps) {
  const isStudioTheme = theme === "studio";
  const total = summary?.total ?? 0;
  const terminalStatuses = summary?.correlates?.terminal_statuses ?? [];
  const metricCardClassName = isStudioTheme
    ? "rounded-xl border border-white/10 bg-slate-950/24 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
    : "rounded-xl border border-slate-100 bg-slate-50 p-4";
  const sectionCardClassName = isStudioTheme
    ? "rounded-xl border border-white/10 bg-slate-950/18 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
    : "rounded-xl border border-slate-100 p-4";
  const eyebrowClassName = isStudioTheme
    ? "text-[11px] uppercase tracking-[0.2em] text-slate-300/78"
    : "text-[11px] uppercase tracking-[0.2em] text-slate-400";
  const metricValueClassName = isStudioTheme
    ? "mt-2 text-2xl font-semibold text-white"
    : "mt-2 text-2xl font-semibold text-slate-900";
  const mutedClassName = isStudioTheme ? "text-slate-300/72" : "text-slate-500";
  const headingClassName = isStudioTheme
    ? "text-sm font-semibold text-white"
    : "text-sm font-semibold text-slate-800";
  const rowTextClassName = isStudioTheme ? "text-sm text-slate-100" : "text-sm text-slate-700";
  const rowValueClassName = isStudioTheme ? "text-xs text-slate-300/78" : "text-xs text-slate-500";

  return (
    <section
      className={`animate-fade-up rounded-2xl p-6 ${
        isStudioTheme
          ? "border border-white/10 bg-[linear-gradient(180deg,rgba(63,78,95,0.62),rgba(37,49,62,0.82))] text-white shadow-[0_24px_60px_rgba(15,23,42,0.18),inset_0_1px_0_rgba(255,255,255,0.05)]"
          : "border border-slate-100 bg-white shadow-sm"
      }`}
    >
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className={`font-display text-xl ${isStudioTheme ? "text-white" : "text-slate-900"}`}>
            Feedback Insights
          </h2>
          <p className={`mt-1 text-xs ${isStudioTheme ? "text-slate-300/74" : "text-slate-500"}`}>
            Read-only quality signals from explicit user feedback and linked runtime context.
          </p>
        </div>
        {onRefresh ? (
          <button
            type="button"
            className={`rounded-full px-3 py-1 text-xs transition ${
              isStudioTheme
                ? "border border-white/10 bg-white/[0.05] text-slate-100 hover:border-white/16 hover:bg-white/[0.08]"
                : "border border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-900"
            }`}
            onClick={onRefresh}
          >
            Refresh
          </button>
        ) : null}
      </div>

      {loading && !summary ? (
        <div
          className={`mt-4 rounded-xl p-6 text-sm ${
            isStudioTheme
              ? "border border-dashed border-white/12 bg-slate-950/18 text-slate-300/74"
              : "border border-dashed border-slate-200 bg-slate-50 text-slate-500"
          }`}
        >
          Loading feedback analytics...
        </div>
      ) : null}

      {error ? (
        <div
          className={`mt-4 rounded-xl px-4 py-3 text-sm ${
            isStudioTheme
              ? "border border-amber-300/20 bg-amber-300/10 text-amber-100"
              : "border border-amber-200 bg-amber-50 text-amber-800"
          }`}
        >
          {error}
        </div>
      ) : null}

      {summary ? (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <div className={metricCardClassName}>
              <div className={eyebrowClassName}>Volume</div>
              <div className={metricValueClassName}>{total}</div>
              <div className={`mt-1 text-xs ${mutedClassName}`}>Explicit feedback rows</div>
            </div>
            <div className={metricCardClassName}>
              <div className={eyebrowClassName}>Chat</div>
              <div className={metricValueClassName}>
                {formatFeedbackRate(summary.metrics?.chat_helpfulness_rate)}
              </div>
              <div className={`mt-1 text-xs ${mutedClassName}`}>Helpful response rate</div>
            </div>
            <div className={metricCardClassName}>
              <div className={eyebrowClassName}>Intent</div>
              <div className={metricValueClassName}>
                {formatFeedbackRate(summary.metrics?.intent_agreement_rate)}
              </div>
              <div className={`mt-1 text-xs ${mutedClassName}`}>Agreement rate</div>
            </div>
            <div className={metricCardClassName}>
              <div className={eyebrowClassName}>Plans</div>
              <div className={metricValueClassName}>
                {formatFeedbackRate(summary.metrics?.plan_approval_rate)}
              </div>
              <div className={`mt-1 text-xs ${mutedClassName}`}>Approval rate</div>
            </div>
            <div className={metricCardClassName}>
              <div className={eyebrowClassName}>Outcome</div>
              <div className={metricValueClassName}>
                {formatFeedbackRate(summary.metrics?.job_outcome_positive_rate)}
              </div>
              <div className={`mt-1 text-xs ${mutedClassName}`}>Positive outcome rate</div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-4">
            <div className={sectionCardClassName}>
              <div className={headingClassName}>Top Negative Reasons</div>
              <div className="mt-3">
                {renderReasonList(summary.negative_reasons.slice(0, 5), isStudioTheme)}
              </div>
            </div>
            <div className={sectionCardClassName}>
              <div className={headingClassName}>Top Models</div>
              <div className="mt-3">
                {renderBucketList(
                  summary.llm_models.slice(0, 5),
                  "No model-tagged feedback yet.",
                  undefined,
                  isStudioTheme
                )}
              </div>
            </div>
            <div className={sectionCardClassName}>
              <div className={headingClassName}>Planner Versions</div>
              <div className="mt-3">
                {renderBucketList(
                  summary.planner_versions.slice(0, 5),
                  "No planner-tagged feedback yet.",
                  undefined,
                  isStudioTheme
                )}
              </div>
            </div>
            <div className={sectionCardClassName}>
              <div className={headingClassName}>Workflow Sources</div>
              <div className="mt-3">
                {renderBucketList(
                  summary.workflow_sources.slice(0, 5),
                  "No workflow source dimensions yet.",
                  undefined,
                  isStudioTheme
                )}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className={sectionCardClassName}>
              <div className={headingClassName}>Outcome Distribution</div>
              <div className="mt-3">
                {renderBucketList(
                  terminalStatuses.slice(0, 5),
                  "No job-linked feedback yet.",
                  (bucket) => `${bucket.total} jobs`,
                  isStudioTheme
                )}
              </div>
            </div>
            <div className={sectionCardClassName}>
              <div className={headingClassName}>Operational Correlates</div>
              <div className={`mt-3 grid gap-2 ${rowTextClassName}`}>
                <div className="flex items-center justify-between gap-3">
                  <span>Jobs with feedback</span>
                  <span className={rowValueClassName}>{summary.correlates.job_count}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>Replans</span>
                  <span className={rowValueClassName}>{summary.correlates.replan_count}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>Retries</span>
                  <span className={rowValueClassName}>{summary.correlates.retry_count}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>Failed tasks</span>
                  <span className={rowValueClassName}>
                    {summary.correlates.failed_task_count}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>Plan failures</span>
                  <span className={rowValueClassName}>
                    {summary.correlates.plan_failure_count}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>Clarification turns</span>
                  <span className={rowValueClassName}>
                    {summary.correlates.clarification_turn_count}
                  </span>
                </div>
              </div>
            </div>
            <div className={sectionCardClassName}>
              <div className={headingClassName}>By Target Type</div>
              <div className="mt-3">
                {renderBucketList(
                  summary.target_type_counts.slice(0, 6),
                  "No target breakdown yet.",
                  (bucket) => `${bucket.total} rows`,
                  isStudioTheme
                )}
              </div>
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}
