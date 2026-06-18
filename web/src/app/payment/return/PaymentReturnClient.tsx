"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeftRight, CreditCard, PackageCheck, RotateCcw, ShoppingBag, Copy } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import {
  authorizePaymentDevStub,
  cancelReservation,
  confirmReservation,
  fetchPayment,
  fetchReservation,
} from "@/shared/api/endpoints";
import type { PaymentSummary, ReservationSummary } from "@/shared/api/types";
import {
  clearPendingCheckout,
  type PendingCheckout,
  readPendingCheckout,
} from "@/shared/checkout/pending";
import { formatDateTime, formatMoney } from "@/shared/format";
import { useAuth } from "@/shared/auth/auth-context";

const DEV_PAYMENT_BYPASS_ENABLED =
  process.env.NEXT_PUBLIC_ENABLE_DEV_PAYMENT_BYPASS === "true";

export function PaymentReturnClient() {
  return (
    <PageChrome>
      <RequireAuth>
        <PaymentReturnContent />
      </RequireAuth>
    </PageChrome>
  );
}

function PaymentReturnContent() {
  const router = useRouter();
  const { session, isReady } = useAuth();
  const [payment, setPayment] = useState<PaymentSummary | null>(null);
  const [reservation, setReservation] = useState<ReservationSummary | null>(null);
  const [rental, setRental] = useState<{
    id: string;
    status: string;
    pickupPin: string;
    plannedEndAt: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [pending, setPending] = useState<PendingCheckout | null | undefined>(undefined);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [pinCopied, setPinCopied] = useState(false);

  useEffect(() => {
    if (!isReady) return;
    setPending(readPendingCheckout(session?.user?.id));
  }, [session, isReady]);

  useEffect(() => {
    if (pending === undefined || pending === null || cancelled) {
      if (pending === null) {
        setLoading(false);
      }
      return;
    }

    let active = true;
    let timer: number | null = null;

    async function loadStatus(currentPending: PendingCheckout) {
      try {
        const [pay, res] = await Promise.all([
          fetchPayment(currentPending.paymentId),
          fetchReservation(currentPending.reservationId),
        ]);
        if (!active) {
          return;
        }

        setPayment(pay);
        setReservation(res);

        // Платёж подтверждён — создаём аренду.
        if (pay.status === "authorized" || pay.status === "captured") {
          const createdRental = await confirmReservation(res.id, pay.id);
          if (!active) {
            return;
          }
          setRental(createdRental);
          clearPendingCheckout();
          setPending(null);
          return;
        }

        // Фоллбэк: вебхук от ЮKassa обновил бронь, но платёж ещё pending
        // в нашей БД (редко, но бывает при задержке обновления кеша).
        if (res.status === "payment_authorized") {
          const createdRental = await confirmReservation(res.id, pay.id);
          if (!active) {
            return;
          }
          setRental(createdRental);
          clearPendingCheckout();
          setPending(null);
          return;
        }

        if (pay.status === "pending") {
          timer = window.setTimeout(() => {
            void loadStatus(currentPending);
          }, 3500);
        }
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Не удалось проверить оплату");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadStatus(pending);

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [cancelled, pending]);

  async function handleDevBypass() {
    if (!pending || !payment || !reservation) {
      return;
    }

    setBusy(true);
    setError("");
    try {
      const updatedPayment = await authorizePaymentDevStub(payment.id);
      const createdRental = await confirmReservation(reservation.id, updatedPayment.id);
      setPayment(updatedPayment);
      setRental(createdRental);
      clearPendingCheckout();
      setPending(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось подтвердить тестовую выдачу");
    } finally {
      setBusy(false);
    }
  }

  async function handleCancelPayment() {
    if (!reservation) {
      return;
    }

    setBusy(true);
    setError("");
    setShowCancelDialog(false);
    try {
      await cancelReservation(reservation.id);
      clearPendingCheckout();
      setCancelled(true);
      setPending(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отменить оплату");
    } finally {
      setBusy(false);
    }
  }

  function handleReschedule() {
    clearPendingCheckout();
    setShowCancelDialog(false);
    router.push("/catalog");
  }

  if (pending === undefined) {
    return <div className="loader">Открываем платеж</div>;
  }

  if (cancelled) {
    return (
      <>
        <PageHeader
          eyebrow="Оплата"
          title="Оплата отменена"
          subtitle="Бронь снята, резерв по оплате больше не ждём."
        />
        <EmptyState
          icon={<ShoppingBag size={34} />}
          title="Можно выбрать другой товар"
          action={
            <Link className="button button-primary" href="/catalog">
              В каталог
            </Link>
          }
        />
      </>
    );
  }

  if (!pending && !rental) {
    return (
      <>
        <PageHeader
          eyebrow="Оплата"
          title="Нет активного платежа"
          subtitle="Не нашли сохраненную бронь для проверки оплаты."
        />
        <EmptyState
          icon={<ShoppingBag size={34} />}
          title="Платеж не найден"
          action={
            <Link className="button button-primary" href="/catalog">
              В каталог
            </Link>
          }
        />
      </>
    );
  }

  const status = rental?.status || payment?.status || "pending";
  const title = rental ? "Оплата подтверждена" : "Проверяем статус";
  const subtitle = rental
    ? "Бронь подтверждена. Перейдите к заказу, чтобы открыть ячейку и забрать товар."
    : "После подтверждения платежа здесь появится ссылка на ваш заказ.";

  return (
    <>
      <PageHeader
        eyebrow="Оплата"
        title={title}
        subtitle={subtitle}
        actions={<StatusPill status={status} />}
      />

      {loading ? <div className="loader">Ждем ответ платежной системы</div> : null}
      {error ? <div className="alert alert-danger">{error}</div> : null}

      <div className="layout-split">
        <Surface className="detail-panel">
          <div className="card-row">
            <span className="icon-badge">
              <CreditCard size={20} />
            </span>
          </div>
          <div>
            <p className="eyebrow">Платеж</p>
            <h2 className="section-title">{formatMoney(payment?.amount, payment?.currency)}</h2>
          </div>
          <div className="meta-list">
            <div className="meta-line">
              <span>Создан</span>
              <strong>{formatDateTime(pending?.createdAt)}</strong>
            </div>

          </div>

          {payment?.status === "pending" ? (
            <div className="alert alert-warn">
              Платеж еще обрабатывается. Бронь подтвердится автоматически после обновления
              статуса.
            </div>
          ) : null}

          {DEV_PAYMENT_BYPASS_ENABLED && payment?.status === "pending" && reservation ? (
            <button
              className="button button-secondary"
              type="button"
              disabled={busy}
              onClick={handleDevBypass}
            >
              {busy ? "Подготовка" : "Тест без оплаты"}
            </button>
          ) : null}

          {!rental && reservation && ["pending", "authorized"].includes(payment?.status || "") ? (
            <button
              className="button button-ghost"
              type="button"
              disabled={busy}
              onClick={() => setShowCancelDialog(true)}
            >
              {busy ? "Отменяем" : "Отменить"}
            </button>
          ) : null}
        </Surface>

        <Surface className="detail-panel sticky-panel">
          <div className="card-row">
            <span className="icon-badge">
              <PackageCheck size={20} />
            </span>
          </div>
          <div>
            <p className="eyebrow">{rental ? "Выдача" : "Бронь"}</p>
            <h2 className="section-title">{reservation?.product?.name || "Товар"}</h2>
          </div>
          <p className="muted">{reservation?.locker?.address}</p>

          {rental ? (
            (() => {
              const PICKUP_LEAD_GRACE_MS = 60 * 60 * 1000;
              const pickupAtStr = reservation?.pickupAt;
              const pickupAtMs = pickupAtStr ? new Date(pickupAtStr).getTime() : 0;
              const tooEarly = pickupAtMs > 0 && Date.now() < pickupAtMs - PICKUP_LEAD_GRACE_MS;
              return (
                <>
                  {!tooEarly && rental.pickupPin ? (
                    <div className="pickup-pin-display" style={{ padding: "16px", backgroundColor: "#f0fdf4", borderRadius: "12px", border: "1px solid #bbf7d0", textAlign: "center", marginBottom: "16px" }}>
                      <div style={{ fontSize: "14px", color: "#166534", marginBottom: "4px" }}>{pinCopied ? "Скопировано ✓" : "Ваш PIN-код:"}</div>
                      <div style={{ fontSize: "32px", fontWeight: "bold", fontFamily: "monospace", color: "#15803d", display: "inline-flex", alignItems: "center", gap: "12px" }}>
                        {rental.pickupPin}
                        <button
                          type="button"
                          className="button button-ghost button-sm"
                          style={{ padding: "6px", minHeight: "unset", minWidth: "unset", borderRadius: "8px", color: "#15803d" }}
                          onClick={() => {
                            navigator.clipboard.writeText(rental.pickupPin);
                            setPinCopied(true);
                            setTimeout(() => setPinCopied(false), 2000);
                          }}
                          title="Скопировать PIN-код"
                        >
                          <Copy size={20} />
                        </button>
                      </div>
                    </div>
                  ) : null}
                  <div className="alert alert-success">
                    {tooEarly
                      ? `Оплата подтверждена. PIN-код появится ближе к дате получения.`
                      : "Оплата прошла успешно. Подойдите к постамату и введите PIN-код для открытия ячейки."}
                  </div>
                  <Link className="button button-primary" href={`/profile/orders/${rental.id}`}>
                    Открыть заказ
                  </Link>
                </>
              );
            })()
          ) : (
            <div className="alert">
              После подтверждения здесь появится переход к заказу.
            </div>
          )}
        </Surface>
      </div>

      {/* Cancel confirmation dialog */}
      {showCancelDialog ? (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-box">
            <div className="modal-icon">
              <RotateCcw size={26} />
            </div>
            <h2 className="modal-title">Отменить бронь?</h2>
            <p className="modal-text">
              Вы уверены, что хотите отменить? Средства вернутся на карту. Вы можете выбрать другой товар и постамат в каталоге.
            </p>
            <div className="modal-actions">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => setShowCancelDialog(false)}
              >
                Назад
              </button>
              <button
                className="button button-secondary"
                type="button"
                onClick={handleReschedule}
              >
                <ArrowLeftRight size={16} />
                Перенести запись
              </button>
              <button
                className="button button-primary"
                type="button"
                disabled={busy}
                onClick={handleCancelPayment}
              >
                {busy ? "Отменяем" : "Да, отменить"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
