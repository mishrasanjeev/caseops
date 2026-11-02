export type NativeClientMetadata = Readonly<{
  platform: "android" | "ios";
  version: string;
}>;

export function clientVersionParts(input: unknown): readonly number[] {
  if (typeof input !== "string" || input.length > 29)
    throw new Error("The app version could not be verified.");
  const match =
    /^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$/.exec(
      input,
    );
  if (!match || match[0] !== input)
    throw new Error("The app version could not be verified.");
  return match.slice(1).map(Number);
}

export function compareClientVersions(left: string, right: string): number {
  const a = clientVersionParts(left),
    b = clientVersionParts(right);
  for (let i = 0; i < 3; ++i) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return 0;
}

export function checkedClientMetadata(input: {
  platform: unknown;
  version: unknown;
}): NativeClientMetadata {
  if (input.platform !== "android" && input.platform !== "ios")
    throw new Error("The app platform could not be verified.");
  clientVersionParts(input.version);
  return { platform: input.platform, version: input.version as string };
}
