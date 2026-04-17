"use client";

import {
  Briefcase,
  ChevronsRight,
  FileSignature,
  Gavel,
  LayoutDashboard,
  LibraryBig,
  ListTodo,
  type LucideIcon,
  PanelsTopLeft,
  Scale,
  Sparkles,
  Users,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/marketing/Logo";
import { type Capability, useRole } from "@/lib/capabilities";
import { cn } from "@/lib/cn";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  section: "work" | "intel" | "admin";
  placeholder?: boolean;
  requiresCapability?: Capability;
};

const NAV: NavItem[] = [
  { href: "/app", label: "Home", icon: LayoutDashboard, section: "work" },
  { href: "/app/matters", label: "Matters", icon: Briefcase, section: "work" },
  { href: "/app/hearings", label: "Hearings", icon: Gavel, section: "work", placeholder: true },
  {
    href: "/app/research",
    label: "Research",
    icon: LibraryBig,
    section: "intel",
    placeholder: true,
  },
  {
    href: "/app/drafting",
    label: "Drafting",
    icon: FileSignature,
    section: "intel",
    placeholder: true,
  },
  {
    href: "/app/recommendations",
    label: "Recommendations",
    icon: Sparkles,
    section: "intel",
    placeholder: true,
  },
  {
    href: "/app/contracts",
    label: "Contracts",
    icon: Scale,
    section: "work",
  },
  {
    href: "/app/outside-counsel",
    label: "Outside Counsel",
    icon: Users,
    section: "work",
  },
  {
    href: "/app/portfolio",
    label: "Portfolio",
    icon: PanelsTopLeft,
    section: "intel",
    placeholder: true,
  },
  {
    href: "/app/admin",
    label: "Admin",
    icon: Wrench,
    section: "admin",
    placeholder: true,
    requiresCapability: "workspace:admin",
  },
];

const SECTION_LABEL: Record<NavItem["section"], string> = {
  work: "Work",
  intel: "Intelligence",
  admin: "Workspace",
};

export function Sidebar() {
  const pathname = usePathname();
  const role = useRole();
  const visible = NAV.filter((item) => {
    if (!item.requiresCapability) return true;
    if (!role) return false;
    // Inline the owner/admin check to avoid importing the capability map
    // twice; matches lib/capabilities.ts.
    if (item.requiresCapability === "workspace:admin") {
      return role === "owner" || role === "admin";
    }
    return true;
  });
  const grouped = Object.entries(SECTION_LABEL)
    .map(([key, label]) => ({
      key: key as NavItem["section"],
      label,
      items: visible.filter((n) => n.section === key),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <aside
      aria-label="Primary navigation"
      className="hidden w-64 shrink-0 flex-col border-r border-[var(--color-line)] bg-white md:flex"
    >
      <div className="flex h-16 items-center border-b border-[var(--color-line)] px-5">
        <Logo />
      </div>
      <nav className="flex flex-1 flex-col gap-6 overflow-y-auto px-3 py-6">
        {grouped.map((group) => (
          <div key={group.key} className="flex flex-col gap-1.5">
            <div className="px-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--color-mute-2)]">
              {group.label}
            </div>
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => (
                <li key={item.href}>
                  <NavLink item={item} active={isActive(pathname, item.href)} />
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="mt-auto rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-[var(--color-ink-2)]">
            <Sparkles className="h-3.5 w-3.5 text-[var(--color-brand-600)]" aria-hidden />
            Early access
          </div>
          <p className="mt-1 text-xs leading-relaxed text-[var(--color-mute)]">
            Features marked <em>preview</em> are on the roadmap in{" "}
            <code className="rounded bg-white px-1 py-0.5 text-[10px]">WORK_TO_BE_DONE.md</code>.
          </p>
        </div>
      </nav>
    </aside>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-label={item.label}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group flex items-center gap-2.5 rounded-md px-2 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-[var(--color-ink)] text-white"
          : "text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]",
      )}
    >
      <Icon
        className={cn("h-4 w-4", active ? "text-white" : "text-[var(--color-mute)]")}
        aria-hidden
      />
      <span className="flex-1" aria-hidden>
        {item.label}
      </span>
      {item.placeholder ? (
        <span
          aria-hidden
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            active ? "bg-white/10 text-white" : "bg-[var(--color-bg-2)] text-[var(--color-mute)]",
          )}
        >
          Preview
        </span>
      ) : null}
      <ChevronsRight
        aria-hidden
        className={cn(
          "h-3.5 w-3.5 opacity-0 transition-opacity",
          active && "opacity-100",
        )}
      />
    </Link>
  );
}

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  if (href === "/app") return pathname === "/app";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export const APP_NAV = NAV;
export const APP_SECTIONS = SECTION_LABEL;
export { ListTodo };
