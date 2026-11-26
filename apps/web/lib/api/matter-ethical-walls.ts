import { z } from "zod";

import { apiRequest } from "./client";

// Matter ethical walls (services/matter_access.py). Owner/admin only
// (`matter_access:manage`); every write and the directory read are audited.

export const matterEthicalWallDirectoryRowSchema = z.object({
  id: z.string(),
  matter_id: z.string(),
  matter_code: z.string(),
  matter_title: z.string(),
  excluded_membership_id: z.string(),
  excluded_full_name: z.string(),
  excluded_email: z.string(),
  excluded_role: z.enum(["owner", "admin", "partner", "member", "paralegal", "viewer"]),
  excluded_membership_active: z.boolean(),
  enforced: z.boolean(),
  reason: z.string().nullable(),
  created_by_membership_id: z.string().nullable(),
  created_by_full_name: z.string().nullable(),
  created_at: z.string(),
});

export const matterEthicalWallDirectorySchema = z.object({
  walls: z.array(matterEthicalWallDirectoryRowSchema),
  truncated: z.boolean(),
});

export const matterEthicalWallSchema = z.object({
  id: z.string(),
  matter_id: z.string(),
  excluded_membership_id: z.string(),
  reason: z.string().nullable(),
  created_by_membership_id: z.string().nullable(),
  created_at: z.string(),
});

export type MatterEthicalWallDirectoryRow = z.infer<typeof matterEthicalWallDirectoryRowSchema>;
export type MatterEthicalWallDirectory = z.infer<typeof matterEthicalWallDirectorySchema>;
export type MatterEthicalWall = z.infer<typeof matterEthicalWallSchema>;

/** Server limit on `reason` (schemas/matter_access.py EthicalWallCreateRequest). */
export const MATTER_WALL_REASON_MAX = 2000;

const wallsPath = (matterId: string) =>
  `/api/matters/${encodeURIComponent(matterId)}/access/walls`;

export async function listMatterEthicalWalls(
  signal?: AbortSignal,
  params?: { q?: string; matterId?: string },
): Promise<MatterEthicalWallDirectory> {
  // `q` and `matterId` narrow on the server: the unfiltered directory stops
  // at the 500 most recent walls, so older walls are only reachable this way.
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.matterId) qs.set("matter_id", params.matterId);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return matterEthicalWallDirectorySchema.parse(
    await apiRequest(`/api/matters/ethical-walls${suffix}`, { signal }),
  );
}

export async function createMatterEthicalWall(input: {
  matterId: string;
  excludedMembershipId: string;
  reason: string | null;
}): Promise<MatterEthicalWall> {
  return matterEthicalWallSchema.parse(
    await apiRequest(wallsPath(input.matterId), {
      method: "POST",
      body: { excluded_membership_id: input.excludedMembershipId, reason: input.reason },
    }),
  );
}

export async function removeMatterEthicalWall(input: { matterId: string; wallId: string }): Promise<void> {
  await apiRequest<void>(`${wallsPath(input.matterId)}/${encodeURIComponent(input.wallId)}`, {
    method: "DELETE",
  });
}
