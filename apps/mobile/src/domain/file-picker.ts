import type { SessionIdentity } from "../auth/types.ts";
import type {
  MatterFileAsset,
  MatterFileSelection,
} from "../files/contracts.ts";
import { TempCleanupError } from "../files/staging.ts";
import { CameraCaptureError } from "../files/camera.ts";

export type PickerIntent = Readonly<{
  companyId: string;
  userId: string;
  membershipId: string;
  sessionKey: string;
  matterId: string;
  expectedLifecycleVersion: number;
}>;
export type FileSelectionState = Readonly<{
  picking: boolean;
  revision: number;
  hasSelection: boolean;
}>;

export function pickerIdentityMatches(
  intent: PickerIntent,
  identity: SessionIdentity,
  sessionKey: string,
) {
  return (
    intent.companyId === identity.company.id &&
    intent.userId === identity.user.id &&
    intent.membershipId === identity.membership.id &&
    intent.sessionKey === sessionKey
  );
}

// Only opaque navigation identity survives the OS picker. No Matter DTO or bytes.
export function createFilePickerCoordinator(
  pick: () => Promise<MatterFileAsset | null>,
  cleanup: (asset: MatterFileAsset) => void,
  changed: () => void,
  capture?: (current: () => boolean) => Promise<MatterFileAsset | null>,
) {
  let epoch = 0;
  let picking = false;
  // Android's system picker backgrounds the app, so its result arrives before
  // the routine compatibility recheck that follows the return. Keep the
  // opaque intent and result through that recheck, never past a later clear.
  let returning = false;
  let intent: PickerIntent | null = null;
  let asset: MatterFileAsset | null = null;
  const clear = () => {
    ++epoch;
    returning = false;
    intent = null;
    const previous = asset;
    asset = null;
    try {
      if (previous) cleanup(previous);
    } finally {
      changed();
    }
  };
  return {
    get picking() {
      return picking;
    },
    /** True from choose() until settle() or any clear. */
    get leased() {
      return picking || returning;
    },
    /** The app is active again and its compatibility recheck succeeded. */
    settle() {
      returning = false;
    },
    get selectionState(): FileSelectionState {
      return { picking, revision: epoch, hasSelection: asset !== null };
    },
    clear,
    snapshot(
      identity: SessionIdentity,
      sessionKey: string,
    ): {
      intent: PickerIntent;
      selection: MatterFileSelection | null;
      revision: number;
    } | null {
      if (!intent || !pickerIdentityMatches(intent, identity, sessionKey))
        return null;
      return {
        intent: { ...intent },
        revision: epoch,
        selection: asset
          ? {
              companyId: intent.companyId,
              userId: intent.userId,
              matterId: intent.matterId,
              sessionKey: intent.sessionKey,
              expectedLifecycleVersion: intent.expectedLifecycleVersion,
              asset: { ...asset },
            }
          : null,
      };
    },
    async choose(
      next: PickerIntent,
      source: "file" | "camera" = "file",
    ): Promise<void> {
      if (picking) throw new Error("Finish the current file selection first.");
      if (source !== "file" && source !== "camera")
        throw new Error("Choose an available file source.");
      if (
        !Object.values(next).every((value) =>
          typeof value === "string"
            ? value.length > 0 && value.length <= 200
            : Number.isSafeInteger(value) && value >= 0,
        )
      ) {
        throw new Error("Reload the Matter before selecting a file.");
      }
      // Claim before cleanup/publish can synchronously reenter a retained UI
      // callback. A privacy clear during that publish must not be reacquired.
      picking = true;
      const owner = epoch + 1;
      try {
        clear();
        if (owner !== epoch) return;
        intent = { ...next };
        returning = true;
        changed();
        if (owner !== epoch) return;
        const result =
          source === "camera"
            ? await (capture
                ? capture(() => owner === epoch)
                : Promise.reject(new CameraCaptureError("unavailable")))
            : await pick();
        if (owner !== epoch) {
          if (result) cleanup(result);
          return;
        }
        // A cancelled pick keeps only the opaque navigation intent so the
        // user returns to the same Matter Files screen with nothing selected.
        if (!result) return;
        asset = { ...result };
        changed();
      } catch (cause) {
        // Cleanup failure remains actionable even if logout invalidated the
        // picker. An unrelated late provider rejection still stays silent.
        if (cause instanceof TempCleanupError) throw cause;
        if (owner !== epoch) return;
        clear();
        if (cause instanceof CameraCaptureError) throw cause;
        throw new Error(
          "The file could not be selected. Choose it again when ready.",
        );
      } finally {
        picking = false;
        changed();
      }
    },
  };
}
