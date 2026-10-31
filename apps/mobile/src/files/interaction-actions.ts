import type { MatterFileSelection } from "./contracts.ts";
import type { FilesController } from "./controller.ts";
import type { FileSelectionState } from "../domain/file-picker.ts";

// Keep the command lease outside React's render cycle: a native callback may
// arrive before disabled controls have received the next snapshot.
export function createFilesInteractionActions(
  controller: FilesController,
  readSelection: () => FileSelectionState,
) {
  let uploading = false;
  let interacting = false;
  let leaving = false;
  const selectionState = (): FileSelectionState | null => {
    try {
      const value = readSelection();
      if (
        typeof value.picking !== "boolean" ||
        typeof value.hasSelection !== "boolean" ||
        !Number.isSafeInteger(value.revision) ||
        value.revision < 0
      )
        return null;
      return { ...value };
    } catch {
      return null;
    }
  };
  const available = (expectedRevision?: number) => {
    const snapshot = controller.getSnapshot();
    const selected = selectionState();
    return (
      !!selected &&
      !selected.picking &&
      (expectedRevision === undefined ||
        selected.revision === expectedRevision) &&
      !interacting &&
      !leaving &&
      !uploading &&
      snapshot.view.state !== "inactive" &&
      snapshot.upload.state !== "preparing" &&
      snapshot.upload.state !== "uploading"
    );
  };
  const canChoose = (expectedRevision?: number) => {
    const snapshot = controller.getSnapshot();
    return (
      available(expectedRevision) &&
      snapshot.view.state === "ready" &&
      snapshot.upload.state !== "unknown" &&
      !snapshot.cleanupFailed
    );
  };
  return {
    selectionState,
    canLeave: (expectedRevision: number) => available(expectedRevision),
    leave(action: () => void, expectedRevision: number): boolean {
      if (!available(expectedRevision)) return false;
      leaving = true;
      action();
      return true;
    },
    async upload(
      selection: MatterFileSelection,
      onOwnedComplete: () => void,
      expectedRevision: number,
    ) {
      if (!canChoose(expectedRevision)) return;
      uploading = true;
      try {
        await controller.submit(selection);
        if (controller.getSnapshot().view.state !== "inactive")
          onOwnedComplete();
      } finally {
        uploading = false;
      }
    },
    clear(action: () => void, expectedRevision: number) {
      if (!available(expectedRevision)) return;
      interacting = true;
      try {
        action();
      } finally {
        interacting = false;
      }
    },
    choose(action: () => void, expectedRevision: number) {
      if (!canChoose(expectedRevision)) return;
      interacting = true;
      try {
        action();
      } finally {
        interacting = false;
      }
    },
  };
}
