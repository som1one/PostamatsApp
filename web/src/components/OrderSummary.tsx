import Link from "next/link";
import { LockKeyhole, MapPinned, PackageCheck } from "lucide-react";
import type { PricePlan, PricingQuote, ProductDetail } from "@/shared/api/types";
import { formatMoney } from "@/shared/format";

export function OrderSummary({
  product,
  lockerName,
  lockerAddress,
  plan,
  pricing,
  startDateTime,
  canCheckout,
  checkoutHref,
  isAuthed,
}: {
  product: ProductDetail;
  lockerName?: string;
  lockerAddress?: string;
  plan?: PricePlan | null;
  pricing?: PricingQuote | null;
  startDateTime?: string;
  canCheckout: boolean;
  checkoutHref: string;
  isAuthed: boolean;
}) {
  return (
    <aside className="surface order-summary sticky-panel">
      <div>
        <p className="eyebrow">Итог</p>
        <h2 className="summary-total">
          {formatMoney(pricing?.totalAmount ?? plan?.baseAmount, pricing?.currency ?? plan?.currency)}
        </h2>
      </div>

      <div className="summary-list">
        <div className="summary-line">
          <span className="muted">Товар</span>
          <strong>{product.name}</strong>
        </div>
        <div className="summary-line">
          <span className="muted">Тариф</span>
          <strong>{plan?.name || "Не выбран"}</strong>
        </div>
        <div className="summary-line">
          <span className="muted">Старт</span>
          <strong>{startDateTime || "Не выбран"}</strong>
        </div>
        <div className="summary-line">
          <span className="muted">Предавторизация</span>
          <strong>{formatMoney(pricing?.preauthAmount, pricing?.currency)}</strong>
        </div>
      </div>

      {lockerName ? (
        <div className="summary-locker">
          <MapPinned size={18} />
          <div>
            <strong>{lockerName}</strong>
            <span>{lockerAddress}</span>
          </div>
        </div>
      ) : (
        <div className="alert alert-warn">Выберите постамат с доступным товаром.</div>
      )}

      {isAuthed ? (
        <Link
          className="button button-primary"
          href={canCheckout ? checkoutHref : "#"}
          aria-disabled={!canCheckout}
          onClick={(event) => {
            if (!canCheckout) {
              event.preventDefault();
            }
          }}
        >
          <PackageCheck size={18} />
          Оформить аренду
        </Link>
      ) : (
        <div className="auth-prompt">
          <LockKeyhole size={20} />
          <div>
            <strong>Войдите, чтобы продолжить</strong>
            <span>Мы сохраним выбранный товар, постамат и тариф.</span>
          </div>
          <div className="auth-prompt-actions">
            <Link className="button button-primary" href="/login">
              Войти
            </Link>
            <Link className="button button-secondary" href="/register">
              Зарегистрироваться
            </Link>
          </div>
        </div>
      )}
    </aside>
  );
}

