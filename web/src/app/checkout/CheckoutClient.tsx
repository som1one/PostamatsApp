"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { CreditCard, FileCheck2, MapPinned, PackageCheck, ShoppingBag } from "lucide-react";
import { CheckoutSteps } from "@/components/CheckoutSteps";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import {
  createPaymentPreauth,
  createReservation,
  createReservationQuote,
  fetchMe,
  fetchProduct,
  fetchProductPricing,
  fetchReservation,
} from "@/shared/api/endpoints";
import type {
  AppUser,
  PricingQuote,
  ProductDetail,
  ReservationQuote,
  ReservationSummary,
} from "@/shared/api/types";
import { writePendingCheckout } from "@/shared/checkout/pending";
import { formatMoney } from "@/shared/format";

export function CheckoutClient() {
  return (
    <PageChrome>
      <RequireAuth>
        <CheckoutContent />
      </RequireAuth>
    </PageChrome>
  );
}

function CheckoutContent() {
  const params = useSearchParams();
  const router = useRouter();
  const productId = params.get("productId") || "";
  const lockerId = params.get("lockerId") || "";
  const durationType = params.get("durationType") || "day";
  const durationValue = Number(params.get("durationValue") || 1);
  const startAt = params.get("startAt") || "";
  const [user, setUser] = useState<AppUser | null>(null);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [pricing, setPricing] = useState<PricingQuote | null>(null);
  const [quote, setQuote] = useState<ReservationQuote | null>(null);
  const [reservation, setReservation] = useState<ReservationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selectedLocker = useMemo(
    () => product?.availableLockers.find((locker) => locker.lockerId === lockerId),
    [lockerId, product],
  );

  useEffect(() => {
    if (!productId || !lockerId) {
      setLoading(false);
      setError("Не выбран товар или постамат.");
      return;
    }
    let active = true;
    Promise.all([
      fetchMe(),
      fetchProduct(productId),
      fetchProductPricing(productId, lockerId, durationType, durationValue),
    ])
      .then(([me, item, price]) => {
        if (!active) {
          return;
        }
        setUser(me);
        setProduct(item);
        setPricing(price);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Не удалось подготовить бронь");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [durationType, durationValue, lockerId, productId]);

  async function handleQuote() {
    setBusy(true);
    setError("");
    try {
      const next = await createReservationQuote({
        productId,
        lockerId,
        durationType,
        durationValue,
      });
      setQuote(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось рассчитать бронь");
    } finally {
      setBusy(false);
    }
  }

  async function handleReservation() {
    setBusy(true);
    setError("");
    try {
      const created = await createReservation({
        productId,
        lockerId,
        durationType,
        durationValue,
        pickupWindowMinutes: 120,
      });
      const expanded = await fetchReservation(created.id);
      setReservation(expanded);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать бронь");
    } finally {
      setBusy(false);
    }
  }

  async function handlePayment() {
    if (!reservation) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const returnUrl =
        typeof window !== "undefined"
          ? `${window.location.origin}/payment/return`
          : undefined;
      const response = await createPaymentPreauth({
        reservationId: reservation.id,
        returnUrl,
      });
      writePendingCheckout({
        reservationId: reservation.id,
        paymentId: response.payment.id,
        createdAt: new Date().toISOString(),
      });
      if (response.confirmation?.confirmationUrl) {
        window.location.href = response.confirmation.confirmationUrl;
        return;
      }
      router.push("/payment/return");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось начать оплату");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <div className="loader">Готовим бронь</div>;
  }

  if (!productId || !lockerId) {
    return (
      <>
        <PageHeader
          eyebrow="Оформление"
          title="Бронь не собрана"
          subtitle={error || "Откройте товар и выберите постамат перед оформлением."}
        />
        <EmptyState
          icon={<ShoppingBag size={34} />}
          title="Нужен товар и постамат"
          action={
            <Link className="button button-primary" href="/catalog">
              В каталог
            </Link>
          }
        />
      </>
    );
  }

  if (user?.verificationStatus !== "approved") {
    return (
      <>
        <PageHeader
          eyebrow="Бронь"
          title="Нужна верификация"
          subtitle="Бронирование откроется после проверки документов."
          actions={<StatusPill status={user?.verificationStatus} />}
        />
        <Surface className="detail-panel">
          <div className="alert alert-warn">
            <FileCheck2 size={22} />
            <div>
              <strong>Документы ещё не одобрены</strong>
              <span>После проверки профиля вы сможете продолжить оформление с выбранным товаром и тарифом.</span>
            </div>
          </div>
          <Link className="button button-primary" href="/verification">
            Перейти к проверке
          </Link>
        </Surface>
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Оформление"
        title="Бронь"
        subtitle={product?.name || "Товар выбран"}
        actions={<StatusPill status={reservation?.status || "awaiting_payment"} />}
      />

      {error ? <div className="alert alert-danger">{error}</div> : null}

      <div className="checkout-layout">
        <Surface className="detail-panel">
          <CheckoutSteps
            steps={[
              {
                title: "Расчёт",
                text: quote
                  ? `Резерв суммы: ${formatMoney(quote.preauthAmount, quote.currency)}`
                  : "Проверяем стоимость и доступность",
                icon: <PackageCheck size={18} />,
                state: quote ? "complete" : "current",
              },
              {
                title: "Бронь",
                text: reservation
                  ? `Статус: ${reservation.status}`
                  : "Создаём резерв в постамате",
                icon: <MapPinned size={18} />,
                state: reservation ? "complete" : quote ? "current" : "idle",
              },
              {
                title: "Оплата",
                text: "YooKassa откроется после создания брони",
                icon: <CreditCard size={18} />,
                state: reservation ? "current" : "idle",
              },
            ]}
          />

          <div className="meta-list">
            <div className="meta-line">
              <span>Товар</span>
              <strong>{product?.name}</strong>
            </div>
            <div className="meta-line">
              <span>Постамат</span>
              <strong>{selectedLocker?.name || lockerId}</strong>
            </div>
            <div className="meta-line">
              <span>Адрес</span>
              <strong>{selectedLocker?.address || "адрес не найден"}</strong>
            </div>
            <div className="meta-line">
              <span>Срок</span>
              <strong>
                {durationValue} {durationType}
              </strong>
            </div>
            <div className="meta-line">
              <span>Начало</span>
              <strong>{startAt ? new Date(startAt).toLocaleString("ru-RU") : "как можно скорее"}</strong>
            </div>
          </div>
          <div className="alert">
            После подтверждения брони мы закрепим за вами доступный комплект в
            выбранной точке и подготовим его к выдаче.
          </div>
        </Surface>

        <aside className="surface detail-panel sticky-panel">
          <div>
            <p className="eyebrow">Итого</p>
            <h2 className="section-title">{formatMoney(pricing?.totalAmount, pricing?.currency)}</h2>
          </div>
          <div className="summary-list">
            <div className="summary-line">
              <span className="muted">Стоимость</span>
              <strong>{formatMoney(pricing?.totalAmount, pricing?.currency)}</strong>
            </div>
            <div className="summary-line">
              <span className="muted">Предавторизация</span>
              <strong>{formatMoney(pricing?.preauthAmount, pricing?.currency)}</strong>
            </div>
          </div>
          <button
            className="button button-secondary"
            type="button"
            onClick={handleQuote}
            disabled={busy}
          >
            {quote ? "Расчёт обновлён" : "Рассчитать"}
          </button>
          <button
            className="button button-primary"
            type="button"
            onClick={handleReservation}
            disabled={busy || !quote || Boolean(reservation)}
          >
            {reservation ? "Бронь создана" : "Создать бронь"}
          </button>
          <button
            className="button button-dark"
            type="button"
            onClick={handlePayment}
            disabled={busy || !reservation}
          >
            Перейти к оплате
          </button>
        </aside>
      </div>
    </>
  );
}
