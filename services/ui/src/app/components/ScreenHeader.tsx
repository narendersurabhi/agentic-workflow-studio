"use client";

import type { ReactNode } from "react";

type ScreenHeaderProps = {
  eyebrow: string;
  title: string;
  description: string;
  activeScreen?: string;
  actions?: ReactNode;
  children?: ReactNode;
  compact?: boolean;
  theme?: "default" | "studio";
};

export const screenHeaderSecondaryActionClassName =
  "rounded-full border border-subtle bg-surface-1 px-4 py-2 text-sm font-semibold text-text-hi transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50";

export const screenHeaderPrimaryActionClassName =
  "rounded-full bg-white px-4 py-2 text-sm font-semibold text-slate-900 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50";

export default function ScreenHeader({
  eyebrow,
  title,
  description,
  activeScreen: _activeScreen,
  actions,
  children,
  compact = false,
  theme = "default",
}: ScreenHeaderProps) {
  const isStudioTheme = theme === "studio";
  return (
    <section
      className={`screen-header relative overflow-hidden animate-fade-up border border-subtle text-text-hi shadow-card ${
        isStudioTheme
          ? "screen-header-studio bg-gradient-header"
          : "screen-header-default bg-gradient-hero"
      } ${compact ? "rounded-[30px] px-6 py-5" : "rounded-[36px] px-8 py-8"}`}
    >
      <div
        className={`pointer-events-none absolute rounded-full blur-3xl opacity-30 ${
          isStudioTheme ? "bg-accent-sky" : "bg-accent-amber"
        } ${compact ? "-left-10 top-4 h-28 w-28" : "-left-14 top-8 h-44 w-44"}`}
      />
      <div
        className={`pointer-events-none absolute rounded-full blur-3xl opacity-25 bg-accent-sky ${
          compact ? "-right-10 bottom-0 h-36 w-36" : "-right-12 bottom-0 h-56 w-56"
        }`}
      />
      <div className={`relative ${compact ? "space-y-4" : "space-y-6"}`}>
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="max-w-3xl">
            <div className="text-[11px] font-semibold uppercase tracking-[0.28em] text-text-sky-token">
              {eyebrow}
            </div>
            <h1
              className={`mt-2 text-text-hi ${
                isStudioTheme
                  ? compact
                    ? "text-[30px] font-semibold tracking-[-0.03em] md:text-[34px]"
                    : "text-[34px] font-semibold tracking-[-0.03em] md:text-[42px]"
                  : compact
                    ? "font-display text-3xl tracking-tight md:text-4xl"
                    : "font-display text-4xl tracking-tight md:text-5xl"
              }`}
            >
              {title}
            </h1>
            <p
              className={`text-text-md ${
                compact ? "mt-2 text-sm leading-6" : "mt-3 text-sm leading-6 md:text-base"
              }`}
            >
              {description}
            </p>
          </div>
          <div className="flex max-w-full flex-col items-start gap-3 md:items-end">
            {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
          </div>
        </div>
        {children ? <div>{children}</div> : null}
      </div>
    </section>
  );
}
