import type { AuthorizedRequest } from "../domain/repository";
import type { SessionIdentity } from "../auth/types";
import type { MatterFileSelection } from "../files/contracts";
import type { ViewerPorts } from "../viewer/contracts";

export type MobileApplicationProps = {
  request: AuthorizedRequest;
  identity: SessionIdentity;
  sessionKey: string;
  initialFilesMatterId?: string;
  selectedFile: MatterFileSelection | null;
  onChooseFile: (matterId: string, expectedLifecycleVersion: number) => void;
  onClearSelectedFile: () => void;
  viewer: Pick<
    ViewerPorts,
    "requestBytes" | "sha256" | "subscribeInvalidation"
  >;
  onSignOut: () => Promise<void>;
};

export type MatterSection = "Summary" | "Activity" | "Files" | "Work";

export type LeaveGuard = (leave: () => void) => void;
