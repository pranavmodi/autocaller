/** @type {import('next').NextConfig} */
const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8099";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/audio/:path*",
        destination: `${backendUrl}/audio/:path*`,
      },
    ];
  },
};

export default nextConfig;
