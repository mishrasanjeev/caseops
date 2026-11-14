type Entry = { type: string; instance?: number };

// A cursor belongs to a navigation instance, including while another tab or
// nested route is active. Array position alone can be reused in one commit.
export function sourceListEntries<T extends Entry>(
  stacks: Readonly<Record<string, readonly T[]>>,
  companyId: string,
  kind: string,
) {
  const result: { entry: T; origin: string; key: string }[] = [];
  const keys = new Set<string>();
  for (const [origin, entries] of Object.entries(stacks)) {
    for (const entry of entries) {
      if (entry.type !== "source-list") continue;
      if (!Number.isSafeInteger(entry.instance) || entry.instance! <= 0)
        throw new Error("Sources navigation instance is unavailable.");
      const key = `${companyId}:${origin}:${kind}:${entry.instance}`;
      if (keys.has(key))
        throw new Error("Sources navigation instance is repeated.");
      keys.add(key);
      result.push({ entry, origin, key });
    }
  }
  return result;
}
