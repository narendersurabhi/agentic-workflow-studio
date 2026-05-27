"use client";

import type {
  ChainPreflightResult,
  ComposerCompileResponse,
  ComposerValidationIssue,
} from "./types";
import { formatTimestamp } from "./utils";

type StudioCompilePanelProps = {
  compileLoading: boolean;
  compileResult: ComposerCompileResponse | null;
  preflightResult: ChainPreflightResult | null;
  issues: ComposerValidationIssue[];
  draftPayloadPreview: Record<string, unknown>;
  onCompile: () => void;
};

const compilePanelClassName =
  "h-full px-3 py-3 text-text-hi [&_.border-slate-200]:border-subtle [&_.border-amber-200]:border-amber-300/25 [&_.border-rose-200]:border-rose-300/25 [&_.bg-slate-50]:bg-surface-1 [&_.bg-white]:bg-surface-1 [&_.bg-amber-50]:bg-accent-amber [&_.bg-rose-50]:bg-accent-rose [&_.text-slate-900]:text-text-hi [&_.text-slate-800]:text-text-hi [&_.text-slate-700]:text-text-md [&_.text-slate-600]:text-text-md [&_.text-text-lo]:text-text-lo [&_.text-amber-800]:text-text-amber-token [&_.text-rose-800]:text-text-rose-token [&_details]:border [&_details]:border-subtle [&_details]:bg-surface-1 [&_summary]:text-text-hi";

export default function StudioCompilePanel({
  compileLoading,
  compileResult,
  preflightResult,
  issues,
  draftPayloadPreview,
  onCompile,
}: StudioCompilePanelProps) {
  const errorCount = issues.filter((issue) => issue.severity === "error").length;
  const warningCount = issues.filter((issue) => issue.severity === "warning").length;
  const hasPlan = Boolean(compileResult?.plan);

  return (
    <section className={compilePanelClassName}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-text-sky-token">
            Workflow Readiness Check
          </div>
          <h3 className="mt-1 text-[22px] font-semibold tracking-[-0.03em] text-text-hi">Plan Preview</h3>
        </div>
        <button
          className="rounded-full border border-sky-300/30 bg-accent-sky px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-hi transition hover:border-sky-200/50 hover:bg-accent-sky disabled:cursor-not-allowed disabled:opacity-60"
          onClick={onCompile}
          disabled={compileLoading}
        >
          {compileLoading ? "Checking..." : "Check Workflow"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.16em]">
        <span
          className={`rounded-full border px-3 py-1 ${
            hasPlan
              ? "border-emerald-300/25 bg-accent-emerald text-emerald-200"
              : "border-subtle bg-surface-1 text-text-md"
          }`}
        >
          {hasPlan ? "Executable plan" : "Draft only"}
        </span>
        <span className="rounded-full border border-rose-300/25 bg-accent-rose px-3 py-1 text-rose-200">
          errors {errorCount}
        </span>
        <span className="rounded-full border border-amber-300/25 bg-accent-amber px-3 py-1 text-amber-200">
          warnings {warningCount}
        </span>
      </div>

      <div className="mt-3 text-xs text-text-lo">
        Last checked: {formatTimestamp(preflightResult?.checkedAt)}
      </div>

      <details className="mt-3 rounded-[18px] p-3" open={hasPlan}>
        <summary className="cursor-pointer text-sm font-semibold">
          {hasPlan ? "Compiled plan JSON" : "Compile request preview"}
        </summary>
        <pre className="mt-3 max-h-[320px] overflow-auto rounded-2xl bg-slate-950 p-4 text-[11px] leading-5 text-text-hi">
          {JSON.stringify(hasPlan ? compileResult?.plan : draftPayloadPreview, null, 2)}
        </pre>
      </details>

      {issues.length > 0 ? (
        <details className="mt-3 rounded-[18px] p-3">
          <summary className="cursor-pointer text-sm font-semibold">
            Diagnostics
          </summary>
          <div className="mt-3 space-y-2">
            {issues.map((issue, index) => (
              <div
                key={`studio-compile-issue-${index}`}
                className={`rounded-xl border px-3 py-2 text-sm ${
                  issue.severity === "warning"
                    ? "border-amber-200 bg-amber-50 text-amber-800"
                    : "border-rose-200 bg-rose-50 text-rose-800"
                }`}
              >
                <div className="font-semibold">
                  [{issue.source}] {issue.code}
                </div>
                <div className="mt-1">{issue.message}</div>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}
