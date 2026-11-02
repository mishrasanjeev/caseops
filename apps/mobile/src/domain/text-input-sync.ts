// A controlled React Native TextInput writes its `value` prop back to the
// native field on every render. When a render lags behind fast typing, that
// write replaces newer native text with an older echo and drops characters
// (observed on the iOS Simulator: "MOBILE-LOCAL-001" became "MOE-LOCAL-001").
// This decides, per render, whether the parent's value is an echo of text the
// user already typed (leave the native field alone) or a genuine programmatic
// change such as a reset, prefill or selection (reseed the native field).
const MAX_PENDING = 64;

export type TextInputSeed = { text: string; generation: number };

export function createTextInputSync(initial: string) {
  let native = initial,
    pending: string[] = [],
    seed: TextInputSeed = { text: initial, generation: 0 };
  return {
    // Call during render with the parent's current value. Idempotent for a
    // repeated render with the same value, as React may render twice.
    render(value: string): TextInputSeed {
      if (value === native) pending = [];
      else if (!pending.includes(value)) {
        native = value;
        pending = [];
        seed = { text: value, generation: seed.generation + 1 };
      }
      return seed;
    },
    // Call from onChangeText before notifying the parent.
    typed(text: string) {
      native = text;
      pending = [...pending.slice(1 - MAX_PENDING), text];
    },
  };
}
