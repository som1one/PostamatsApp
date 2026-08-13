import type { Metadata } from "next";
import { PrivacyClient } from "./PrivacyClient";

export const metadata: Metadata = {
  title: "Политика конфиденциальности",
  description:
    "Политика конфиденциальности naprokatberu: состав и цели обработки персональных данных, права пользователей, порядок отзыва согласия.",
  alternates: { canonical: "/privacy" },
  openGraph: {
    url: "/privacy",
    title: "Политика конфиденциальности — naprokatberu",
    description:
      "Как naprokatberu обрабатывает и защищает персональные данные пользователей сервиса аренды.",
  },
};

export default function PrivacyPage() {
  return <PrivacyClient />;
}
