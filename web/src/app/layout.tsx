import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AppProviders } from "./providers";
import { SITE_CONFIG, siteJsonLd } from "@/shared/seo/site";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_CONFIG.url),
  title: {
    default:
      "naprokatberu — аренда и прокат техники и вещей через постаматы без залога",
    template: "%s — naprokatberu",
  },
  description:
    "naprokatberu — сервис аренды техники и вещей через постаматы. Возьмите напрокат проекторы, PS5, дрели, перфораторы, пылесосы, пароочистители и отпариватели без залога: получение и возврат рядом с домом.",
  applicationName: SITE_CONFIG.name,
  keywords: [
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
  ],
  authors: [{ name: SITE_CONFIG.name, url: SITE_CONFIG.url }],
  creator: SITE_CONFIG.name,
  publisher: SITE_CONFIG.name,
  category: "rental",
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "ru_RU",
    url: SITE_CONFIG.url,
    siteName: SITE_CONFIG.name,
    title:
      "naprokatberu — аренда и прокат техники и вещей через постаматы без залога",
    description:
      "Возьмите технику и вещи напрокат без залога. Получение и возврат через постаматы рядом с домом: проекторы, PS5, дрели, пылесосы, пароочистители и отпариватели.",
    images: [
      {
        url: "/hero-rental-promo.png",
        width: 1054,
        height: 1492,
        alt: "naprokatberu — аренда техники и вещей через постаматы",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title:
      "naprokatberu — аренда и прокат техники и вещей через постаматы без залога",
    description:
      "Аренда техники и вещей через постаматы без залога: проекторы, PS5, дрели, пылесосы, пароочистители и отпариватели рядом с домом.",
    images: ["/hero-rental-promo.png"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-snippet": -1,
      "max-image-preview": "large",
      "max-video-preview": -1,
    },
  },
  icons: {
    icon: "/naprokatberu-logo.png",
    apple: "/naprokatberu-logo.png",
  },
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#eef5fb",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(siteJsonLd()) }}
        />
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
