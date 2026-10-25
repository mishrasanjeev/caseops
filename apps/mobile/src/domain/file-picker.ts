import type { SessionIdentity } from "../auth/types.ts";
import type {
  MatterFileAsset,
  MatterFileSelection,
} from "../files/contracts.ts";

export type PickerIntent = Readonly<{
  companyId: string;
  userId: string;
  membershipId: string;
  sessionKey: string;
  matterId: string;
  expectedLifecycleVersion: number;
}>;

function belongs(
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
) {
  let epoch = 0;
  let picking = false;
  let intent: PickerIntent | null = null;
  let asset: MatterFileAsset | null = null;
  const clear = () => {
    ++epoch;
    intent = null;
    const previous = asset;
    asset = null;
    if (previous) cleanup(previous);
    changed();
  };
  return {
    get picking() {
      return picking;
    },
    clear,
    snapshot(
      identity: SessionIdentity,
      sessionKey: string,
    ): {
      intent: PickerIntent;
      selection: MatterFileSelection | null;
    } | null {
      if (!intent || !belongs(intent, identity, sessionKey)) return null;
      return {
        intent: { ...intent },
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
    async choose(next: PickerIntent): Promise<void> {
      if (picking) throw new Error("Finish the current file selection first.");
      if (
        !Object.values(next).every((value) =>
          typeof value === "string"
            ? value.length > 0 && value.length <= 200
            : Number.isSafeInteger(value) && value >= 0,
        )
      ) {
        throw new Error("Reload the Matter before selecting a file.");
      }
      clear();
      const owner = epoch;
      intent = { ...next };
      picking = true;
      changed();
      try {
        const result = await pick();
        if (owner !== epoch) {
          if (result) cleanup(result);
          return;
        }
        if (!result) {
          clear();
          return;
        }
        asset = { ...result };
        changed();
      } catch {
        if (owner !== epoch) return;
        clear();
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
