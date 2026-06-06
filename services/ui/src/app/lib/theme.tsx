"use client";

import {
  createContext,
  startTransition,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { apiFetch } from "./auth";

export type AppTheme = "dark" | "light";

export type ShellTheme =
  | "ocean"
  | "midnight"
  | "slate"
  | "forest"
  | "dusk"
  | "ember"
  | "cloud"
  | "sand"
  | "rose";

export type ShellThemeOption = {
  id: ShellTheme;
  label: string;
  /** CSS value shown as swatch preview */
  swatch: string;
};

export const SHELL_THEMES: ShellThemeOption[] = [
  { id: "ocean",    label: "Ocean",    swatch: "linear-gradient(135deg,#435365,#55697c)" },
  { id: "midnight", label: "Midnight", swatch: "linear-gradient(135deg,#0d1117,#1a2233)" },
  { id: "slate",    label: "Slate",    swatch: "linear-gradient(135deg,#0f172a,#1e293b)" },
  { id: "forest",   label: "Forest",   swatch: "linear-gradient(135deg,#0a1f0e,#162a1c)" },
  { id: "dusk",     label: "Dusk",     swatch: "linear-gradient(135deg,#1a1025,#26183a)" },
  { id: "ember",    label: "Ember",    swatch: "linear-gradient(135deg,#1a0e08,#2c1a10)" },
  { id: "cloud",    label: "Cloud",    swatch: "linear-gradient(135deg,#e1e9f2,#f5f8fc)" },
  { id: "sand",     label: "Sand",     swatch: "linear-gradient(135deg,#f5f0e8,#ede5d8)" },
  { id: "rose",     label: "Rose",     swatch: "linear-gradient(135deg,#fdf2f4,#fce7ec)" },
];

const THEME_LS_KEY      = "ape.ui.theme.v1";
const SHELL_THEME_LS_KEY = "ape.ui.shell-theme.v1";
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

const VALID_SHELL_THEMES = new Set<string>(SHELL_THEMES.map((t) => t.id));

function readLsTheme(): AppTheme {
  if (typeof window === "undefined") return "dark";
  const v = window.localStorage.getItem(THEME_LS_KEY);
  if (v === "dark" || v === "light") return v;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readLsShellTheme(): ShellTheme {
  if (typeof window === "undefined") return "ocean";
  const v = window.localStorage.getItem(SHELL_THEME_LS_KEY);
  return (v && VALID_SHELL_THEMES.has(v) ? v : "ocean") as ShellTheme;
}

type AppThemeContextValue = {
  theme: AppTheme;
  shellTheme: ShellTheme;
  mounted: boolean;
  setTheme: (next: AppTheme) => void;
  toggleTheme: () => void;
  setShellTheme: (next: ShellTheme) => void;
};

const AppThemeContext = createContext<AppThemeContextValue | null>(null);

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState]           = useState<AppTheme>("dark");
  const [shellTheme, setShellThemeState] = useState<ShellTheme>("ocean");
  const [mounted, setMounted]            = useState(false);

  // Track whether the server value has been loaded so we don't overwrite it
  // with a stale debounce flush.
  const serverLoadedRef = useRef(false);
  const saveTimerRef    = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 1. Hydrate from localStorage immediately on mount ──────────────────────
  useEffect(() => {
    const lsTheme      = readLsTheme();
    const lsShellTheme = readLsShellTheme();
    setThemeState(lsTheme);
    setShellThemeState(lsShellTheme);
    setMounted(true);

    // ── 2. Overwrite with server value as soon as it arrives ─────────────────
    apiFetch(`${API_URL}/auth/me/preferences`)
      .then((res) => (res.ok ? res.json() : null))
      .then((prefs: Record<string, string> | null) => {
        if (!prefs) return;
        serverLoadedRef.current = true;
        const serverTheme      = prefs.theme as AppTheme | undefined;
        const serverShellTheme = prefs.shell_theme as ShellTheme | undefined;
        if (serverTheme === "dark" || serverTheme === "light") {
          setThemeState(serverTheme);
          window.localStorage.setItem(THEME_LS_KEY, serverTheme);
        }
        if (serverShellTheme && VALID_SHELL_THEMES.has(serverShellTheme)) {
          setShellThemeState(serverShellTheme);
          window.localStorage.setItem(SHELL_THEME_LS_KEY, serverShellTheme);
        }
      })
      .catch(() => {
        // Unauthenticated or network error — keep localStorage values.
      });
  }, []);

  // ── Apply dark/light token attributes ─────────────────────────────────────
  useEffect(() => {
    if (!mounted || typeof window === "undefined") return;
    window.localStorage.setItem(THEME_LS_KEY, theme);
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  }, [mounted, theme]);

  useEffect(() => {
    if (!mounted || typeof window === "undefined") return;
    window.localStorage.setItem(SHELL_THEME_LS_KEY, shellTheme);
  }, [mounted, shellTheme]);

  // ── Debounced server persist (300 ms after last change) ───────────────────
  const persistToServer = (nextTheme: AppTheme, nextShell: ShellTheme) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      apiFetch(`${API_URL}/auth/me/preferences`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: nextTheme, shell_theme: nextShell }),
      }).catch(() => {/* ignore — preference loss on network error is acceptable */});
    }, 300);
  };

  const setTheme = (next: AppTheme) => {
    startTransition(() => setThemeState(next));
    persistToServer(next, shellTheme);
  };

  const setShellTheme = (next: ShellTheme) => {
    startTransition(() => setShellThemeState(next));
    persistToServer(theme, next);
  };

  const value = useMemo<AppThemeContextValue>(
    () => ({
      theme,
      shellTheme,
      mounted,
      setTheme,
      toggleTheme: () => setTheme(theme === "dark" ? "light" : "dark"),
      setShellTheme,
    }),
    [mounted, theme, shellTheme],
  );

  return <AppThemeContext.Provider value={value}>{children}</AppThemeContext.Provider>;
}

export const useAppTheme = () => {
  const value = useContext(AppThemeContext);
  if (!value) throw new Error("useAppTheme must be used within AppThemeProvider.");
  return value;
};
