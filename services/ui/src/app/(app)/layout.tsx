import type { ReactNode } from "react";
import AppShell from "../components/AppShell";
import { ShellProvider } from "../lib/shell";
import { AppQueryProvider } from "../lib/queryClient";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AppQueryProvider>
      <ShellProvider>
        <AppShell>{children}</AppShell>
      </ShellProvider>
    </AppQueryProvider>
  );
}
