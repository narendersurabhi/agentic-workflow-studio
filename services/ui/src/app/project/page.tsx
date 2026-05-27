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
  },
  {
    href: "/studio",
    eyebrow: "Workflow Studio",
    title: "Workflow Studio",
    description:
      "Design reusable workflow steps, decisions, tools, and AI actions.",
    cta: "Open Studio",
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
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-text-sky-token">
              Project
            </div>
            <h2 className="mt-1 text-[30px] font-semibold tracking-[-0.03em] text-text-hi">
              Workflow Management
            </h2>
            <p className="mt-1 max-w-3xl text-[13px] leading-5 text-text-md">
              Move between saved automations and Workflow Studio for designing business workflows.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em]">
            <span className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-text-hi">
              compose
            </span>
            <span className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-text-hi">
              chat
            </span>
            <span className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-text-hi">
              workflows
            </span>
            <span className="rounded-full border border-subtle bg-surface-1 px-3 py-1 text-text-hi">
              studio
            </span>
          </div>
        </div>

        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          {projectCards.map((card) => (
            <Link
              key={card.href}
              href={card.href}
              className="group rounded-[30px] border border-subtle bg-gradient-panel p-5 shadow-[0_24px_60px_rgba(15,23,42,0.18),inset_0_1px_0_rgba(255,255,255,0.05)] transition hover:border-sky-300/28 hover:bg-gradient-panel"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-text-sky-token">
                    {card.eyebrow}
                  </div>
                  <h3 className="mt-2 text-[26px] font-semibold tracking-[-0.03em] text-text-hi">
                    {card.title}
                  </h3>
                </div>
              </div>
              <p className="mt-3 max-w-xl text-sm leading-6 text-text-md">
                {card.description}
              </p>
              <div className="mt-5 inline-flex items-center rounded-full border border-subtle bg-surface-1 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition group-hover:border-sky-300/30 group-hover:bg-surface-1">
                {card.cta}
              </div>
            </Link>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
