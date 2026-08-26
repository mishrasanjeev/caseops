"use client";

import {
  Bell,
  Bookmark,
  BookOpenCheck,
  BookOpenText,
  Briefcase,
  CalendarClock,
  CalendarDays,
  ChevronsRight,
  Contact,
  CreditCard,
  Database,
  FileSignature,
  FileClock,
  FileChartColumn,
  Gavel,
  Globe2,
  HardDrive,
  History,
  Inbox,
  LayoutDashboard,
  Languages,
  ListChecks,
  LibraryBig,
  ListTodo,
  type LucideIcon,
  PanelsTopLeft,
  PlugZap,
  Repeat2,
  Radar,
  Scale,
  ShieldCheck,
  Sparkles,
  Sun,
  Users,
  UserRoundCheck,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/marketing/Logo";
import {
  type Capability,
  can,
  useResolvedCapabilities,
  useRole,
} from "@/lib/capabilities";
import { cn } from "@/lib/cn";
import {
  PRODUCT_GUIDE_CATALOG,
  type ProductGuideNavigationGroup,
} from "@/lib/product-guide";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  section: ProductGuideNavigationGroup;
  requiredCapabilities: readonly Capability[];
};

const ICON_BY_NAME: Record<string, LucideIcon> = {
  Bell,
  Bookmark,
  BookOpenCheck,
  BookOpenText,
  Briefcase,
  CalendarClock,
  CalendarDays,
  Contact,
  CreditCard,
  Database,
  FileChartColumn,
  FileClock,
  FileSignature,
  Gavel,
  Globe2,
  HardDrive,
  History,
  Inbox,
  Languages,
  LayoutDashboard,
  LibraryBig,
  ListChecks,
  ListTodo,
  PanelsTopLeft,
  PlugZap,
  Radar,
  Repeat2,
  Scale,
  ShieldCheck,
  Sparkles,
  Sun,
  UserRoundCheck,
  Users,
  Wrench,
};

const NAV_ITEMS: NavItem[] = PRODUCT_GUIDE_CATALOG.commands.map((command) => {
  const icon = ICON_BY_NAME[command.icon];
  if (!icon) throw new Error(`Unknown Product Guide icon: ${command.icon}`);
  return {
    href: command.href,
    label: command.label,
    icon,
    section: command.group,
    requiredCapabilities: command.required_capabilities,
  };
});

// Order is the reading order of the sidebar. "Work" previously held 17 of the
// 33 destinations in one flat list, which is more than anyone scans, and it mixed
// the daily action list with scheduling views, casework and settings. The groups
// below separate *what must I do* from *when is it* from *what is it about*, so
// a lawyer arriving in the morning has one obvious starting point rather than
// six plausible ones.
const SECTION_LABEL = PRODUCT_GUIDE_CATALOG.navigation_groups;

// Ram-BUG-005 (2026-04-22): the inner nav body is split out so the
// mobile hamburger trigger in Topbar can render the same content
// inside a Radix Dialog without copy-pasting the menu items.
export function SidebarBody({
  pathname,
  onNavigate,
}: {
  pathname: string;
  onNavigate?: () => void;
}) {
  const role = useRole();
  const resolvedCapabilities = useResolvedCapabilities();
  const visible = NAV_ITEMS.filter((item) => {
    if (item.requiredCapabilities.length === 0) return true;
    if (resolvedCapabilities) {
      return item.requiredCapabilities.every((capability) =>
        resolvedCapabilities.includes(capability),
      );
    }
    return item.requiredCapabilities.every((capability) => can(role, capability));
  });
  const grouped = Object.entries(SECTION_LABEL)
    .map(([key, label]) => ({
      key: key as NavItem["section"],
      label,
      items: visible.filter((n) => n.section === key),
    }))
    .filter((group) => group.items.length > 0);

  return (
    <>
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
                  <NavLink
                    item={item}
                    active={isActive(pathname, item.href)}
                    onNavigate={onNavigate}
                  />
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
            Pilot build. Tell us what we should ship next.
          </p>
        </div>
      </nav>
    </>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside
      aria-label="Primary navigation"
      className="hidden w-64 shrink-0 flex-col border-r border-[var(--color-line)] bg-white md:flex"
    >
      <SidebarBody pathname={pathname} />
    </aside>
  );
}

function NavLink({
  item,
  active,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-label={item.label}
      aria-current={active ? "page" : undefined}
      onClick={onNavigate}
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

export const APP_NAV = NAV_ITEMS;
export const APP_SECTIONS = SECTION_LABEL;
export { ListTodo };
