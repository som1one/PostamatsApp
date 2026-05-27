import type { Metadata } from "next";
import { TermsRentalClient } from "./TermsRentalClient";

export const metadata: Metadata = {
  title: "Условия аренды товаров — naprokatberu",
  description:
    "Условия аренды техники и вещей через постаматы naprokatberu. Договор публичной оферты.",
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
