import type { Metadata } from "next";
import { HomeClient } from "./HomeClient";

export const metadata: Metadata = {
  title:
    "Аренда и прокат техники и вещей через постаматы без залога",
  description:
    "naprokatberu — берите технику и вещи напрокат рядом с домом. Аренда проекторов, PS5, дрелей, перфораторов, пылесосов, пароочистителей и отпаривателей через постаматы без залога.",
  alternates: { canonical: "/" },
  openGraph: {
    url: "/",
    title:
      "Аренда и прокат техники и вещей через постаматы без залога — naprokatberu",
    description:
      "Берите технику и вещи напрокат рядом с домом. Получение и возврат через постаматы без залога: проекторы, PS5, инструменты, пылесосы и пароочистители.",
  },
};

export default function HomePage() {
  return <HomeClient />;
}
