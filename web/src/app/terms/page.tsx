import type { Metadata } from "next";
import { TermsClient } from "./TermsClient";

export const metadata: Metadata = {
  title: "Пользовательское соглашение",
  description:
    "Пользовательское соглашение naprokatberu: регистрация, правила использования сайта и постаматов, ответственность сторон.",
  alternates: { canonical: "/terms" },
  openGraph: {
    url: "/terms",
    title: "Пользовательское соглашение — naprokatberu",
    description: "Правила использования платформы аренды вещей naprokatberu.",
  },
};

export default function TermsPage() {
  return <TermsClient />;
}
