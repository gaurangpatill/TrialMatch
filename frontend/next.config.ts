import type {NextConfig} from "next";

const backend = process.env.TRIALMATCH_API_BASE_URL?.replace(/\/+$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    if (!backend) return [];
    return [
      {source: "/api/geo", destination: `${backend}/api/geo`},
      {source: "/api/optimize", destination: `${backend}/api/optimize`},
    ];
  },
};

export default nextConfig;
