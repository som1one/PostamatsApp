import type { Metadata } from "next";
import { FAQClient } from "./FAQClient";

export const metadata: Metadata = {
  title: "Вопросы и ответы про аренду через постаматы — naprokatberu",
  description:
    "Ответы на частые вопросы про аренду и прокат техники и вещей через постаматы: как оформить заказ, забрать товар, вернуть и оплатить без залога.",
  alternates: { canonical: "/faq" },
  openGraph: {
    url: "/faq",
    title: "Вопросы и ответы про аренду через постаматы — naprokatberu",
    description:
      "Как взять технику и вещи напрокат через постаматы без залога: оформление, оплата, получение, возврат и поддержка.",
  },
};

export default function FAQPage() {
  return <FAQClient />;
}
