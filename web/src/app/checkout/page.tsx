import { Suspense } from "react";
import { CheckoutClient } from "./CheckoutClient";

export default function CheckoutPage() {
  return (
    <Suspense fallback={<div className="container page loader">Готовим оформление</div>}>
      <CheckoutClient />
    </Suspense>
  );
}
