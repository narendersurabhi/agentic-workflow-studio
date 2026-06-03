import Link from "next/link";

import AppShell from "../components/AppShell";

const projectCards = [
  {
    href: "/workflows",
    eyebrow: "Saved Workflows",
    title: "Saved Workflows",
    description:
      "Manage reusable workflows, versions, triggers, and published automations.",
    cta: "Open Workflows",
    marker: "W",
  },
  {
    href: "/studio",
    eyebrow: "Workflow Studio",
    title: "Workflow Studio",
    description:
      "Design reusable workflow steps, decisions, tools, and AI actions.",
    cta: "Open Studio",
    marker: "S",
  },
];

export default function ProjectPage() {
  return (
    <AppShell
      activeScreen="project"
      title="Project Workspace"
      breadcrumbs={[{ label: "Project" }]}
      actions={
        <>
          <Link
            href="/workflows"
            className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-sky-300/35 hover:bg-surface-1"
          >
            Saved Workflows
          </Link>
          <Link
            href="/studio"
            className="rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-default-theme hover:bg-slate-950/35"
          >
            Open Studio
          </Link>
        </>
      }
    >
      <section className="relative">
        <div className="mb-4">
          <div className="text-[10px] font-semibold uppercase tracking-[0.26em] text-text-sky-token">
            Project
          </div>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-text-hi">
            Workflow Management
          </h2>
          <p className="mt-0.5 text-xs text-text-md">
            Move between saved automations and Workflow Studio for designing business workflows.
          </p>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          {projectCards.map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="group rounded-[24px] border border-subtle bg-gradient-panel p-4 shadow-[0_12px_32px_rgba(15,23,42,0.14),inset_0_1px_0_rgba(255,255,255,0.05)] transition hover:border-sky-300/28"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-text-sky-token">
                    {card.eyebrow}
                  </div>
                  <h3 className="mt-1 text-base font-semibold tracking-tight text-text-hi">
                    {card.title}
                  </h3>
                </div>
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-subtle bg-surface-1 text-xs font-semibold uppercase tracking-[0.16em] text-text-hi">
                  {card.marker}
                </div>
              </div>
              <p className="mt-2 text-xs leading-5 text-text-md">
                {card.description}
              </p>
              <div className="mt-3 flex items-center justify-end">
                <span className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-hi transition group-hover:border-sky-300/30">
                  {card.cta} →
                </span>
              </div>
            </Link>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
