"use client";

import { LogOut, Search, Settings, User } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import { Avatar, AvatarFallback, initialsFrom } from "@/components/ui/Avatar";
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
  const { context, signOut } = useSession();
  const user = context?.user;
  const company = context?.company;
  // Topbar search routes to the Research workspace. A federated search
  // over matters + contracts + authorities is Sprint K scope; today we
  // route to /app/research which hits the authority corpus. Honest + it
  // works end-to-end with the 5,714-doc corpus.
  const [searchValue, setSearchValue] = useState("");

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
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled>
            <User className="h-4 w-4" aria-hidden />
            Profile
          </DropdownMenuItem>
          <DropdownMenuItem disabled>
            <Settings className="h-4 w-4" aria-hidden />
            Workspace settings
          </DropdownMenuItem>
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
