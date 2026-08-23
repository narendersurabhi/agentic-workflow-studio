import type { ToolStepItem } from "./types";

function artifactDownloadUrl(rawPath: string): string {
  // Strip leading /shared/artifacts/ prefix — API endpoint is relative to that root
  const relative = rawPath.replace(/^\/shared\/artifacts\/?/, "");
  return `/artifacts/download?path=${encodeURIComponent(relative)}`;
}

export function ToolProgressCard({
  intent,
  steps,
}: {
  intent?: string;
  steps: ToolStepItem[];
}) {
  if (!intent && steps.length === 0) return null;
  const anyRunning = steps.some((s) => s.status === "running");
  const downloads = steps.filter(
    (s) => s.status === "done" && typeof s.result?.path === "string"
  );
  return (
    <div className="mb-2 rounded-xl border border-sky-300/20 bg-accent-sky px-3 py-2.5 text-[12px] text-text-sky-token">
      {intent && steps.length === 0 && (
        <div className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-sky-400 border-t-transparent" />
          <span>{intent}</span>
        </div>
      )}
      {steps.map((step) => (
        <div key={step.capability} className="flex items-center gap-2 py-0.5">
          {step.status === "running" ? (
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-sky-400 border-t-transparent" />
          ) : (
            <span className="text-emerald-400">&#x2713;</span>
          )}
          <span className={step.status === "done" ? "text-text-md" : ""}>{step.label}</span>
        </div>
      ))}
      {anyRunning && (
        <div className="mt-1 text-[11px] text-text-lo">Working&hellip;</div>
      )}
      {downloads.length > 0 && (
        <div className="mt-2 flex flex-col gap-1 border-t border-sky-300/20 pt-2">
          {downloads.map((step) => {
            const filePath = step.result!.path as string;
            const filename = filePath.split("/").pop() ?? "download";
            return (
              <a
                key={step.capability}
                href={artifactDownloadUrl(filePath)}
                download={filename}
                className="flex items-center gap-2 rounded-lg border border-sky-300/30 bg-sky-900/20 px-2.5 py-1.5 text-sky-300 transition-colors hover:bg-sky-900/40 hover:text-sky-100"
              >
                <span>&#x1F4C4;</span>
                <span className="flex-1 truncate font-medium">{filename}</span>
                <span className="shrink-0 text-[10px] uppercase tracking-wide opacity-70">Download</span>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default ToolProgressCard;
