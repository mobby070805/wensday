import type { ReactNode } from "react";
import { AppShell } from "@/components/Shell";

export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
