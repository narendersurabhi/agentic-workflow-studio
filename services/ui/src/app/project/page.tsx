import Link from "next/link";

import StudioWorkbenchIcon from "../features/studio/StudioWorkbenchIcon";

const projectCards = [
  {
    href: "/workflows",
    eyebrow: "Workflow Library",
    title: "Review Saved Drafts",
    description:
      "Browse saved workflow definitions, inspect version history, create manual triggers, and jump back into Studio with a selected draft.",
    cta: "Open Workflows",
    icon: "library" as const,
  },
  {
    href: "/studio",
    eyebrow: "Workflow Studio",
    title: "Design the Workspace",
    description:
      "Build and edit workflows on the full graph workspace, then move the floating utility panels around the stage while you iterate.",
    cta: "Open Studio",
    icon: "graph" as const,
  },
];

export default function ProjectPage() {
  return (
    <div className="-mx-6 -my-8 min-h-screen bg-[#56697c] text-white">
      <div className="min-h-screen bg-[linear-gradient(180deg,#435365_0px,#435365_78px,#55697c_78px,#55697c_100%)]">
        <header className="border-b border-white/10 bg-[linear-gradient(180deg,rgba(67,83,101,0.98),rgba(60,74,90,0.98))] px-6 py-3 shadow-[inset_0_-1px_0_rgba(255,255,255,0.08)]">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="truncate text-[22px] font-semibold tracking-[-0.03em] text-white">
                Project Workspace
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-200/78">
                <span className="text-white/95">Project</span>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Link
                href="/workflows"
                className="rounded-xl border border-white/12 bg-white/[0.04] px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-100 transition hover:border-sky-300/35 hover:bg-white/[0.08]"
              >
                Workflows
              </Link>
              <Link
                href="/studio"
                className="rounded-xl border border-slate-200/18 bg-slate-950/25 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-white transition hover:border-white/30 hover:bg-slate-950/35"
              >
                Open Studio
              </Link>
            </div>
          </div>
        </header>

        <div className="grid min-h-[calc(100vh-78px)] grid-cols-[52px_minmax(0,1fr)]">
          <aside className="border-r border-white/10 bg-[linear-gradient(180deg,rgba(49,61,74,0.96),rgba(44,56,69,0.98))] px-1.5 py-3">
            <div className="flex h-full flex-col items-center justify-between">
              <div className="space-y-3">
                {[
                  { href: "/project", label: "Project", icon: "menu" as const, active: true },
                  { href: "/studio", label: "Studio", icon: "graph" as const },
                  { href: "/workflows", label: "Workflows", icon: "library" as const },
                ].map((item) => (
                  <Link
                    key={item.label}
                    href={item.href}
                    title={item.label}
                    aria-label={item.label}
                    className={`flex h-11 w-11 items-center justify-center rounded-xl border transition ${
                      item.active
                        ? "border-sky-300/35 bg-sky-400/18 text-sky-50 shadow-[0_8px_18px_rgba(14,165,233,0.16)]"
                        : "border-white/10 bg-slate-950/18 text-slate-200 hover:border-white/18 hover:bg-slate-950/26"
                    }`}
                  >
                    <StudioWorkbenchIcon kind={item.icon} className="h-5 w-5" />
                  </Link>
                ))}
              </div>

              <Link
                href="/studio"
                title="Open Studio"
                aria-label="Open Studio"
                className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-slate-950/18 text-slate-100 transition hover:border-white/18 hover:bg-slate-950/26"
              >
                <StudioWorkbenchIcon kind="run" className="h-5 w-5" />
              </Link>
            </div>
          </aside>

          <main className="min-w-0 overflow-auto px-4 py-4">
            <section className="relative">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-sky-100/72">
                    Project
                  </div>
                  <h2 className="mt-1 text-[30px] font-semibold tracking-[-0.03em] text-white">
                    Workflow Surfaces
                  </h2>
                  <p className="mt-1 max-w-3xl text-[13px] leading-5 text-slate-200/74">
                    Move between the dedicated workflow views without losing the Studio visual
                    language. The library and the editor now live as separate destinations.
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em]">
                  <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-slate-100">
                    studio
                  </span>
                  <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-slate-100">
                    workflows
                  </span>
                  <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-slate-100">
                    connected
                  </span>
                </div>
              </div>

              <div className="mt-5 grid gap-4 xl:grid-cols-2">
                {projectCards.map((card) => (
                  <Link
                    key={card.href}
                    href={card.href}
                    className="group rounded-[30px] border border-white/10 bg-[linear-gradient(180deg,rgba(63,78,95,0.62),rgba(37,49,62,0.82))] p-5 shadow-[0_24px_60px_rgba(15,23,42,0.18),inset_0_1px_0_rgba(255,255,255,0.05)] transition hover:border-sky-300/28 hover:bg-[linear-gradient(180deg,rgba(71,88,106,0.66),rgba(42,56,70,0.86))]"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-sky-100/72">
                          {card.eyebrow}
                        </div>
                        <h3 className="mt-2 text-[26px] font-semibold tracking-[-0.03em] text-white">
                          {card.title}
                        </h3>
                      </div>
                      <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-slate-950/18 text-slate-100">
                        <StudioWorkbenchIcon kind={card.icon} className="h-6 w-6" />
                      </div>
                    </div>
                    <p className="mt-3 max-w-xl text-sm leading-6 text-slate-300/82">
                      {card.description}
                    </p>
                    <div className="mt-5 inline-flex items-center rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-100 transition group-hover:border-sky-300/30 group-hover:bg-white/[0.08]">
                      {card.cta}
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          </main>
        </div>
      </div>
    </div>
  );
}
