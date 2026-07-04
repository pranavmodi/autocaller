/** @type {import('next').NextConfig} */
const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8099";

const nextConfig = {
  reactStrictMode: true,
  // Don't 308-redirect `/emailtag/pif-info/` -> `/emailtag/pif-info`. That
  // redirect strips the trailing slash before the rewrite runs, so the proxied
  // request hits emailtag's `/pif-info` which FastAPI 307-redirects to
  // `/pif-info/` cross-origin — dropping the SameSite=Lax pifstats cookie and
  // 401ing. Keeping the slash lets the proxy reach `/pif-info/` directly.
  skipTrailingSlashRedirect: true,
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
      // The firm-list endpoint lives at emailtag `/pif-info/` (trailing slash);
      // FastAPI 307-redirects the no-slash form cross-origin, which drops the
      // SameSite=Lax cookie. Map the exact list path to the slash form so the
      // proxied request reaches emailtag directly. Must precede the catch-all.
      {
        source: "/emailtag/pif-info",
        destination: `${process.env.EMAILTAG_API_URL || "https://emailprocessing.mediflow360.com/api/v1"}/pif-info/`,
      },
      {
        source: "/emailtag/:path*",
        destination: `${process.env.EMAILTAG_API_URL || "https://emailprocessing.mediflow360.com/api/v1"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
