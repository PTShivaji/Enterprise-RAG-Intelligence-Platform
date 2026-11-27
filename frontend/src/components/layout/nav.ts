import { BarChart3, BookOpen, FileText, LayoutDashboard, MessageSquareText, Search, Settings, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  description: string;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, description: "Workspace summary" },
  { to: "/chat", label: "AI Chat", icon: MessageSquareText, description: "Grounded Q&A over your documents" },
  { to: "/knowledge", label: "Knowledge Base", icon: BookOpen, description: "Browse indexed content" },
  { to: "/documents", label: "Documents", icon: FileText, description: "Upload and manage files" },
  { to: "/search", label: "Search", icon: Search, description: "Hybrid retrieval workspace" },
  { to: "/analytics", label: "Analytics", icon: BarChart3, description: "Usage, cache and evaluation" },
  { to: "/settings", label: "Settings", icon: Settings, description: "Retrieval and generation" },
];

export function navItemFor(pathname: string): NavItem {
  return (
    NAV_ITEMS.filter((n) => n.to !== "/" && pathname.startsWith(n.to)).sort((a, b) => b.to.length - a.to.length)[0] ??
    NAV_ITEMS[0]
  );
}
