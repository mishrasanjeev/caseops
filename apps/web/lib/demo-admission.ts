import { z } from "zod";

export const demoSources = ["demo", "pricing_page", "homepage", "solo_lawyers", "law_firms", "general_counsels", "guide", "resource"] as const;
export type DemoSource = typeof demoSources[number];
export type DemoSegment = "solo" | "firm" | "gc";
export const demoRoles = [
  ["solo_advocate", "Solo advocate"], ["partner", "Partner / head of litigation"],
  ["associate", "Associate"], ["general_counsel", "General counsel"],
  ["legal_ops", "Legal operations"], ["other", "Other"],
] as const;

export const demoAdmissionSchema = z.object({
  contact_name: z.string().trim().min(2).max(255),
  contact_email: z.string().trim().email().max(320),
  company_name: z.string().trim().max(255).nullable().optional(),
  segment: z.enum(["solo", "firm", "gc"]),
  role: z.enum(["solo_advocate", "partner", "associate", "general_counsel", "legal_ops", "other"]),
  intent: z.enum(["demo", "pilot", "pricing"]),
  source: z.enum(demoSources),
  selected_plan: z.string().max(80).nullable().optional(),
  notes: z.string().trim().max(1000).nullable().optional(),
  idempotency_key: z.string().uuid(),
  privacy_notice_version: z.literal("2026-10-09"),
}).strict();
