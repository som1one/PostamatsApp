import type { Metadata } from "next";
import { TermsRentalClient } from "./TermsRentalClient";

export const metadata: Metadata = {
  title: "Условия аренды товаров",
  description:
    "Договор публичной оферты naprokatberu: правила получения, использования и возврата оборудования, цена, ответственность сторон и оценка оборудования.",
  alternates: { canonical: "/terms-rental" },
  openGraph: {
    url: "/terms-rental",
    title: "Условия аренды товаров — naprokatberu",
    description: "Договор публичной оферты на аренду техники и вещей.",
  },
};

export default function TermsRentalPage() {
  return <TermsRentalClient />;
}
