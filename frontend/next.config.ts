import type { NextConfig } from "next";
import { API_ORIGIN } from "./src/lib/api/origin";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  devIndicators: false, // the floating badge covered the sidebar's athlete chip
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // Same-origin proxy for normal API calls. Large uploads bypass it (see import-view.tsx):
  // the dev proxy drops multi-MB request bodies.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
