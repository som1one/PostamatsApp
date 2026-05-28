import type { Metadata } from "next";
import { HomeClient } from "./HomeClient";

export const metadata: Metadata = {
  title:
    "Аренда и прокат любых вещей и техники через постоматы. Сервис аренды вещей",
  description:
    "Naprokatberu — сервис аренды техники без залога, быстро и удобно: пылесосы, PS5, пароочистители и инструменты.",
  alternates: { canonical: "/" },
  openGraph: {
    url: "/",
    title:
      "Аренда и прокат любых вещей и техники через постоматы. Сервис аренды вещей",
    description:
      "Naprokatberu — сервис аренды техники без залога, быстро и удобно: пылесосы, PS5, пароочистители и инструменты.",
  },
};

export default function HomePage() {
  return <HomeClient />;
}
