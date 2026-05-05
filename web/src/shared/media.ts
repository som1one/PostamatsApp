export function resolvePublicAssetUrl(url?: string | null) {
  if (!url || typeof window === "undefined") {
    return url ?? null;
  }

  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost") {
      parsed.protocol = window.location.protocol;
      parsed.hostname = window.location.hostname;
    }
    return parsed.toString();
  } catch {
    return url;
  }
}
