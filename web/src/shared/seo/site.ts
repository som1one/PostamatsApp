/**
 * Общая SEO-конфигурация сайта: базовый URL, имя бренда и JSON-LD.
 *
 * Базовый URL берётся из `NEXT_PUBLIC_SITE_URL` (production), иначе
 * fallback на `https://naprokatberu.ru`. Это нужно, чтобы Next.js
 * корректно строил абсолютные ссылки в openGraph/twitter/canonical.
 */
const RAW_SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.trim() || "https://naprokatberu.ru";

const SITE_URL = RAW_SITE_URL.replace(/\/+$/, "");

export const SITE_CONFIG = {
  name: "naprokatberu",
  legalName: "naprokatberu",
  url: SITE_URL,
  logoPath: "/naprokatberu-logo.png",
  supportEmail: "info@naprokatberu.ru",
  description:
    "naprokatberu — сервис аренды техники и вещей через постаматы. Возьмите напрокат проекторы, PS5, дрели, перфораторы, пылесосы, пароочистители и отпариватели без залога: получение и возврат рядом с домом.",
  shortTagline:
    "Аренда и прокат техники и вещей через постаматы без залога",
} as const;

export function absoluteUrl(path = "/") {
  if (!path) {
    return SITE_CONFIG.url;
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${SITE_CONFIG.url}${normalized}`;
}

/**
 * JSON-LD для главной страницы: Organization + WebSite с SearchAction,
 * чтобы Яндекс/Google могли показывать сайтлинки и встроенный поиск.
 */
export function siteJsonLd() {
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        "@id": `${SITE_CONFIG.url}/#organization`,
        name: SITE_CONFIG.name,
        legalName: SITE_CONFIG.legalName,
        url: SITE_CONFIG.url,
        logo: absoluteUrl(SITE_CONFIG.logoPath),
        email: SITE_CONFIG.supportEmail,
        description: SITE_CONFIG.description,
      },
      {
        "@type": "WebSite",
        "@id": `${SITE_CONFIG.url}/#website`,
        url: SITE_CONFIG.url,
        name: SITE_CONFIG.name,
        description: SITE_CONFIG.description,
        inLanguage: "ru-RU",
        publisher: { "@id": `${SITE_CONFIG.url}/#organization` },
        potentialAction: {
          "@type": "SearchAction",
          target: {
            "@type": "EntryPoint",
            urlTemplate: `${SITE_CONFIG.url}/catalog?query={search_term_string}`,
          },
          "query-input": "required name=search_term_string",
        },
      },
    ],
  };
}
