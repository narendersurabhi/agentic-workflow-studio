"use client";

import type { ReactNode, RefObject } from "react";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import StudioWorkbenchIcon from "../features/studio/StudioWorkbenchIcon";
import { PRIMARY_APP_NAV_ITEMS } from "../lib/app-navigation";
import { SHELL_THEMES, useAppTheme, type ShellTheme } from "../lib/theme";
import { useShellMeta, useShellActionsSlotRef } from "../lib/shell";
import { apiFetch, useAuth } from "../lib/auth";
import { LLM_PROVIDERS } from "../lib/llmProviders";

// ── Avatar color palette ────────────────────────────────────────────────────
const AVATAR_COLORS = [
  { value: "sky",     hex: "#0ea5e9" },
  { value: "violet",  hex: "#8b5cf6" },
  { value: "emerald", hex: "#10b981" },
  { value: "rose",    hex: "#f43f5e" },
  { value: "amber",   hex: "#f59e0b" },
  { value: "slate",   hex: "#64748b" },
] as const;

function avatarHex(color: string): string {
  return AVATAR_COLORS.find((c) => c.value === color)?.hex ?? "#0ea5e9";
}

const LANGUAGES = ["English", "Spanish", "French", "German", "Portuguese", "Japanese", "Chinese", "Arabic", "Hindi"];

const TIMEZONES = [
  "UTC",
  "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
  "Europe/London", "Europe/Paris", "Europe/Berlin",
  "Asia/Tokyo", "Asia/Shanghai", "Asia/Kolkata",
  "Australia/Sydney",
];

type ProfileTab = "profile" | "ai" | "workspace";

// ── Shared field wrapper ────────────────────────────────────────────────────
function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.16em] text-text-md">
        {label}
        {hint ? <span className="ml-1.5 normal-case tracking-normal font-normal text-text-lo">{hint}</span> : null}
      </label>
      {children}
    </div>
  );
}

const inputCls = "w-full rounded-xl border border-subtle bg-surface-1 px-3 py-2 text-sm text-text-hi placeholder:text-text-lo focus:border-sky-400/50 focus:outline-none";
const selectCls = `${inputCls} cursor-pointer`;

// ── ThemeModeIcon ───────────────────────────────────────────────────────────
function ThemeModeIcon({ theme, className = "" }: { theme: "dark" | "light"; className?: string }) {
  if (theme === "light") {
    return (
      <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="none">
        <path d="M12 4.5V2.5M12 21.5v-2M6.7 6.7 5.3 5.3M18.7 18.7l-1.4-1.4M4.5 12h-2M21.5 12h-2M6.7 17.3l-1.4 1.4M18.7 5.3l-1.4 1.4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
        <circle cx="12" cy="12" r="4.25" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="none">
      <path d="M14.5 3.5a7.7 7.7 0 1 0 6 12.4 8.8 8.8 0 0 1-6.8-12.4c.2-.4 0-.7-.4-.7-.3 0-.5.1-.8.7Z" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
    </svg>
  );
}

// ── ThemePicker ─────────────────────────────────────────────────────────────
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
        <span className="h-3.5 w-3.5 rounded-full border border-white/20 shrink-0" style={{ background: active.swatch }} />
        {active.label}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-52 overflow-hidden rounded-2xl border border-white/20 bg-slate-900 p-2 shadow-[0_16px_40px_rgba(0,0,0,0.55)]">
          <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">Theme</p>
          <div className="grid grid-cols-3 gap-2">
            {SHELL_THEMES.map((t) => {
              const isActive = t.id === shellTheme;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => { setShellTheme(t.id as ShellTheme); setOpen(false); }}
                  className={`group flex flex-col items-center gap-1.5 rounded-xl p-2 transition ${isActive ? "bg-white/10" : "hover:bg-white/5"}`}
                  title={t.label}
                >
                  <span className={`h-8 w-8 rounded-full border-2 shadow-sm transition ${isActive ? "border-sky-400 scale-110" : "border-white/20 group-hover:border-white/40"}`} style={{ background: t.swatch }} />
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

// ── AppShell ────────────────────────────────────────────────────────────────
export default function AppShell({ children }: { children: ReactNode }) {
  const { mounted, theme, shellTheme, toggleTheme } = useAppTheme();
  const isLightTheme = mounted ? theme === "light" : false;
  const { user, logout, updateProfile } = useAuth();

  // Avatar color — loaded from preferences on login
  const [avatarColor, setAvatarColor] = useState("sky");

  useEffect(() => {
    if (!user) return;
    apiFetch("/api/auth/me/preferences")
      .then((res) => (res.ok ? (res.json() as Promise<Record<string, unknown>>) : null))
      .then((prefs) => {
        if (prefs?.avatar_color && typeof prefs.avatar_color === "string") {
          setAvatarColor(prefs.avatar_color);
        }
      })
      .catch(() => {});
  }, [user?.user_id]);

  // Dialog state
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileTab, setProfileTab] = useState<ProfileTab>("profile");
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  // Profile tab
  const [profileName, setProfileName] = useState("");
  const [profileEmail, setProfileEmail] = useState("");
  const [profileRole, setProfileRole] = useState("");
  const [profileAvatarColor, setProfileAvatarColor] = useState("sky");
  const [profileCurrentPw, setProfileCurrentPw] = useState("");
  const [profileNewPw, setProfileNewPw] = useState("");

  // AI tab
  const [prefProvider, setPrefProvider] = useState("");
  const [prefModel, setPrefModel] = useState("");
  const [prefSystemPrompt, setPrefSystemPrompt] = useState("");
  const [prefRagCollection, setPrefRagCollection] = useState("");
  const [prefLanguage, setPrefLanguage] = useState("English");

  // Workspace tab
  const [prefTimezone, setPrefTimezone] = useState("UTC");
  const [prefDefaultUserId, setPrefDefaultUserId] = useState("");
  const [prefNotifWorkflowDone, setPrefNotifWorkflowDone] = useState(true);
  const [prefNotifRunFailed, setPrefNotifRunFailed] = useState(true);
  const [prefNotifTriggerInvoked, setPrefNotifTriggerInvoked] = useState(false);

  const openProfile = async () => {
    setProfileName(user?.display_name ?? "");
    setProfileEmail("");
    setProfileRole("");
    setProfileAvatarColor(avatarColor);
    setProfileCurrentPw("");
    setProfileNewPw("");
    setProfileError(null);
    setProfileTab("profile");
    setProfileOpen(true);
    try {
      const res = await apiFetch("/api/auth/me/preferences");
      if (!res.ok) return;
      const prefs = await res.json() as Record<string, unknown>;
      setProfileEmail(typeof prefs.email === "string" ? prefs.email : "");
      setProfileRole(typeof prefs.role === "string" ? prefs.role : "");
      setProfileAvatarColor(typeof prefs.avatar_color === "string" ? prefs.avatar_color : "sky");
      setPrefProvider(typeof prefs.default_llm_provider === "string" ? prefs.default_llm_provider : "");
      setPrefModel(typeof prefs.default_llm_model === "string" ? prefs.default_llm_model : "");
      setPrefSystemPrompt(typeof prefs.default_system_prompt === "string" ? prefs.default_system_prompt : "");
      setPrefRagCollection(typeof prefs.default_rag_collection === "string" ? prefs.default_rag_collection : "");
      setPrefLanguage(typeof prefs.language === "string" ? prefs.language : "English");
      setPrefTimezone(typeof prefs.timezone === "string" ? prefs.timezone : "UTC");
      setPrefDefaultUserId(typeof prefs.default_workspace_user_id === "string" ? prefs.default_workspace_user_id : "");
      setPrefNotifWorkflowDone(prefs.notif_workflow_done !== false);
      setPrefNotifRunFailed(prefs.notif_run_failed !== false);
      setPrefNotifTriggerInvoked(prefs.notif_trigger_invoked === true);
    } catch {
      // dialog already open — use defaults
    }
  };

  const saveProfile = async () => {
    setProfileSaving(true);
    setProfileError(null);
    try {
      await updateProfile(profileName, profileCurrentPw || undefined, profileNewPw || undefined);
      const res = await apiFetch("/api/auth/me/preferences", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: profileEmail.trim(),
          role: profileRole.trim(),
          avatar_color: profileAvatarColor,
          default_llm_provider: prefProvider,
          default_llm_model: prefModel,
          default_system_prompt: prefSystemPrompt,
          default_rag_collection: prefRagCollection.trim(),
          language: prefLanguage,
          timezone: prefTimezone,
          default_workspace_user_id: prefDefaultUserId.trim(),
          notif_workflow_done: prefNotifWorkflowDone,
          notif_run_failed: prefNotifRunFailed,
          notif_trigger_invoked: prefNotifTriggerInvoked,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(err.detail ?? "Failed to save preferences.");
      }
      setAvatarColor(profileAvatarColor);
      setProfileOpen(false);
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Update failed.");
    } finally {
      setProfileSaving(false);
    }
  };

  const pathname = usePathname();
  const shellMeta = useShellMeta();
  const actionsSlotRef = useShellActionsSlotRef();

  const activeNavItem = PRIMARY_APP_NAV_ITEMS.find((item) => item.href === pathname)
    ?? PRIMARY_APP_NAV_ITEMS.find((item) => item.href !== "/" && pathname.startsWith(item.href));
  const activeScreenId = activeNavItem?.id ?? "home";
  const title = shellMeta.title || activeNavItem?.title || "Workspace";
  const breadcrumbs = shellMeta.breadcrumbs;

  const userInitials = user
    ? user.display_name.split(" ").map((p) => p[0]).join("").toUpperCase().slice(0, 2)
    : "";

  const providerModels = LLM_PROVIDERS.find((p) => p.value === prefProvider)?.models ?? [];
  const shellClass = mounted ? `shell-theme-${shellTheme}` : "shell-theme-ocean";

  return (
    <div className={`app-shell min-h-screen text-text-hi ${shellClass}`} data-app-theme={mounted ? theme : "dark"}>
      <div className="min-h-screen bg-gradient-shell">
        <header className="border-b bg-gradient-header px-6 py-3" style={{ borderColor: "var(--border-header)", boxShadow: "var(--shadow-header)" }}>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="truncate text-[22px] font-semibold tracking-[-0.03em] text-text-hi">{title}</div>
              {breadcrumbs.length > 0 && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-md">
                  {breadcrumbs.map((crumb, i) => (
                    <span key={`${crumb.label}-${i}`} className="contents">
                      {crumb.href ? (
                        <Link href={crumb.href} className="transition hover:text-text-hi">{crumb.label}</Link>
                      ) : (
                        <span className="text-text-hi">{crumb.label}</span>
                      )}
                      {i < breadcrumbs.length - 1 && <span className="text-text-lo">›</span>}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div
                ref={actionsSlotRef as RefObject<HTMLDivElement>}
                className="flex flex-wrap items-center gap-2"
              />
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
                  <button
                    type="button"
                    onClick={() => { void openProfile(); }}
                    className="flex h-8 w-8 items-center justify-center rounded-full text-[11px] font-bold text-white transition hover:opacity-90"
                    style={{ backgroundColor: avatarHex(avatarColor) }}
                    title={`${user.display_name} — click to edit profile`}
                  >
                    {userInitials}
                  </button>
                  <button
                    type="button"
                    onClick={() => { void logout(); }}
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
          <aside className="border-r bg-gradient-sidebar px-1.5 py-3" style={{ borderColor: "var(--border-header)" }}>
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
                        ? { background: "var(--nav-active-bg)", borderColor: "var(--nav-active-border)", color: "var(--nav-active-text)", boxShadow: "0 8px 18px rgba(14,165,233,0.16)" }
                        : { background: "var(--nav-inactive-bg)", borderColor: "var(--nav-inactive-border)", color: "var(--nav-inactive-text)" }
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

      {/* ── Profile / Settings dialog ─────────────────────────────────────── */}
      {profileOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) setProfileOpen(false); }}
        >
          <div
            className="flex w-full max-w-lg flex-col rounded-[28px] border border-subtle bg-gradient-panel shadow-card"
            style={{ maxHeight: "min(90vh, 700px)" }}
          >
            {/* Header */}
            <div className="shrink-0 px-6 pt-6 pb-4 border-b border-subtle">
              <div className="flex items-center gap-3">
                <div
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white"
                  style={{ backgroundColor: avatarHex(profileAvatarColor) }}
                >
                  {userInitials}
                </div>
                <div className="min-w-0">
                  <h2 className="font-display text-xl text-text-hi">Account Settings</h2>
                  <p className="text-sm text-text-md">@{user?.username}</p>
                </div>
              </div>

              {/* Tabs */}
              <div className="mt-4 flex gap-1 rounded-xl border border-subtle bg-surface-1 p-1">
                {(["profile", "ai", "workspace"] as const).map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setProfileTab(tab)}
                    className={`flex-1 rounded-lg py-1.5 text-xs font-semibold uppercase tracking-[0.12em] transition ${
                      profileTab === tab ? "bg-surface-2 text-text-hi shadow-sm" : "text-text-lo hover:text-text-md"
                    }`}
                  >
                    {tab === "profile" ? "Profile" : tab === "ai" ? "AI" : "Workspace"}
                  </button>
                ))}
              </div>
            </div>

            {/* Scrollable body */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">

              {/* ── Profile tab ───────────────────────────────────────────── */}
              {profileTab === "profile" && (
                <>
                  <Field label="Display name">
                    <input
                      type="text"
                      value={profileName}
                      onChange={(e) => setProfileName(e.target.value)}
                      className={inputCls}
                      placeholder="Your display name"
                    />
                  </Field>

                  <Field label="Email">
                    <input
                      type="email"
                      value={profileEmail}
                      onChange={(e) => setProfileEmail(e.target.value)}
                      className={inputCls}
                      placeholder="you@example.com"
                    />
                  </Field>

                  <Field label="Role / title">
                    <input
                      type="text"
                      value={profileRole}
                      onChange={(e) => setProfileRole(e.target.value)}
                      className={inputCls}
                      placeholder="e.g. AI Engineer, Product Owner"
                    />
                  </Field>

                  <Field label="Avatar color">
                    <div className="flex gap-2.5 pt-0.5">
                      {AVATAR_COLORS.map((c) => (
                        <button
                          key={c.value}
                          type="button"
                          onClick={() => setProfileAvatarColor(c.value)}
                          style={{ backgroundColor: c.hex }}
                          className={`h-6 w-6 rounded-full transition ${
                            profileAvatarColor === c.value
                              ? "ring-2 ring-white/80 ring-offset-2 ring-offset-surface-1 scale-110"
                              : "opacity-60 hover:opacity-90"
                          }`}
                        />
                      ))}
                    </div>
                  </Field>

                  <div className="border-t border-subtle pt-4">
                    <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-text-lo">Change password</p>
                    <div className="space-y-3">
                      <Field label="Current password" hint="required to set a new password">
                        <input
                          type="password"
                          value={profileCurrentPw}
                          onChange={(e) => setProfileCurrentPw(e.target.value)}
                          className={inputCls}
                          placeholder="••••••••"
                          autoComplete="current-password"
                        />
                      </Field>
                      <Field label="New password" hint="min 6 characters, leave blank to keep current">
                        <input
                          type="password"
                          value={profileNewPw}
                          onChange={(e) => setProfileNewPw(e.target.value)}
                          className={inputCls}
                          placeholder="••••••••"
                          autoComplete="new-password"
                        />
                      </Field>
                    </div>
                  </div>
                </>
              )}

              {/* ── AI tab ────────────────────────────────────────────────── */}
              {profileTab === "ai" && (
                <>
                  <Field label="Default LLM provider">
                    <select
                      value={prefProvider}
                      onChange={(e) => { setPrefProvider(e.target.value); setPrefModel(""); }}
                      className={selectCls}
                    >
                      {LLM_PROVIDERS.map((p) => (
                        <option key={p.value} value={p.value}>{p.label}</option>
                      ))}
                    </select>
                  </Field>

                  {providerModels.length > 0 && (
                    <Field label="Default model">
                      <select
                        value={prefModel}
                        onChange={(e) => setPrefModel(e.target.value)}
                        className={selectCls}
                      >
                        <option value="">Provider default</option>
                        {providerModels.map((m) => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </select>
                    </Field>
                  )}

                  <Field label="Default system prompt" hint="prepended to every chat session">
                    <textarea
                      value={prefSystemPrompt}
                      onChange={(e) => setPrefSystemPrompt(e.target.value)}
                      className={`${inputCls} resize-none`}
                      rows={4}
                      placeholder="You are a helpful AI assistant specializing in…"
                    />
                  </Field>

                  <Field label="Default RAG collection" hint="knowledge base searched by default">
                    <input
                      type="text"
                      value={prefRagCollection}
                      onChange={(e) => setPrefRagCollection(e.target.value)}
                      className={inputCls}
                      placeholder="e.g. docs"
                    />
                  </Field>

                  <Field label="Output language">
                    <select
                      value={prefLanguage}
                      onChange={(e) => setPrefLanguage(e.target.value)}
                      className={selectCls}
                    >
                      {LANGUAGES.map((l) => (
                        <option key={l} value={l}>{l}</option>
                      ))}
                    </select>
                  </Field>
                </>
              )}

              {/* ── Workspace tab ─────────────────────────────────────────── */}
              {profileTab === "workspace" && (
                <>
                  <Field label="Timezone">
                    <select
                      value={prefTimezone}
                      onChange={(e) => setPrefTimezone(e.target.value)}
                      className={selectCls}
                    >
                      {TIMEZONES.map((tz) => (
                        <option key={tz} value={tz}>{tz}</option>
                      ))}
                    </select>
                  </Field>

                  <Field label="Default workspace user ID" hint="pre-fills the workflow library filter">
                    <input
                      type="text"
                      value={prefDefaultUserId}
                      onChange={(e) => setPrefDefaultUserId(e.target.value)}
                      className={inputCls}
                      placeholder={user?.user_id ?? "user ID"}
                    />
                  </Field>

                  <Field label="Notifications">
                    <div className="mt-1 space-y-3">
                      {[
                        { key: "done" as const,    label: "Workflow completed",  checked: prefNotifWorkflowDone,   set: setPrefNotifWorkflowDone },
                        { key: "failed" as const,  label: "Run failed",          checked: prefNotifRunFailed,      set: setPrefNotifRunFailed },
                        { key: "trigger" as const, label: "Trigger invoked",     checked: prefNotifTriggerInvoked, set: setPrefNotifTriggerInvoked },
                      ].map(({ key, label, checked, set }) => (
                        <label key={key} className="flex cursor-pointer items-center gap-3">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => set(e.target.checked)}
                            className="h-4 w-4 rounded border-subtle accent-sky-500"
                          />
                          <span className="text-sm text-text-hi">{label}</span>
                        </label>
                      ))}
                    </div>
                  </Field>
                </>
              )}
            </div>

            {/* Footer */}
            <div className="shrink-0 border-t border-subtle px-6 py-4">
              {profileError ? (
                <div className="mb-3 rounded-xl border border-rose-300/20 bg-accent-rose px-3 py-2 text-sm text-text-rose-token">
                  {profileError}
                </div>
              ) : null}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setProfileOpen(false)}
                  className="rounded-xl border border-subtle bg-surface-1 px-4 py-2 text-sm font-semibold text-text-md transition hover:text-text-hi"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => { void saveProfile(); }}
                  disabled={profileSaving || !profileName.trim()}
                  className="rounded-xl border border-sky-400/30 bg-accent-sky px-4 py-2 text-sm font-semibold text-text-sky-token transition hover:border-sky-400/50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {profileSaving ? "Saving…" : "Save changes"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
