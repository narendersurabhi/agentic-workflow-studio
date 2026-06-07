"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import StudioWorkbenchIcon from "../features/studio/StudioWorkbenchIcon";
import { PRIMARY_APP_NAV_ITEMS } from "../lib/app-navigation";
import { SHELL_THEMES, useAppTheme, type ShellTheme } from "../lib/theme";
import { useShellMeta, useShellActionsSlotRef } from "../lib/shell";
import { useAuth } from "../lib/auth";

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

function ThemePicker() {
  const { shellTheme, setShellTheme } = useAppTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const active = SHELL_THEMES.find((t) => t.id === shellTheme) ?? SHELL_THEMES[0];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="inline-flex items-center gap-2 rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-default-theme hover:bg-surface-2"
        aria-label="Change theme"
        title="Change theme"
      >
        <span
          className="h-3.5 w-3.5 rounded-full border border-white/20 shrink-0"
          style={{ background: active.swatch }}
        />
        {active.label}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-52 overflow-hidden rounded-2xl border border-white/20 bg-slate-900 p-2 shadow-[0_16px_40px_rgba(0,0,0,0.55)]">
          <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            Theme
          </p>
          <div className="grid grid-cols-3 gap-2">
            {SHELL_THEMES.map((t) => {
              const isActive = t.id === shellTheme;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    setShellTheme(t.id as ShellTheme);
                    setOpen(false);
                  }}
                  className={`group flex flex-col items-center gap-1.5 rounded-xl p-2 transition ${
                    isActive ? "bg-white/10" : "hover:bg-white/5"
                  }`}
                  title={t.label}
                >
                  <span
                    className={`h-8 w-8 rounded-full border-2 shadow-sm transition ${
                      isActive ? "border-sky-400 scale-110" : "border-white/20 group-hover:border-white/40"
                    }`}
                    style={{ background: t.swatch }}
                  />
                  <span className="text-[10px] font-medium text-slate-300">{t.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const { mounted, theme, shellTheme, toggleTheme } = useAppTheme();
  const isLightTheme = mounted ? theme === "light" : false;
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const shellMeta = useShellMeta();
  const actionsSlotRef = useShellActionsSlotRef();

  // Derive active nav item and title from pathname
  const activeNavItem = PRIMARY_APP_NAV_ITEMS.find((item) => item.href === pathname)
    ?? PRIMARY_APP_NAV_ITEMS.find((item) => item.href !== "/" && pathname.startsWith(item.href));
  const activeScreenId = activeNavItem?.id ?? "home";
  const title = shellMeta.title || activeNavItem?.title || "Workspace";
  const breadcrumbs = shellMeta.breadcrumbs;

  const userInitials = user
    ? user.display_name
        .split(" ")
        .map((p) => p[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "";

  const shellClass = mounted ? `shell-theme-${shellTheme}` : "shell-theme-ocean";

  return (
    <div
      className={`app-shell min-h-screen text-text-hi ${shellClass}`}
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
              {breadcrumbs.length > 0 && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-md">
                  {breadcrumbs.map((crumb, i) => (
                    <span key={`${crumb.label}-${i}`} className="contents">
                      {crumb.href ? (
                        <Link href={crumb.href} className="transition hover:text-text-hi">
                          {crumb.label}
                        </Link>
                      ) : (
                        <span className="text-text-hi">{crumb.label}</span>
                      )}
                      {i < breadcrumbs.length - 1 && (
                        <span className="text-text-lo">›</span>
                      )}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {/* Per-page action buttons are portalled here by ShellActions */}
              <div ref={actionsSlotRef} className="flex flex-wrap items-center gap-2" />

              <button
                type="button"
                onClick={toggleTheme}
                className="inline-flex items-center gap-2 rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-hi transition hover:border-default-theme hover:bg-surface-2"
                aria-label={isLightTheme ? "Switch to dark mode" : "Switch to light mode"}
              >
                <ThemeModeIcon theme={isLightTheme ? "light" : "dark"} className="h-4 w-4" />
                {isLightTheme ? "Dark" : "Light"}
              </button>
              <ThemePicker />

              {user && (
                <div className="flex items-center gap-2">
                  <div
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-600/80 text-[11px] font-bold text-white"
                    title={user.display_name}
                  >
                    {userInitials}
                  </div>
                  <button
                    type="button"
                    onClick={() => logout()}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-lo transition hover:border-default-theme hover:bg-surface-2 hover:text-text-hi"
                  >
                    Sign out
                  </button>
                </div>
              )}
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
                      item.id === activeScreenId
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

          <main className="min-w-0 overflow-auto">{children}</main>
        </div>
      </div>
    </div>
  );
}
