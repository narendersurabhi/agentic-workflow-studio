"use client";

type ComposerValidationIssue = {
  severity: "error" | "warning";
  source: "local" | "compile" | "preflight";
  code: string;
  message: string;
  field?: string;
  nodeId?: string;
};

type ComposerIssueFocus = {
  nodeId: string;
  field?: string;
};

type ChainPreflightResult = {
  valid: boolean;
  localErrors: string[];
  serverErrors: Record<string, string>;
  checkedAt: string;
};

type ComposerValidationPanelProps = {
  preflightResult: ChainPreflightResult | null;
  compileLoading: boolean;
  issues: ComposerValidationIssue[];
  needsValidation: boolean;
  onIssueClick: (issue: ComposerValidationIssue) => void;
  activeIssue: ComposerIssueFocus | null;
  formatTimestamp: (value?: string) => string;
};

export default function ComposerValidationPanel({
  preflightResult,
  compileLoading,
  issues,
  needsValidation,
  onIssueClick,
  activeIssue,
  formatTimestamp,
}: ComposerValidationPanelProps) {
  const errorCount = issues.filter((issue) => issue.severity === "error").length;
  const warningCount = issues.filter((issue) => issue.severity === "warning").length;
  const isValid = Boolean(preflightResult?.valid) && errorCount === 0;
  const statusText = needsValidation
    ? preflightResult
      ? isValid
        ? "Compile + Preflight OK"
        : "Compile/Preflight Issues Found"
      : "Validation required"
    : "No chain validation required";
  const statusClass = !needsValidation
    ? "text-text-md font-semibold"
    : isValid
      ? "text-emerald-300 font-semibold"
      : "text-rose-300 font-semibold";

  return (
    <div className="mt-3 rounded-[24px] border border-subtle bg-surface-1 px-3 py-3 text-[11px] text-text-md shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
      <div className="flex items-center justify-between gap-2">
        <div className={statusClass}>{statusText}</div>
        <div className="text-text-lo">{formatTimestamp(preflightResult?.checkedAt)}</div>
      </div>
      {compileLoading ? <div className="mt-2 text-text-lo">Compiling draft...</div> : null}
      {issues.length > 0 ? (
        <div className="mt-2 space-y-1">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.15em] text-text-lo">
            <span>Issues</span>
            <span className="rounded-full border border-rose-300/25 bg-accent-rose px-1.5 py-0.5 text-[10px] text-rose-200">
              errors: {errorCount}
            </span>
            <span className="rounded-full border border-amber-300/25 bg-accent-amber px-1.5 py-0.5 text-[10px] text-amber-200">
              warnings: {warningCount}
            </span>
          </div>
          {issues.map((issue, idx) => {
            const isActive =
              activeIssue &&
              issue.nodeId === activeIssue.nodeId &&
              (!activeIssue.field || !issue.field || issue.field === activeIssue.field);
            const issueClass =
              issue.severity === "warning"
                ? "text-text-amber-token border-amber-300/25 bg-accent-amber hover:bg-accent-amber"
                : "text-text-rose-token border-rose-300/25 bg-accent-rose hover:bg-accent-rose";
            return (
              <button
                key={`composer-issue-${idx}`}
                type="button"
                className={`w-full rounded-md border px-2 py-1 text-left transition ${
                  isActive ? "ring-2 ring-sky-300/30" : ""
                } ${issueClass}`}
                onClick={() => onIssueClick(issue)}
                title={issue.nodeId ? "Focus node in DAG canvas" : "Issue detail"}
              >
                • [{issue.source}] {issue.code}
                {issue.nodeId ? ` (${issue.nodeId})` : ""}
                {issue.field ? ` ${issue.field}:` : ":"} {issue.message}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="mt-2 text-text-lo">
          {needsValidation ? "No issues detected." : "Add one or more chain steps to enable validation."}
        </div>
      )}
    </div>
  );
}
