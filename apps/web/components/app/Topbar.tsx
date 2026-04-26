"use client";

import { LogOut, Menu, Search } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import { SidebarBody } from "@/components/app/Sidebar";
import { Avatar, AvatarFallback, initialsFrom } from "@/components/ui/Avatar";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/DropdownMenu";
import { Input } from "@/components/ui/Input";
import { useSession } from "@/lib/use-session";

export function Topbar() {
  const router = useRouter();
  const pathname = usePathname();
  const { context, signOut } = useSession();
  const user = context?.user;
  const company = context?.company;
  // Topbar search routes to the Research workspace. A federated search
  // over matters + contracts + authorities is Sprint K scope; today we
  // route to /app/research which hits the authority corpus. Honest + it
  // works end-to-end with the 5,714-doc corpus.
  const [searchValue, setSearchValue] = useState("");
  // Ram-BUG-005 (2026-04-22): mobile users had no way to open the
  // sidebar nav (it's hidden md:flex). The hamburger renders only
  // below md and pops the same nav body inside a left-anchored
  // dialog. Closes itself on navigate so the user lands on the
  // chosen page without a stale overlay.
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  function handleSignOut() {
    signOut();
    toast.success("Signed out");
    router.replace("/sign-in");
  }

  function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = searchValue.trim();
    if (trimmed.length < 2) {
      toast.error("Type at least two characters to search.");
      return;
    }
    router.push(`/app/research?q=${encodeURIComponent(trimmed)}`);
  }

  return (
    <header className="flex h-16 items-center gap-3 border-b border-[var(--color-line)] bg-white px-4 md:px-6">
      <Dialog open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <DialogTrigger asChild>
          <button
            type="button"
            aria-label="Open navigation menu"
            data-testid="mobile-nav-trigger"
            className="md:hidden inline-flex h-9 w-9 items-center justify-center rounded-md border border-[var(--color-line)] text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]"
          >
            <Menu className="h-5 w-5" aria-hidden />
          </button>
        </DialogTrigger>
        <DialogPortal>
          <DialogOverlay />
          {/* Anchor the panel to the left edge instead of centred —
              this is a navigation drawer, not a centered modal. */}
          <DialogContent className="left-0 top-0 h-full max-h-screen w-72 max-w-full translate-x-0 translate-y-0 rounded-none border-r border-[var(--color-line)] p-0">
            <DialogTitle className="sr-only">Workspace navigation</DialogTitle>
            <DialogClose className="sr-only">Close</DialogClose>
            <div className="flex h-full flex-col bg-white">
              <SidebarBody
                pathname={pathname}
                onNavigate={() => setMobileNavOpen(false)}
              />
            </div>
          </DialogContent>
        </DialogPortal>
      </Dialog>
      <form
        onSubmit={handleSearchSubmit}
        className="relative flex-1 max-w-md"
        role="search"
        aria-label="Workspace search"
      >
        <Search
          className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-mute-2)]"
          aria-hidden
        />
        <Input
          value={searchValue}
          onChange={(e) => setSearchValue(e.target.value)}
          placeholder="Search authorities — matters + contracts coming soon"
          className="pl-8"
          aria-label="Search authorities (Enter to open Research)"
          type="search"
        />
      </form>
      <div className="hidden md:flex md:flex-col md:items-end md:leading-tight">
        <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
          Workspace
        </span>
        <span className="text-sm font-semibold text-[var(--color-ink)]">
          {company?.name ?? "—"}
        </span>
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label="Open user menu"
          className="rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]"
        >
          <Avatar>
            <AvatarFallback>{initialsFrom(user?.full_name ?? "?")}</AvatarFallback>
          </Avatar>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel className="truncate">{user?.full_name ?? "Signed in"}</DropdownMenuLabel>
          <DropdownMenuLabel className="-mt-1 truncate text-[10px] normal-case tracking-normal text-[var(--color-mute-2)]">
            {user?.email}
          </DropdownMenuLabel>
          {/*
            BUG-022 (Ram 2026-04-26): Profile and Workspace-settings
            menu items were rendering as disabled placeholders. A
            disabled menu row that does nothing on click is a worse
            signal than no row at all — Ram (correctly) flagged them
            as broken. Until the underlying /app/profile and
            /app/admin/workspace routes ship, hide them entirely.
            Per `feedback_fix_vs_mitigation`: no impossible actions
            in the UI.
          */}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={handleSignOut} data-testid="sign-out">
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
