import { apiBaseUrl } from "@/shared/api/client";

function normalizeAssetPath(pathname: string) {
  const normalized = pathname.startsWith("/") ? pathname : `/${pathname}`;
  if (normalized.startsWith("/assets/")) {
    return normalized;
  }
  if (normalized.startsWith("/uploads/")) {
    return `/assets${normalized}`;
  }
  return normalized;
}

export function resolvePublicAssetUrl(url?: string | null) {
  if (!url) {
    return null;
  }

  const base = apiBaseUrl();

  try {
    if (/^(\/?assets\/|\/?uploads\/)/i.test(url)) {
      const apiUrl = new URL(base);
      return new URL(normalizeAssetPath(url), `${apiUrl.origin}/`).toString();
    }

    const parsed = new URL(url, `${base}/`);
    if (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost") {
      const apiUrl = new URL(base);
      parsed.protocol = apiUrl.protocol;
      parsed.hostname = apiUrl.hostname;
      parsed.port = apiUrl.port;
    }
    return parsed.toString();
  } catch {
    return url;
  }
}
