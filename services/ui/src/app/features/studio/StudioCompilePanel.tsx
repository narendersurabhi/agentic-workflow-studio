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
  "h-full overflow-auto px-2.5 py-2.5 text-text-hi [&_.border-slate-200]:border-subtle [&_.border-amber-200]:border-amber-300/25 [&_.border-rose-200]:border-rose-300/25 [&_.bg-slate-50]:bg-surface-1 [&_.bg-white]:bg-surface-1 [&_.bg-amber-50]:bg-accent-amber [&_.bg-rose-50]:bg-accent-rose [&_.text-slate-900]:text-text-hi [&_.text-slate-800]:text-text-hi [&_.text-slate-700]:text-text-md [&_.text-slate-600]:text-text-md [&_.text-text-lo]:text-text-lo [&_.text-amber-800]:text-text-amber-token [&_.text-rose-800]:text-text-rose-token [&_details]:border [&_details]:border-subtle [&_details]:bg-surface-1 [&_summary]:text-text-hi";

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
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5 text-[10px] uppercase tracking-[0.14em]">
          <span className={`rounded-full border px-2 py-0.5 ${hasPlan ? "border-emerald-300/25 bg-accent-emerald text-emerald-200" : "border-subtle bg-surface-1 text-text-md"}`}>
            {hasPlan ? "plan ready" : "draft only"}
          </span>
          {errorCount > 0 && <span className="rounded-full border border-rose-300/25 bg-accent-rose px-2 py-0.5 text-rose-200">{errorCount} errors</span>}
          {warningCount > 0 && <span className="rounded-full border border-amber-300/25 bg-accent-amber px-2 py-0.5 text-amber-200">{warningCount} warnings</span>}
        </div>
        <button
          className="shrink-0 rounded-lg border border-sky-300/30 bg-accent-sky px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-hi transition hover:border-sky-200/50 disabled:cursor-not-allowed disabled:opacity-60"
          onClick={onCompile}
          disabled={compileLoading}
        >
          {compileLoading ? "Checking…" : "Check"}
        </button>
      </div>

      <div className="mt-1.5 text-[10px] text-text-lo">
        Last checked: {formatTimestamp(preflightResult?.checkedAt)}
      </div>

      <details className="mt-2 rounded-[12px] p-2.5" open={hasPlan}>
        <summary className="cursor-pointer text-xs font-semibold">
          {hasPlan ? "Compiled plan JSON" : "Compile request preview"}
        </summary>
        <pre className="mt-2 max-h-[280px] overflow-auto rounded-xl bg-slate-950 p-3 text-[10px] leading-4 text-text-hi">
          {JSON.stringify(hasPlan ? compileResult?.plan : draftPayloadPreview, null, 2)}
        </pre>
      </details>

      {issues.length > 0 ? (
        <details className="mt-2 rounded-[12px] p-2.5">
          <summary className="cursor-pointer text-xs font-semibold">
            Diagnostics ({issues.length})
          </summary>
          <div className="mt-2 space-y-1.5">
            {issues.map((issue, index) => (
              <div
                key={`studio-compile-issue-${index}`}
                className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                  issue.severity === "warning"
                    ? "border-amber-200 bg-amber-50 text-amber-800"
                    : "border-rose-200 bg-rose-50 text-rose-800"
                }`}
              >
                <div className="font-semibold">[{issue.source}] {issue.code}</div>
                <div className="mt-0.5">{issue.message}</div>
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}
