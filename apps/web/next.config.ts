import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Sprint 6 BG-017: /legacy is removed. Existing bookmarks and any
  // stray external links resolve into the new app shell instead of
  // 404ing. Permanent (308) so the browser updates its cache.
  async redirects() {
    return [
      {
        source: "/legacy",
        destination: "/app",
        permanent: true,
      },
      {
        source: "/legacy/:path*",
        destination: "/app",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
