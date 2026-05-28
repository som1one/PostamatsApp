/**
 * Общая SEO-конфигурация сайта: базовый URL, имя бренда, города,
 * ключевые запросы и JSON-LD.
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
  legalName: "ИП Кириллов Виталий Валерьевич",
  inn: "532120829653",
  ogrnip: "318532100005699",
  url: SITE_URL,
  logoPath: "/naprokatberu-logo.png",
  supportEmail: "info@naprokatberu.ru",
  description:
    "Naprokatberu — сервис аренды техники без залога, быстро и удобно: пылесосы, PS5, пароочистители и инструменты.",
  shortTagline:
    "Аренда и прокат любых вещей и техники через постоматы. Сервис аренды вещей",
  countryCode: "RU",
  defaultCurrency: "RUB",
} as const;

/**
 * Города, в которых физически работают постаматы. Каждый город — это
 * самостоятельный SEO-лендинг (`/city/<slug>`) и отдельная сущность в
 * `LocalBusiness` JSON-LD.
 *
 * Адреса соответствуют реально активным постаматам из миграции
 * `scripts/migrate_lockers_to_real.py`.
 */
export const CITY_LANDINGS = [
  {
    slug: "velikiy-novgorod",
    citySlug: "velikiy-novgorod",
    name: "Великий Новгород",
    nameLocative: "в Великом Новгороде",
    nameGenitive: "Великого Новгорода",
    region: "Новгородская область",
    description:
      "Аренда техники и вещей в Великом Новгороде через постаматы naprokatberu без залога. PS5, проекторы, дрели, перфораторы, пылесосы, пароочистители и отпариватели — получение и возврат рядом с домом.",
    address: {
      street: "Большая Санкт-Петербургская ул., 39",
      locality: "Великий Новгород",
      region: "Новгородская область",
      postalCode: "173000",
      country: "RU",
    },
    geo: { latitude: 58.533147, longitude: 31.269947 },
  },
  {
    slug: "sankt-peterburg",
    citySlug: "spb",
    name: "Санкт-Петербург",
    nameLocative: "в Санкт-Петербурге",
    nameGenitive: "Санкт-Петербурга",
    region: "Санкт-Петербург",
    description:
      "Аренда техники и вещей в Санкт-Петербурге через постаматы naprokatberu без залога. Скоро откроем точки в центре и на окраинах: PS5, проекторы, дрели, перфораторы, пылесосы и пароочистители рядом с домом.",
    address: {
      street: "Невский пр., 114",
      locality: "Санкт-Петербург",
      region: "Санкт-Петербург",
      postalCode: "191025",
      country: "RU",
    },
    geo: { latitude: 59.931258, longitude: 30.353944 },
  },
] as const;

export type CityLanding = (typeof CITY_LANDINGS)[number];

export function getCityLandingBySlug(slug: string): CityLanding | undefined {
  return CITY_LANDINGS.find((city) => city.slug === slug);
}

/**
 * Базовые ключевые запросы — используются на главной, в каталоге и
 * как заготовка для динамических страниц.
 */
export const COMMON_RENTAL_KEYWORDS: readonly string[] = [
  "аренда техники",
  "прокат техники",
  "аренда вещей",
  "прокат вещей",
  "взять напрокат",
  "аренда без залога",
  "прокат без залога",
  "аренда через постамат",
  "прокат через постамат",
  "аренда проектора",
  "аренда PS5",
  "прокат игровой приставки",
  "аренда пылесоса",
  "аренда пароочистителя",
  "аренда отпаривателя",
  "аренда дрели",
  "аренда перфоратора",
  "аренда инструмента",
  "naprokatberu",
];

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
 * JSON-LD для главной страницы: Organization + WebSite с SearchAction +
 * филиалы (LocalBusiness) для каждого города. Это даёт Яндексу/Google
 * сайтлинки, встроенный поиск и геопривязку — критично для локального
 * органического трафика.
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
        taxID: SITE_CONFIG.inn,
        identifier: [
          { "@type": "PropertyValue", propertyID: "ИНН", value: SITE_CONFIG.inn },
          { "@type": "PropertyValue", propertyID: "ОГРНИП", value: SITE_CONFIG.ogrnip },
        ],
        areaServed: CITY_LANDINGS.map((city) => ({
          "@type": "City",
          name: city.name,
        })),
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
      ...CITY_LANDINGS.map((city) => ({
        "@type": "LocalBusiness",
        "@id": `${SITE_CONFIG.url}/city/${city.slug}#business`,
        parentOrganization: { "@id": `${SITE_CONFIG.url}/#organization` },
        name: `${SITE_CONFIG.name} — аренда ${city.nameLocative}`,
        url: `${SITE_CONFIG.url}/city/${city.slug}`,
        description: city.description,
        image: absoluteUrl(SITE_CONFIG.logoPath),
        priceRange: "₽",
        address: {
          "@type": "PostalAddress",
          streetAddress: city.address.street,
          addressLocality: city.address.locality,
          addressRegion: city.address.region,
          postalCode: city.address.postalCode,
          addressCountry: city.address.country,
        },
        geo: {
          "@type": "GeoCoordinates",
          latitude: city.geo.latitude,
          longitude: city.geo.longitude,
        },
        areaServed: { "@type": "City", name: city.name },
      })),
    ],
  };
}

/**
 * BreadcrumbList JSON-LD для произвольной цепочки. Помогает Яндексу
 * показывать «хлебные крошки» в сниппете вместо сырого URL.
 */
export function breadcrumbJsonLd(
  items: Array<{ name: string; url: string }>,
) {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: absoluteUrl(item.url),
    })),
  };
}

/**
 * Product JSON-LD под schema.org/Offer. Нужен для богатых сниппетов
 * товара в выдаче с ценой и наличием.
 */
export function productJsonLd(input: {
  name: string;
  description?: string | null;
  brand?: string | null;
  url: string;
  imageUrl?: string | null;
  priceMinor: number;
  currency?: string;
  available?: boolean;
}) {
  const currency = (input.currency || SITE_CONFIG.defaultCurrency).toUpperCase();
  const priceMajor = (input.priceMinor / 100).toFixed(2);
  const availability = input.available
    ? "https://schema.org/InStock"
    : "https://schema.org/OutOfStock";

  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: input.name,
    description: input.description || undefined,
    brand: input.brand
      ? { "@type": "Brand", name: input.brand }
      : undefined,
    image: input.imageUrl ? absoluteUrl(input.imageUrl) : undefined,
    url: absoluteUrl(input.url),
    offers: {
      "@type": "Offer",
      url: absoluteUrl(input.url),
      priceCurrency: currency,
      price: priceMajor,
      priceSpecification: {
        "@type": "UnitPriceSpecification",
        price: priceMajor,
        priceCurrency: currency,
        unitText: "DAY",
        referenceQuantity: {
          "@type": "QuantitativeValue",
          value: 1,
          unitCode: "DAY",
        },
      },
      availability,
      seller: { "@id": `${SITE_CONFIG.url}/#organization` },
    },
  };
}
