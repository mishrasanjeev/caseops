/**
 * ENH-001: firm branding printed on billing PDFs, and the public lookup behind
 * the verification QR code on each PDF.
 */
import { apiBlobDataRequest, apiRequest } from "./client";
import type { components } from "./openapi-types";

export type DocumentBranding = components["schemas"]["DocumentBrandingRecord"];
export type DocumentBrandingUpdate = components["schemas"]["DocumentBrandingUpdateRequest"];
export type BillingDocumentVerification =
  components["schemas"]["BillingDocumentVerificationResponse"];
export type BrandingImageKind = "logo" | "signature";

/** Mirrors the server: PNG or JPEG, at most 2 MB. SVG is refused (scripts). */
export const BRANDING_IMAGE_ACCEPT = "image/png,image/jpeg";
export const BRANDING_IMAGE_MAX_BYTES = 2 * 1024 * 1024;
export const BRANDING_TEXT_LIMITS = {
  signatory_name: 160,
  signatory_designation: 160,
  watermark_text: 60,
} as const;

const BASE = "/api/admin/document-branding";

export function fetchDocumentBranding(): Promise<DocumentBranding> {
  return apiRequest<DocumentBranding>(BASE);
}

export function updateDocumentBranding(body: DocumentBrandingUpdate): Promise<DocumentBranding> {
  return apiRequest<DocumentBranding>(BASE, { method: "PATCH", body });
}

export function uploadBrandingImage(kind: BrandingImageKind, file: File): Promise<DocumentBranding> {
  const body = new FormData();
  body.append("file", file);
  return apiRequest<DocumentBranding>(`${BASE}/${kind}`, { method: "PUT", body });
}

export function removeBrandingImage(kind: BrandingImageKind): Promise<DocumentBranding> {
  return apiRequest<DocumentBranding>(`${BASE}/${kind}`, { method: "DELETE" });
}

export async function fetchBrandingImage(kind: BrandingImageKind): Promise<Blob> {
  const { blob } = await apiBlobDataRequest(`${BASE}/${kind}`, { maxBytes: 4 * 1024 * 1024 });
  return blob;
}

/** A client-side check of a file chosen from disk; refuses before any upload. */
export function brandingImageProblem(file: File): string | null {
  const name = file.name.toLowerCase();
  if (name.endsWith(".svg") || file.type === "image/svg+xml") {
    return "SVG files are not accepted because they can carry scripts. Use a PNG or JPEG.";
  }
  if (!["image/png", "image/jpeg"].includes(file.type) && !/\.(png|jpe?g)$/.test(name)) {
    return "Use a PNG or JPEG file.";
  }
  if (file.size > BRANDING_IMAGE_MAX_BYTES) return "The image must be 2 MB or smaller.";
  return null;
}

const TOKEN = /^[A-Za-z0-9_-]{43}$/;

export function isVerificationToken(token: string): boolean {
  return TOKEN.test(token);
}

export function fetchBillingDocumentVerification(
  token: string,
): Promise<BillingDocumentVerification> {
  return apiRequest<BillingDocumentVerification>(
    `/api/verify/billing-documents/${encodeURIComponent(token)}`,
  );
}

/** SHA-256 of a local file, computed in the browser; the file is never uploaded. */
export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
