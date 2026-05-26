import type { Metadata } from "next";
import { Suspense } from "react";
import { CatalogClient } from "./CatalogClient";

export const metadata: Metadata = {
  title: "Каталог аренды техники и вещей — прокат через постаматы без залога",
  description:
    "Каталог аренды naprokatberu: проекторы, PS5, дрели, перфораторы, пылесосы, пароочистители и отпариватели. Прокат техники и вещей через постаматы без залога — получение и возврат рядом с домом.",
  keywords: [
    "каталог аренды",
    "каталог проката",
    "аренда техники",
    "прокат техники",
    "аренда вещей",
    "прокат без залога",
    "взять напрокат",
    "аренда через постамат",
  ],
  alternates: { canonical: "/catalog" },
  openGraph: {
    url: "/catalog",
    title:
      "Каталог аренды техники и вещей — прокат через постаматы без залога",
    description:
      "Аренда проекторов, PS5, дрелей, пылесосов, пароочистителей и отпаривателей. Получение и возврат через постаматы рядом с домом.",
  },
};

export default function CatalogPage() {
  return (
    <Suspense fallback={<div className="container page loader">Загружаем каталог</div>}>
      <CatalogClient />
    </Suspense>
  );
}
