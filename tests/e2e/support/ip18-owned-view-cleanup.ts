import { isDeepStrictEqual } from "node:util";

export type OwnedIp18View = { id: string; name: string; version: number };
export type Ip18CleanupView = OwnedIp18View & { scope: string; editable: boolean; is_default: boolean; team_id: string | null };

/** Remove only the canonical identity acknowledged by this run's successful create. */
export async function cleanupOwnedIp18View(owned: OwnedIp18View, operations: {
  release: () => Promise<void>;
  list: () => Promise<Ip18CleanupView[]>;
  remove: (id: string) => Promise<void>;
}) {
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(owned.id)
      || !/^IP18 dates /.test(owned.name) || owned.version !== 1) {
    throw new Error("IP18 cleanup requires its acknowledged canonical identity.");
  }
  await operations.release();
  const before = await operations.list();
  const matches = before.filter(view => view.id === owned.id);
  if (matches.length !== 1 || matches[0].name !== owned.name || matches[0].version !== owned.version
      || matches[0].scope !== "personal" || !matches[0].editable || matches[0].is_default || matches[0].team_id !== null) {
    throw new Error("Owned IP18 preference changed; cleanup refused.");
  }
  const others = before.filter(view => view.id !== owned.id).sort((a, b) => a.id.localeCompare(b.id));
  await operations.remove(owned.id);
  const after = (await operations.list()).sort((a, b) => a.id.localeCompare(b.id));
  if (!isDeepStrictEqual(after, others)) throw new Error("IP18 cleanup readback differs; no automatic replay.");
  return { acknowledged_identity: true, deleted_count: 1, remaining_unchanged: true };
}
