import type { ReactNode } from "react";
import AppShell from "../components/AppShell";
import { ShellProvider } from "../lib/shell";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <ShellProvider>
      <AppShell>{children}</AppShell>
    </ShellProvider>
  );
}
