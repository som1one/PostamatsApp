import type { Metadata } from "next";
import { LockersClient } from "./LockersClient";

export const metadata: Metadata = {
  title: "Постаматы для аренды и проката — карта точек выдачи naprokatberu",
  description:
    "Карта постаматов naprokatberu для аренды и проката техники и вещей. Выберите удобную точку выдачи и возврата рядом с домом — без залога и очередей.",
  alternates: { canonical: "/lockers" },
  openGraph: {
    url: "/lockers",
    title: "Постаматы для аренды и проката — карта точек выдачи naprokatberu",
    description:
      "Карта постаматов для получения и возврата арендуемой техники и вещей без залога рядом с домом.",
  },
};

export default function LockersPage() {
  return <LockersClient />;
}
