import type { AuthorizedRequest } from "../domain/repository";

export type MobileApplicationProps = {
  request: AuthorizedRequest;
  identity: {
    company: { id: string; name: string; slug: string };
    user: { id: string; email: string; full_name?: string | null };
    capabilities: string[];
  };
  onSignOut: () => Promise<void>;
};

export type MatterSection = "Summary" | "Activity" | "Files" | "Work";

export type LeaveGuard = (leave: () => void) => void;
