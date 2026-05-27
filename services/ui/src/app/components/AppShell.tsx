"use client";

import type { ReactNode } from "react";
import Link from "next/link";

import StudioWorkbenchIcon from "../features/studio/StudioWorkbenchIcon";
import { PRIMARY_APP_NAV_ITEMS, type AppScreenId } from "../lib/app-navigation";
import { useAppTheme } from "../lib/theme";

export type AppBreadcrumb = {
  label: string;
  href?: string;
};

export type AppShellProps = {
  activeScreen: AppScreenId;
  title: string;
  breadcrumbs?: AppBreadcrumb[];
  actions?: ReactNode;
  children: ReactNode;
  contentClassName?: string;
};

function ThemeModeIcon({
  theme,
  className = "",
}: {
  theme: "dark" | "light";
  className?: string;
}) {
  if (theme === "light") {
    return (
      <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="none">
        <path
          d="M12 4.5V2.5M12 21.5v-2M6.7 6.7 5.3 5.3M18.7 18.7l-1.4-1.4M4.5 12h-2M21.5 12h-2M6.7 17.3l-1.4 1.4M18.7 5.3l-1.4 1.4"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.7"
        />
        <circle
          cx="12"
          cy="12"
          r="4.25"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="1.7"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="none">
      <path
        d="M14.5 3.5a7.7 7.7 0 1 0 6 12.4 8.8 8.8 0 0 1-6.8-12.4c.2-.4 0-.7-.4-.7-.3 0-.5.1-.8.7Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.7"
      />
    </svg>
  );
}

export default function AppShell({
  activeScreen,
  title,
  breadcrumbs = [],
  actions,
  children,
  contentClassName = "px-4 py-4",
}: AppShellProps) {
  const { mounted, theme, toggleTheme } = useAppTheme();
  const isLightTheme = mounted ? theme === "light" : false;

  return (
    <div
      className={`app-shell -mx-6 -my-8 min-h-screen text-text-hi ${
        isLightTheme ? "app-shell-light" : "app-shell-dark"
      }`}
      data-app-theme={mounted ? theme : "dark"}
    >
      <div className="min-h-screen bg-gradient-shell">
        <header
          className="border-b bg-gradient-header px-6 py-3"
          style={{
            borderColor: "var(--border-header)",
            boxShadow: "var(--shadow-header)",
          }}
        >
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="truncate text-[22px] font-semibold tracking-[-0.03em] text-text-hi">
                {title}
              </div>
              {breadcrumbs.length > 0 ? (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-md">
                  {breadcrumbs.map((breadcrumb, index) => (
                    <span key={`${breadcrumb.label}-${index}`} className="contents">
                      {breadcrumb.href ? (
                        <Link
                          href={breadcrumb.href}
                          className="transition hover:text-text-hi"
                        >
                          {breadcrumb.label}
                        </Link>
                      ) : (
                        <span className="text-text-hi">{breadcrumb.label}</span>
                      )}
                      {index < breadcrumbs.length - 1 ? (
                        <span className="text-text-lo">›</span>
                      ) : null}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={toggleTheme}
                className="inline-flex items-center gap-2 rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-default-theme hover:bg-surface-2"
                aria-label={isLightTheme ? "Switch to dark mode" : "Switch to light mode"}
              >
                <ThemeModeIcon theme={isLightTheme ? "light" : "dark"} className="h-4 w-4" />
                {isLightTheme ? "Dark Mode" : "Light Mode"}
              </button>
              {actions}
            </div>
          </div>
        </header>

        <div className="grid min-h-[calc(100vh-78px)] grid-cols-[52px_minmax(0,1fr)]">
          <aside
            className="border-r bg-gradient-sidebar px-1.5 py-3"
            style={{ borderColor: "var(--border-header)" }}
          >
            <div className="flex h-full flex-col items-center">
              <div className="space-y-3">
                {PRIMARY_APP_NAV_ITEMS.map((item) => (
                  <Link
                    key={item.id}
                    href={item.href}
                    title={item.label}
                    aria-label={item.label}
                    className="flex h-11 w-11 items-center justify-center rounded-xl border transition"
                    style={
                      item.id === activeScreen
                        ? {
                            background: "var(--nav-active-bg)",
                            borderColor: "var(--nav-active-border)",
                            color: "var(--nav-active-text)",
                            boxShadow: "0 8px 18px rgba(14,165,233,0.16)",
                          }
                        : {
                            background: "var(--nav-inactive-bg)",
                            borderColor: "var(--nav-inactive-border)",
                            color: "var(--nav-inactive-text)",
                          }
                    }
                  >
                    <StudioWorkbenchIcon kind={item.icon} className="h-5 w-5" />
                  </Link>
                ))}
              </div>
            </div>
          </aside>

          <main className={`min-w-0 overflow-auto ${contentClassName}`}>{children}</main>
        </div>
      </div>
    </div>
  );
}
