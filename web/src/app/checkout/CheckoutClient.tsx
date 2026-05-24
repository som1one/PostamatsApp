"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FileCheck2, ShoppingBag } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { Surface } from "@/components/Surface";
import {
  confirmReservation,
  createReservation,
  fetchMe,
  fetchMyReservations,
  fetchProduct,
  fetchProductPricing,
  fetchReservation,
} from "@/shared/api/endpoints";
import { ApiError } from "@/shared/api/client";
import type {
  AppUser,
  PricingQuote,
  ProductDetail,
  ReservationSummary,
} from "@/shared/api/types";
import { formatDate, formatMoney, pluralizeRu } from "@/shared/format";

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
  const sourceReservationId = params.get("reservationId") || "";

  const [user, setUser] = useState<AppUser | null>(null);
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [pricing, setPricing] = useState<PricingQuote | null>(null);
  const [reservation, setReservation] = useState<ReservationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("");
  const [error, setError] = useState("");

  const selectedLocker = useMemo(
    () => product?.availableLockers.find((locker) => locker.lockerId === lockerId),
    [lockerId, product],
  );

  const durationLabel = useMemo(() => {
    const forms =
      durationType === "hour"
        ? (["час", "часа", "часов"] as [string, string, string])
        : (["день", "дня", "дней"] as [string, string, string]);
    return `${durationValue} ${pluralizeRu(durationValue, forms)}`;
  }, [durationType, durationValue]);

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

  async function handleCheckout() {
    if (!pricing) {
      setError("Не удалось загрузить сумму для оплаты.");
      return;
    }

    setBusy(true);
    setBusyLabel("Оформляем аренду");
    setError("");

    try {
      let currentReservation = reservation;

      // startAt из URL — это YYYY-MM-DD из DateTimeSelector. Переводим в
      // ISO-8601 (00:00 локального времени), чтобы backend мог запретить
      // открытие ячейки до этого момента.
      const startAtISO = startAt ? new Date(`${startAt}T00:00:00`).toISOString() : undefined;

      if (!currentReservation) {
        try {
          const created = await createReservation({
            productId,
            lockerId,
            durationType,
            durationValue,
            sourceReservationId: sourceReservationId || undefined,
            startAt: startAtISO,
          });
          currentReservation = await fetchReservation(created.id);
        } catch (err) {
          // У пользователя уже есть активная бронь — переиспользуем её, чтобы
          // не блокировать кнопку "Оплатить" повторным кликом.
          if (err instanceof ApiError && err.code === "ACTIVE_RESERVATION_EXISTS") {
            const existing = await fetchMyReservations();
            const reusable = existing.find((r) =>
              ["created", "awaiting_payment", "payment_authorized"].includes(r.status),
            );
            if (!reusable) {
              throw err;
            }
            currentReservation = await fetchReservation(reusable.id);
          } else {
            throw err;
          }
        }
        setReservation(currentReservation);
      }

      // Юкасса временно отключена: подтверждаем бронь без платежа и сразу
      // переходим в карточку аренды. startAt дублируем, чтобы зафиксировать
      // выбранную дату в Rental.starts_at.
      const rental = await confirmReservation(currentReservation.id, undefined, startAtISO);
      router.push(`/profile/orders/${rental.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "LOCKER_OFFLINE") {
          setError(
            "Постамат сейчас офлайн. Попробуйте чуть позже — в ночные часы устройство может уходить в режим обслуживания.",
          );
        } else if (err.code === "LOCKER_NOT_CONFIGURED") {
          setError("Постамат пока не привязан к серверу. Обратитесь в поддержку.");
        } else if (err.code === "ESI_RESERVE_FAILED" || err.code === "ESI_HTTP_ERROR") {
          setError("Не удалось зарезервировать ячейку. Попробуйте ещё раз через минуту.");
        } else {
          setError(err.message || "Не удалось оформить аренду");
        }
      } else {
        setError(err instanceof Error ? err.message : "Не удалось оформить аренду");
      }
    } finally {
      setBusy(false);
      setBusyLabel("");
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

  if (!user) {
    return (
      <>
        <PageHeader
          eyebrow="Оформление"
          title="Не удалось загрузить профиль"
          subtitle={error || "Обновите страницу и попробуйте еще раз."}
        />
        <Surface className="detail-panel checkout-verify-panel">
          <div className="alert alert-danger checkout-verify-alert">
            <div>
              <strong>Статус аккаунта пока недоступен</strong>
              <span>Мы не смогли проверить профиль, поэтому бронь пока не продолжаем.</span>
            </div>
          </div>
          <button
            className="button button-secondary checkout-primary-button"
            type="button"
            onClick={() => window.location.reload()}
          >
            Обновить страницу
          </button>
        </Surface>
      </>
    );
  }

  if (user.verificationStatus !== "approved") {
    return (
      <>
        <PageHeader
          eyebrow="Бронь"
          title="Подтвердите профиль"
          subtitle="Проверка документов нужна один раз перед первой арендой."
        />
        <Surface className="detail-panel checkout-verify-panel">
          <div className="alert alert-warn checkout-verify-alert">
            <FileCheck2 size={22} />
            <div>
              <strong>Без проверки бронь не выпустить</strong>
              <span>
                Выбранный товар сохранится. После одобрения можно будет сразу вернуться к
                оплате.
              </span>
            </div>
          </div>
          <Link className="button button-primary checkout-primary-button" href="/verification">
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
        title="Подтверждение"
        subtitle={product?.name || "Проверьте детали и переходите к оплате"}
      />

      {error ? <div className="alert alert-danger">{error}</div> : null}

      <div className="checkout-flow">
        <aside className="surface detail-panel checkout-payment-card">
          <div className="checkout-payment-header">
            <p className="eyebrow">К оплате</p>
            <h2 className="section-title">{formatMoney(pricing?.totalAmount, pricing?.currency)}</h2>
            <p className="checkout-caption">
              Предавторизация {formatMoney(pricing?.preauthAmount, pricing?.currency)}. Ячейка на
              этом шаге не откроется.
            </p>
          </div>

          <div className="summary-list">
            <div className="summary-line">
              <span className="muted">Аренда</span>
              <strong>{formatMoney(pricing?.totalAmount, pricing?.currency)}</strong>
            </div>
            <div className="summary-line">
              <span className="muted">Резерв на карте</span>
              <strong>{formatMoney(pricing?.preauthAmount, pricing?.currency)}</strong>
            </div>
          </div>

          <button
            className="button button-primary checkout-primary-button"
            type="button"
            onClick={handleCheckout}
            disabled={busy}
          >
            {busy ? busyLabel || "Подтверждаем" : "Оплатить"}
          </button>
        </aside>

        <Surface className="detail-panel checkout-summary-card">
          <div className="checkout-summary-header">
            <p className="eyebrow">Проверьте детали</p>
            <h2 className="section-title">{product?.name}</h2>
            <p className="checkout-caption">
              Бронь подтвердим автоматически и сразу переведём вас на оплату.
            </p>
          </div>

          <div className="meta-list checkout-meta-list">
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
              <strong>{selectedLocker?.address || "Адрес уточняется"}</strong>
            </div>
            <div className="meta-line">
              <span>Срок</span>
              <strong>{durationLabel}</strong>
            </div>
            <div className="meta-line">
              <span>Дата получения</span>
              <strong>{startAt ? formatDate(startAt) : "Как можно скорее"}</strong>
            </div>
          </div>

          <div className="checkout-note">
            После оплаты мы закрепим комплект за вами в выбранном постамате и подготовим выдачу.
          </div>
        </Surface>
      </div>
    </>
  );
}
