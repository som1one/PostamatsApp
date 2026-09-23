import type { Metadata } from "next";
import { ConsentClient } from "./ConsentClient";

export const metadata: Metadata = {
  title: "Согласие на обработку персональных данных",
  description:
    "Согласие пользователя naprokatberu на обработку персональных данных: состав данных, цели, срок действия и порядок отзыва.",
  alternates: { canonical: "/consent" },
  openGraph: {
    url: "/consent",
    title: "Согласие на обработку персональных данных — naprokatberu",
    description: "Какие данные и для чего обрабатывает naprokatberu с согласия пользователя.",
  },
};

export default function ConsentPage() {
  return <ConsentClient />;
}
