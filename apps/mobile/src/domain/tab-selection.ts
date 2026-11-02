// Pressing the tab that is already selected must not run the leave guard.
// The guard hands the screen's leave lease to its action and expects that
// action to navigate away; setTab(current) navigates nowhere, which left Files
// holding a spent lease so every later Back reported "File action in progress".
export function selectTab<T extends string>(
  current: T,
  next: T,
  guarded: (action: () => void) => void,
  setTab: (tab: T) => void,
): boolean {
  if (next === current) return false;
  guarded(() => setTab(next));
  return true;
}
