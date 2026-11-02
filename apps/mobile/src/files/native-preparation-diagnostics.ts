import { isPrivateImportUri } from "./private-imports.ts";

const domains = ["import", "cache", "documents", "external-file", "content", "other"] as const;
export type NativePickedDomain = typeof domains[number];
const steps = ["staging-directory", "staging-path", "selected-exists", "selected-size",
  "staged-exists", "staged-size", "copy-bounded", "target-create", "source-open", "target-open",
  "source-read", "target-write", "source-close", "target-close", "digest", "preparation-policy"] as const;
export type NativePreparationStep = typeof steps[number] | `selected-unavailable-${NativePickedDomain}${"" | "-deleted"}`;
export type NativePreparationDiagnostic = { event: "caseops-file-preparation-failed"; step: NativePreparationStep };
const failureSteps = new WeakMap<object, NativePreparationStep>();
function localFile(uri: string): URL | undefined {
  try {
    const url = new URL(uri);
    if (url.protocol !== "file:" || url.hostname || url.username || url.password || url.search || url.hash
      || url.href !== uri || /[\x00-\x1f\x7f\\]/.test(decodeURIComponent(url.pathname))
      || /%2f/i.test(url.pathname)) return;
    return url;
  } catch { return; }
}
function under(uri: string, root: string): boolean {
  const file = localFile(uri), directory = localFile(root);
  if (!file || !directory) return false;
  return file.pathname.startsWith(`${directory.pathname.replace(/\/$/, "")}/`);
}
// Classification is passive QA metadata, never file admission or permission.
export function nativePickedDomain(uri: string, roots: { imports?: string; cache: string; documents: string }): NativePickedDomain {
  if (uri.startsWith("content:")) return "content";
  if (!localFile(uri)) return "other";
  if (roots.imports && localFile(roots.imports) && isPrivateImportUri(uri, roots.imports)) return "import";
  if (under(uri, roots.cache)) return "cache";
  if (under(uri, roots.documents)) return "documents";
  return "external-file";
}
export function nativePreparationFailureStep(error: unknown): NativePreparationStep | undefined {
  return error !== null && typeof error === "object" ? failureSteps.get(error) : undefined;
}

// Acceptance diagnostics contain only reviewed operation enums. Exception
// strings, paths, selected names and document bytes never enter this channel.
export function createNativePreparationDiagnostics(enabled: boolean, emit: (value: NativePreparationDiagnostic) => void) {
  let firstFailure: NativePreparationStep | undefined;
  let selected: { uri: string; domain: NativePickedDomain; deleted: boolean } | undefined;
  const failed = (step: NativePreparationStep) => {
    if (!(steps as readonly string[]).includes(step) && !domains.some(domain =>
      step === `selected-unavailable-${domain}` || step === `selected-unavailable-${domain}-deleted`))
      throw new Error("Invalid preparation diagnostic.");
    if (enabled) firstFailure ??= step;
  };
  return {
    begin() { firstFailure = undefined; },
    selected(uri: string, domain: NativePickedDomain) {
      if (!domains.includes(domain)) throw new Error("Invalid preparation domain.");
      if (!enabled) return;
      firstFailure = undefined;
      selected = { uri, domain, deleted: false };
    },
    deleted(uri: string) {
      if (enabled && selected?.uri === uri) selected.deleted = true;
    },
    deletedUnder(rootUri: string) {
      if (enabled && selected && under(selected.uri, rootUri)) selected.deleted = true;
    },
    unavailable(uri: string) {
      if (!enabled) return;
      failed(selected?.uri === uri
        ? `selected-unavailable-${selected.domain}${selected.deleted ? "-deleted" : ""}`
        : "selected-exists");
    },
    failed,
    sync<T>(step: NativePreparationStep, action: () => T): T {
      try { return action(); } catch (error) { failed(step); throw error; }
    },
    async<T>(step: NativePreparationStep, action: () => Promise<T>): Promise<T> {
      try {
        const pending = action();
        void pending.catch(() => { failed(step); });
        return pending;
      } catch (error) { failed(step); throw error; }
    },
    report(error?: unknown) {
      if (!enabled) return;
      const step = firstFailure ?? "preparation-policy";
      if (error !== null && typeof error === "object") failureSteps.set(error, step);
      emit({ event: "caseops-file-preparation-failed", step });
    },
  };
}
