import type { MetadataRoute } from "next";
import { SITE_CONFIG } from "@/shared/seo/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          "/api/",
          "/auth/",
          "/login",
          "/register",
          "/profile",
          "/profile/",
          "/checkout",
          "/checkout/",
          "/payment/",
          "/verification",
          "/rentals",
        ],
      },
    ],
    sitemap: `${SITE_CONFIG.url}/sitemap.xml`,
    host: SITE_CONFIG.url,
  };
}
