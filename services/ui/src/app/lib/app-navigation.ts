export type AppScreenId =
  | "home"
  | "project"
  | "compose"
  | "chat"
  | "workflows"
  | "studio"
  | "memory"
  | "rag"
  | "skills"
  | "observability";

export type AppNavIcon = "home" | "menu" | "palette" | "chat" | "library" | "graph" | "inspect" | "zap" | "activity";

export type AppNavItem = {
  id: AppScreenId;
  label: string;
  title: string;
  href: string;
  icon: AppNavIcon;
};

export const PRIMARY_APP_NAV_ITEMS: AppNavItem[] = [
  { id: "home",          label: "Home",             title: "Home",             href: "/",              icon: "home" },
  { id: "project",       label: "Project",           title: "Project",          href: "/project",       icon: "menu" },
  { id: "compose",       label: "Run from Prompt",   title: "Run from Prompt",  href: "/compose",       icon: "palette" },
  { id: "chat",          label: "Chat",              title: "Chat",             href: "/chat",          icon: "chat" },
  { id: "workflows",     label: "Saved Workflows",   title: "Saved Workflows",  href: "/workflows",     icon: "library" },
  { id: "studio",        label: "Workflow Studio",   title: "Workflow Studio",  href: "/studio",        icon: "graph" },
  { id: "memory",        label: "Context",           title: "Context & Memory", href: "/memory",        icon: "inspect" },
  { id: "rag",           label: "Knowledge",         title: "Knowledge Base",   href: "/rag",           icon: "library" },
  { id: "skills",        label: "Skills",            title: "Skills",           href: "/skills",        icon: "zap" },
  { id: "observability", label: "Observability",     title: "Observability",    href: "/observability", icon: "activity" },
];
