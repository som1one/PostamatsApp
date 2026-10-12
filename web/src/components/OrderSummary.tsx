import Link from "next/link";
import { LockKeyhole, MapPinned, PackageCheck } from "lucide-react";
import type { PricingQuote, ProductDetail } from "@/shared/api/types";
import { formatDate, formatMoney } from "@/shared/format";

export function OrderSummary({
  product,
  lockerName,
  lockerAddress,
  lockerStatus,
  durationLabel,
  pricing,
  estimatedTotal,
  currency,
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
  /** Срок аренды текстом: имя готового тарифа либо «9 дней». */
  durationLabel?: string;
  pricing?: PricingQuote | null;
  /** Оценка суммы на выбранный срок, пока не пришёл `pricing` с бэка. */
  estimatedTotal?: number | null;
  currency?: string;
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
  const moneyCurrency = pricing?.currency ?? currency;
  // Предавторизация сейчас равна сумме аренды, поэтому до ответа бэка
  // показываем ту же оценку, а не «0 ₽».
  const preauthAmount = pricing?.preauthAmount ?? estimatedTotal;

  return (
    <aside className={`surface order-summary ${isCompact ? "order-summary-compact" : "sticky-panel"}`}>
      <div className={`summary-header ${isCompact ? "summary-header-compact" : ""}`}>
        <div className="summary-header-main">
          <p className="eyebrow">Итог</p>
          <h2 className="summary-total">
            {formatMoney(pricing?.totalAmount ?? estimatedTotal, moneyCurrency)}
          </h2>
        </div>
        {isCompact ? (
          <p className="muted small summary-preauth">
            Предавторизация: {formatMoney(preauthAmount, moneyCurrency)}
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
          <strong>{durationLabel || "Не выбран"}</strong>
        </div>
        <div className="summary-line summary-line-start">
          <span className="muted">Дата получения</span>
          <strong>{startDateTime ? formatDate(startDateTime) : "Не выбрана"}</strong>
        </div>
        {!isCompact ? (
          <div className="summary-line summary-line-preauth">
            <span className="muted">Предавторизация</span>
            <strong>{formatMoney(preauthAmount, moneyCurrency)}</strong>
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
