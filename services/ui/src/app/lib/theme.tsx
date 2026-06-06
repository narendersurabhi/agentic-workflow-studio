"use client";

import {
  createContext,
  startTransition,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

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

const THEME_STORAGE_KEY = "ape.ui.theme.v1";
const SHELL_THEME_STORAGE_KEY = "ape.ui.shell-theme.v1";

type AppThemeContextValue = {
  theme: AppTheme;
  shellTheme: ShellTheme;
  mounted: boolean;
  setTheme: (nextTheme: AppTheme) => void;
  toggleTheme: () => void;
  setShellTheme: (next: ShellTheme) => void;
};

const AppThemeContext = createContext<AppThemeContextValue | null>(null);

const resolveInitialTheme = (): AppTheme => {
  if (typeof window === "undefined") return "dark";
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

const resolveInitialShellTheme = (): ShellTheme => {
  if (typeof window === "undefined") return "ocean";
  const stored = window.localStorage.getItem(SHELL_THEME_STORAGE_KEY) as ShellTheme | null;
  if (stored && SHELL_THEMES.some((t) => t.id === stored)) return stored;
  return "ocean";
};

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<AppTheme>("dark");
  const [shellTheme, setShellThemeState] = useState<ShellTheme>("ocean");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setThemeState(resolveInitialTheme());
    setShellThemeState(resolveInitialShellTheme());
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted || typeof window === "undefined") return;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  }, [mounted, theme]);

  useEffect(() => {
    if (!mounted || typeof window === "undefined") return;
    window.localStorage.setItem(SHELL_THEME_STORAGE_KEY, shellTheme);
  }, [mounted, shellTheme]);

  const setTheme = (nextTheme: AppTheme) => {
    startTransition(() => setThemeState(nextTheme));
  };

  const setShellTheme = (next: ShellTheme) => {
    startTransition(() => setShellThemeState(next));
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
    [mounted, theme, shellTheme]
  );

  return <AppThemeContext.Provider value={value}>{children}</AppThemeContext.Provider>;
}

export const useAppTheme = () => {
  const value = useContext(AppThemeContext);
  if (!value) throw new Error("useAppTheme must be used within AppThemeProvider.");
  return value;
};
