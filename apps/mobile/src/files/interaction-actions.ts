import type { MatterFileSelection } from "./contracts.ts";
import type { FilesController } from "./controller.ts";

// Keep the command lease outside React's render cycle: a native callback may
// arrive before disabled controls have received the next snapshot.
export function createFilesInteractionActions(controller: FilesController) {
  let uploading = false;
  const available = () => {
    const snapshot = controller.getSnapshot();
    return (
      !uploading &&
      snapshot.view.state !== "inactive" &&
      snapshot.upload.state !== "preparing" &&
      snapshot.upload.state !== "uploading"
    );
  };
  const canChoose = () => {
    const snapshot = controller.getSnapshot();
    return (
      available() &&
      snapshot.view.state === "ready" &&
      snapshot.upload.state !== "unknown" &&
      !snapshot.cleanupFailed
    );
  };
  return {
    async upload(selection: MatterFileSelection, onOwnedComplete: () => void) {
      if (!canChoose()) return;
      uploading = true;
      try {
        await controller.submit(selection);
        if (controller.getSnapshot().view.state !== "inactive")
          onOwnedComplete();
      } finally {
        uploading = false;
      }
    },
    clear(action: () => void) {
      if (available()) action();
    },
    choose(action: () => void) {
      if (canChoose()) action();
    },
  };
}
