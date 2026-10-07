import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  // Crawlers must be able to fetch pages to observe their noindex directive.
  return { rules: { userAgent: "*", allow: "/" } };
}
