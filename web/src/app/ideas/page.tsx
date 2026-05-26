import type { Metadata } from "next";
import { IdeasClient } from "./IdeasClient";

export const metadata: Metadata = {
  title: "Идеи аренды — что взять напрокат для дома, ремонта и отдыха",
  description:
    "Идеи и подборки для аренды техники и вещей: что взять напрокат для ремонта, уборки, путешествия, киновечера и игр. Прокат через постаматы без залога.",
  alternates: { canonical: "/ideas" },
  openGraph: {
    url: "/ideas",
    title: "Идеи аренды — что взять напрокат для дома, ремонта и отдыха",
    description:
      "Готовые идеи и подборки: что взять в аренду для ремонта, уборки, поездки, киновечера и игр. Получение через постаматы без залога.",
  },
};

export default function IdeasPage() {
  return <IdeasClient />;
}
