// Declaration-only re-exports for the auth surface.
//
// `import type` statements are erased at compile time and emit zero
// JS. This module lets the sign-in bundle reference the auth shapes
// without pulling in `./schemas.ts` (60 zod schemas + zod runtime,
// ~35 kB min+gz).
//
// Authenticated routes keep importing from `./schemas` as before —
// they need the runtime validators for defence-in-depth against a
// backend contract drift.
export type {
  AuthContext,
  AuthSession,
  CompanySummary,
  MembershipSummary,
  UserSummary,
} from "./schemas";
