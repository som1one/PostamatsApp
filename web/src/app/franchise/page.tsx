import type { Metadata } from "next";
import { FranchiseClient } from "./FranchiseClient";

export const metadata: Metadata = {
  title: "Франшиза naprokatberu — бизнес на аренде вещей через постаматы",
  description:
    "Откройте точку аренды вещей и техники через постаматы naprokatberu без персонала. Прозрачная финансовая модель, оборудование российского производства, поддержка на каждом шаге запуска.",
  alternates: { canonical: "/franchise" },
  openGraph: {
    url: "/franchise",
    title: "Франшиза naprokatberu — бизнес на аренде вещей через постаматы",
    description:
      "Постаматы с товарами в аренду как готовый бизнес: низкий порог входа, выручка без персонала, поддержка запуска под ключ.",
  },
};

export default function FranchisePage() {
  return <FranchiseClient />;
}
