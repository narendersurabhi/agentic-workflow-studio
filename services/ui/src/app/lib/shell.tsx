"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

export type ShellBreadcrumb = { label: string; href?: string };

type ShellMeta = { title: string; breadcrumbs: ShellBreadcrumb[] };

type ShellContextValue = {
  meta: ShellMeta;
  setMeta: (m: ShellMeta) => void;
  actionsSlotRef: React.RefObject<HTMLDivElement | null>;
};

const ShellContext = createContext<ShellContextValue | null>(null);

export function ShellProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<ShellMeta>({ title: "", breadcrumbs: [] });
  const actionsSlotRef = useRef<HTMLDivElement | null>(null);

  return (
    <ShellContext.Provider value={{ meta, setMeta, actionsSlotRef }}>
      {children}
    </ShellContext.Provider>
  );
}

function useShellContext() {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell* must be used inside ShellProvider");
  return ctx;
}

/** Read shell metadata — used by AppShell. */
export function useShellMeta() {
  return useShellContext().meta;
}

/** Read the ref for the actions slot div — used by AppShell to attach the div. */
export function useShellActionsSlotRef() {
  return useShellContext().actionsSlotRef;
}

/**
 * Called by each page/screen to declare its title and breadcrumbs.
 * Runs once on mount and clears on unmount.
 */
export function useShell({
  title,
  breadcrumbs = [],
}: {
  title: string;
  breadcrumbs?: ShellBreadcrumb[];
}) {
  const { setMeta } = useShellContext();
  useEffect(() => {
    setMeta({ title, breadcrumbs });
    return () => setMeta({ title: "", breadcrumbs: [] });
    // breadcrumbs are per-page constants — title change is the only reactive dep
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title]);
}

/**
 * Renders children into the shell header's actions slot via a portal.
 * Use this inside any screen that needs header action buttons.
 * The content re-renders normally with the screen's state — no infinite loops
 * because AppShell itself does not re-render when the portal content changes.
 */
export function ShellActions({ children }: { children: ReactNode }) {
  const { actionsSlotRef } = useShellContext();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted || !actionsSlotRef.current) return null;
  return createPortal(children, actionsSlotRef.current);
}
