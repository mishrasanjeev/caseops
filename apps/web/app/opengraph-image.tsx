import { ImageResponse } from "next/og";

import { siteConfig } from "@/lib/site";

export const runtime = "edge";
export const alt = `${siteConfig.name} — ${siteConfig.tagline}`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          background:
            "radial-gradient(1000px 600px at 80% 0%, #dbe4ff 0%, transparent 60%), linear-gradient(180deg, #fbfbfc 0%, #f5f6f8 100%)",
          color: "#0b1220",
          fontFamily: "Inter, system-ui, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 14,
              background: "#0b1220",
              color: "white",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: -0.5,
            }}
          >
            C
          </div>
          <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: -0.5 }}>
            {siteConfig.name}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <div
            style={{
              fontSize: 72,
              fontWeight: 600,
              letterSpacing: -2,
              lineHeight: 1.05,
              maxWidth: 1000,
            }}
          >
            The operating system for legal work.
          </div>
          <div
            style={{
              fontSize: 28,
              color: "#5b6676",
              lineHeight: 1.35,
              maxWidth: 980,
            }}
          >
            Matters, research, drafting, hearings, contracts, recommendations, and billing —
            on one citation-grounded workspace.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: 20,
            color: "#7a8594",
          }}
        >
          <div>India-first legal OS</div>
          <div>caseops.ai</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
