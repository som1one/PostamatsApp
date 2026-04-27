"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CreditCard, PackageCheck, ShoppingBag } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import {
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
  const [pending, setPending] = useState<PendingCheckout | null | undefined>(
    undefined,
  );

  useEffect(() => {
    setPending(readPendingCheckout());
  }, []);

  useEffect(() => {
    if (pending === undefined) {
      return;
    }
    if (pending === null) {
      setLoading(false);
      return;
    }

    let active = true;
    let timer: number | null = null;
    const currentPending = pending;

    async function load() {
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

        if (pay.status === "authorized" || pay.status === "captured") {
          const createdRental = await confirmReservation(res.id, pay.id);
          if (!active) {
            return;
          }
          setRental(createdRental);
          clearPendingCheckout();
          return;
        }

        if (pay.status === "pending") {
          timer = window.setTimeout(load, 3500);
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

    void load();

    return () => {
      active = false;
      if (timer) {
        window.clearTimeout(timer);
      }
    };
  }, [pending]);

  if (pending === undefined) {
    return <div className="loader">Открываем платёж</div>;
  }

  if (!pending) {
    return (
      <>
        <PageHeader
          eyebrow="Оплата"
          title="Нет активного платежа"
          subtitle="Локальный checkout не нашёл сохранённую бронь для проверки."
        />
        <EmptyState
          icon={<ShoppingBag size={34} />}
          title="Платёж не найден"
          action={
            <Link className="button button-primary" href="/catalog">
              В каталог
            </Link>
          }
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Оплата"
        title={rental ? "Бронь подтверждена" : "Проверяем статус"}
        subtitle="После подтверждения платежа здесь появятся PIN и ссылка на аренды."
        actions={<StatusPill status={rental?.status || payment?.status || "pending"} />}
      />

      {loading ? <div className="loader">Ждём ответ платёжной системы</div> : null}
      {error ? <div className="alert alert-danger">{error}</div> : null}

      <div className="layout-split">
        <Surface className="detail-panel">
          <div className="card-row">
            <span className="icon-badge">
              <CreditCard size={20} />
            </span>
            <StatusPill status={payment?.status || "pending"} />
          </div>
          <div>
            <p className="eyebrow">Платёж</p>
            <h2 className="section-title">{formatMoney(payment?.amount, payment?.currency)}</h2>
          </div>
          <div className="meta-list">
            <div className="meta-line">
              <span>Создан</span>
              <strong>{formatDateTime(pending.createdAt)}</strong>
            </div>
            <div className="meta-line">
              <span>ID платежа</span>
              <strong>{pending.paymentId}</strong>
            </div>
          </div>
          {payment?.status === "pending" ? (
            <div className="alert alert-warn">
              Платёж ещё обрабатывается. Бронь подтвердится автоматически после обновления
              статуса.
            </div>
          ) : null}
        </Surface>

        <Surface className="detail-panel sticky-panel">
          <div className="card-row">
            <span className="icon-badge">
              <PackageCheck size={20} />
            </span>
            <StatusPill status={reservation?.status || rental?.status || "pending"} />
          </div>
          <div>
            <p className="eyebrow">Бронь</p>
            <h2 className="section-title">{reservation?.product?.name || "Товар"}</h2>
          </div>
          <p className="muted">{reservation?.locker?.address}</p>
          {rental ? (
            <>
              <div className="alert">
                <strong>PIN: {rental.pickupPin}</strong>
              </div>
              <Link className="button button-primary" href="/rentals">
                Мои аренды
              </Link>
            </>
          ) : null}
        </Surface>
      </div>
    </>
  );
}
