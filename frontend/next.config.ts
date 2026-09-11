import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Cloud Run deployment (Phase 6) - a minimal, self-contained server
  // bundle instead of requiring the full node_modules tree in the image.
  output: "standalone",
};

export default nextConfig;
