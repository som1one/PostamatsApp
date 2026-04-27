import { Suspense } from "react";
import { CatalogClient } from "./CatalogClient";

export default function CatalogPage() {
  return (
    <Suspense fallback={<div className="container page loader">Загружаем каталог</div>}>
      <CatalogClient />
    </Suspense>
  );
}
