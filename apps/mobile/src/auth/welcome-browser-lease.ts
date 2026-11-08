import { PRIVACY_POLICY_OPEN_TIMEOUT_MS } from "../domain/privacy-policy.ts";

// The privacy policy hands the welcome screen to a system browser; sign-in is
// refused while that launch holds this lease (sign-in tracks its own flight).
// A launch promise that never settles must not lock sign-in until the app is
// killed: the lease also ends at the privacy
// opener's acknowledgement deadline, or when the app returns to the foreground
// after the browser sent it to the background. Each launch owns its release, so
// a late settlement cannot end a newer launch's lease.
export function createWelcomeBrowserLease(changed: (held: boolean) => void) {
  let owner = 0,
    held = false,
    backgrounded = false,
    timer: ReturnType<typeof setTimeout> | undefined;
  const release = (launch: number) => {
    if (!held || launch !== owner) return;
    held = false;
    clearTimeout(timer);
    changed(false);
  };
  return {
    get held() {
      return held;
    },
    async launch(open: () => Promise<unknown>) {
      if (held) throw Error("Browser action unavailable");
      const launch = ++owner;
      held = true;
      backgrounded = false;
      timer = setTimeout(() => release(launch), PRIVACY_POLICY_OPEN_TIMEOUT_MS);
      changed(true);
      try {
        await open();
      } finally {
        release(launch);
      }
    },
    visibility(state: string) {
      if (!held) return;
      if (state === "background") backgrounded = true;
      else if (state === "active" && backgrounded) release(owner);
    },
  };
}
