import type { AuthorizedRequest } from "../domain/repository";
import type { LocalSessionBinding, SessionIdentity } from "../auth/types";
import type { RecordLinkInbox } from "../domain/record-links";
import type { MatterFileSelection } from "../files/contracts";
import type { FileSelectionState } from "../domain/file-picker";
import type { ViewerPorts } from "../viewer/contracts";

export type MobileApplicationProps = {
  request: AuthorizedRequest;
  identity: SessionIdentity;
  sessionKey: string;
  initialFilesMatterId?: string;
  recordLinks?: {
    inbox: RecordLinkInbox;
    binding: LocalSessionBinding;
  };
  selectedFile: MatterFileSelection | null;
  onChooseFile: (matterId: string, expectedLifecycleVersion: number) => void;
  onCapturePhoto: (matterId: string, expectedLifecycleVersion: number) => void;
  selectingFile: boolean;
  selectionRevision: number;
  readFileSelection: () => FileSelectionState;
  localUnlock?: {
    enabled: boolean;
    busy: boolean;
    message: string;
    enable: () => Promise<void>;
  };
  onClearSelectedFile: () => void;
  viewer: Pick<
    ViewerPorts,
    "requestBytes" | "sha256" | "subscribeInvalidation"
  >;
  onSignOut: () => Promise<void>;
};

export type MatterSection = "Summary" | "Activity" | "Files" | "Work";

export type LeaveGuard = (leave: () => void) => void;
