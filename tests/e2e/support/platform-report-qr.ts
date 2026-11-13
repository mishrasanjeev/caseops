import { expect, type Page } from "@playwright/test";
import jsQR from "jsqr";

export const AUTHENTICATOR_QR_LABEL = "Authenticator setup QR code";

export async function renderedTotpSecret(page: Page,
  enrollment: { secret: string; otpauth_url: string }, account: string): Promise<string> {
  const qr = page.getByRole("img", { name: AUTHENTICATOR_QR_LABEL, exact: true });
  await expect(qr).toBeVisible();
  const pixels = await qr.evaluate(async element => {
    if (!(element instanceof SVGSVGElement) || element.querySelector("image, use, foreignObject, script, style")) {
      throw new Error("Expected a self-contained authenticator SVG.");
    }
    const source = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(element)], { type: "image/svg+xml" }));
    try {
      const image = new Image();
      image.src = source;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = 256; canvas.height = 256;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Authenticator pixel canvas unavailable.");
      context.fillStyle = "white"; context.fillRect(0, 0, 256, 256);
      context.drawImage(image, 0, 0, 256, 256);
      return Array.from(context.getImageData(0, 0, 256, 256).data);
    } finally { URL.revokeObjectURL(source); }
  });
  // Decode only rasterized pixels; never read a DOM otpauth value or retain media.
  const decoded = jsQR(Uint8ClampedArray.from(pixels), 256, 256)?.data;
  expect(Boolean(decoded && decoded === enrollment.otpauth_url),
    "Rendered QR must decode to the exact canonical enrollment URL; private values omitted.").toBe(true);
  let url: URL;
  try { url = new URL(decoded!); } catch { throw new Error("Invalid authenticator QR URL; private value omitted."); }
  const parameters = url.searchParams;
  expect(url.protocol === "otpauth:" && url.hostname === "totp" && !url.username && !url.password && !url.port && !url.hash,
    "Authenticator QR must use the canonical TOTP scheme.").toBe(true);
  let label: string;
  try { label = decodeURIComponent(url.pathname.slice(1)); } catch { throw new Error("Invalid authenticator account label."); }
  expect(label === `CaseOps Reports:${account}`, "Authenticator issuer/account must match the actual console identity.").toBe(true);
  expect([...parameters.keys()].sort()).toEqual(["algorithm", "digits", "issuer", "period", "secret"]);
  expect(parameters.get("issuer")).toBe("CaseOps Reports");
  expect(parameters.get("algorithm")).toBe("SHA1");
  expect(parameters.get("digits")).toBe("6");
  expect(parameters.get("period")).toBe("30");
  const secret = parameters.get("secret");
  expect(Boolean(secret && /^[A-Z2-7]+$/.test(secret) && secret === enrollment.secret),
    "Decoded QR secret must match the canonical enrollment secret; private values omitted.").toBe(true);
  return secret!;
}
