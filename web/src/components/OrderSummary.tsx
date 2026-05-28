import Link from "next/link";
import { LockKeyhole, MapPinned, PackageCheck } from "lucide-react";
import type { PricePlan, PricingQuote, ProductDetail } from "@/shared/api/types";
import { formatDate, formatMoney } from "@/shared/format";

export function OrderSummary({
  product,
  lockerName,
  lockerAddress,
  lockerStatus,
  plan,
  pricing,
  startDateTime,
  canCheckout,
  checkoutHref,
  isAuthed,
  variant = "default",
  showProduct = true,
}: {
  product: ProductDetail;
  lockerName?: string;
  lockerAddress?: string;
  /** Статус выбранного постамата. Если не "online" — рендерим
   * предупреждение и блокируем кнопку «Оформить аренду». */
  lockerStatus?: string | null;
  plan?: PricePlan | null;
  pricing?: PricingQuote | null;
  startDateTime?: string;
  canCheckout: boolean;
  checkoutHref: string;
  isAuthed: boolean;
  variant?: "default" | "compact";
  showProduct?: boolean;
}) {
  const isCompact = variant === "compact";
  const lockerNotBookable = Boolean(
    lockerName && lockerStatus && lockerStatus !== "online",
  );
  const effectiveCanCheckout = canCheckout && !lockerNotBookable;

  return (
    <aside className={`surface order-summary ${isCompact ? "order-summary-compact" : "sticky-panel"}`}>
      <div className={`summary-header ${isCompact ? "summary-header-compact" : ""}`}>
        <div className="summary-header-main">
          <p className="eyebrow">Итог</p>
          <h2 className="summary-total">
            {formatMoney(pricing?.totalAmount ?? plan?.baseAmount, pricing?.currency ?? plan?.currency)}
          </h2>
        </div>
        {isCompact ? (
          <p className="muted small summary-preauth">
            Предавторизация: {formatMoney(pricing?.preauthAmount, pricing?.currency)}
          </p>
        ) : null}
      </div>

      <div className="summary-list">
        {showProduct ? (
          <div className="summary-line summary-line-product">
            <span className="muted">Товар</span>
            <strong>{product.name}</strong>
          </div>
        ) : null}
        <div className="summary-line summary-line-plan">
          <span className="muted">Тариф</span>
          <strong>{plan?.name || "Не выбран"}</strong>
        </div>
        <div className="summary-line summary-line-start">
          <span className="muted">Дата получения</span>
          <strong>{startDateTime ? formatDate(startDateTime) : "Не выбрана"}</strong>
        </div>
        {!isCompact ? (
          <div className="summary-line summary-line-preauth">
            <span className="muted">Предавторизация</span>
            <strong>{formatMoney(pricing?.preauthAmount, pricing?.currency)}</strong>
          </div>
        ) : null}
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

      {lockerNotBookable ? (
        <div className="alert alert-warn">
          Аренда недоступна в этом постамате. Выберите другую точку выдачи.
        </div>
      ) : null}

      {effectiveCanCheckout && isAuthed ? (
        <Link className="button button-primary summary-action" href={checkoutHref}>
          <PackageCheck size={18} />
          Оформить аренду
        </Link>
      ) : effectiveCanCheckout ? (
        isCompact ? (
          <div className="summary-auth-actions">
            <Link className="button button-primary summary-action" href="/login">
              Войти
            </Link>
            <Link className="button button-secondary summary-secondary-action" href="/register">
              Регистрация
            </Link>
          </div>
        ) : (
          <div className="auth-prompt">
            <LockKeyhole size={20} />
            <div>
              <strong>Войдите, чтобы продолжить</strong>
              <span>Мы сохраним выбранный товар, постамат и тариф.</span>
            </div>
            <div className="auth-prompt-actions">
              <Link className="button button-primary summary-action" href="/login">
                Войти
              </Link>
              <Link className="button button-secondary summary-secondary-action" href="/register">
                Зарегистрироваться
              </Link>
            </div>
          </div>
        )
      ) : (
        <a className="button button-primary summary-action" href="#rental-flow">
          <PackageCheck size={18} />
          Выбрать параметры
        </a>
      )}
    </aside>
  );
}
