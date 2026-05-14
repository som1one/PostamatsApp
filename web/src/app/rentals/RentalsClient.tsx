"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  CreditCard,
  ImageIcon,
  MapPin,
  PackageCheck,
  RotateCcw,
  XCircle,
  ArrowLeftRight,
  type LucideIcon,
} from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import {
  cancelReservation,
  createPaymentPreauth,
  fetchMyReservations,
  fetchReservation,
  fetchRentals,
  requestRentalReturn,
} from "@/shared/api/endpoints";
import type { RentalListItem, UpcomingReservation } from "@/shared/api/types";
import { writePendingCheckout } from "@/shared/checkout/pending";
import { buildRescheduleProductHref } from "@/shared/checkout/reschedule";
import { formatCountRu, formatDateTime } from "@/shared/format";
import { resolvePublicAssetUrl } from "@/shared/media";

const DEV_PAYMENT_BYPASS_ENABLED =
  process.env.NEXT_PUBLIC_ENABLE_DEV_PAYMENT_BYPASS === "true";

const filters = [
  { value: "", label: "Все" },
  { value: "active", label: "Активные" },
  { value: "completed", label: "Завершённые" },
  { value: "cancelled", label: "Отменённые" },
];

type DeadlineMeta = {
  tone: "warn" | "danger" | "success";
  title: string;
  text: string;
  Icon: LucideIcon;
};

function formatDurationLabel(diffMs: number) {
  const totalMinutes = Math.max(1, Math.ceil(Math.abs(diffMs) / 60_000));
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;
  const parts: string[] = [];

  if (days > 0) {
    parts.push(formatCountRu(days, ["день", "дня", "дней"]));
  }
  if (hours > 0) {
    parts.push(formatCountRu(hours, ["час", "часа", "часов"]));
  }
  if (days === 0 && minutes > 0) {
    parts.push(formatCountRu(minutes, ["минута", "минуты", "минут"]));
  }

  return parts.join(" ");
}

function getReservationDeadlineMeta(reservation: UpcomingReservation, nowMs: number): DeadlineMeta | null {
  const expiresMs = new Date(reservation.expiresAt).getTime();
  if (Number.isNaN(expiresMs)) {
    return null;
  }

  const diffMs = expiresMs - nowMs;
  const duration = formatDurationLabel(diffMs);

  if (diffMs <= 0) {
    return {
      tone: "danger",
      title: `Бронь истекла ${duration} назад`,
      text: "Эта бронь уже недоступна для выдачи.",
      Icon: AlertTriangle,
    };
  }

  if (reservation.status === "payment_authorized") {
    return {
      tone: "success",
      title: `До выдачи: ${duration}`,
      text: `Оплата подтверждена. Заберите до ${formatDateTime(reservation.expiresAt)}.`,
      Icon: CheckCircle2,
    };
  }

  return {
    tone: "warn",
    title: `До отмены брони: ${duration}`,
    text: `Оплатите и заберите до ${formatDateTime(reservation.expiresAt)}.`,
    Icon: Clock3,
  };
}

function getRentalDeadlineMeta(rental: RentalListItem, nowMs: number): DeadlineMeta | null {
  if (rental.status === "return_in_progress") {
    return {
      tone: "success",
      title: "Возврат уже начат",
      text: "Завершите возврат через открытую ячейку постамата.",
      Icon: CheckCircle2,
    };
  }

  if (!rental.plannedEndAt) {
    return null;
  }

  const plannedEndMs = new Date(rental.plannedEndAt).getTime();
  if (Number.isNaN(plannedEndMs)) {
    return null;
  }

  const diffMs = plannedEndMs - nowMs;
  const duration = formatDurationLabel(diffMs);

  if (rental.status === "overdue" || diffMs <= 0) {
    return {
      tone: "danger",
      title: `Просрочено на ${duration}`,
      text: "Стоит оформить возврат как можно скорее.",
      Icon: AlertTriangle,
    };
  }

  if (["pickup_ready", "pickup_opened", "active"].includes(rental.status)) {
    return {
      tone: "warn",
      title: `До возврата: ${duration}`,
      text: `Вернуть до ${formatDateTime(rental.plannedEndAt)}`,
      Icon: Clock3,
    };
  }

  return null;
}

export function RentalsClient() {
  return (
    <PageChrome>
      <RequireAuth>
        <RentalsContent />
      </RequireAuth>
    </PageChrome>
  );
}

function RentalsContent() {
  const router = useRouter();
  const [status, setStatus] = useState("");
  const [reservations, setReservations] = useState<UpcomingReservation[]>([]);
  const [rentals, setRentals] = useState<RentalListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());

  // Per-card busy state: maps item id → true
  const [busyIds, setBusyIds] = useState<Record<string, boolean>>({});
  const [cardError, setCardError] = useState<Record<string, string>>({});

  // Refund dialog (payment_authorized cancel)
  const [showRefundDialog, setShowRefundDialog] = useState(false);
  const [pendingCancelId, setPendingCancelId] = useState<string | null>(null);

  // Return confirm dialog
  const [returnConfirmId, setReturnConfirmId] = useState<string | null>(null);
  const confirmResolveRef = useRef<((ok: boolean) => void) | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextReservations, nextRentals] = await Promise.all([
        fetchMyReservations(),
        fetchRentals(status || undefined),
      ]);
      setReservations(nextReservations);
      setRentals(nextRentals);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить заказы");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  function setBusy(id: string, value: boolean) {
    setBusyIds((prev) => ({ ...prev, [id]: value }));
  }

  function setItemError(id: string, msg: string) {
    setCardError((prev) => ({ ...prev, [id]: msg }));
  }

  // ── Pay reservation ──────────────────────────────────────────
  async function handlePay(reservation: UpcomingReservation, e: React.MouseEvent) {
    e.stopPropagation();
    setBusy(reservation.id, true);
    setItemError(reservation.id, "");
    try {
      const returnUrl = `${window.location.origin}/payment/return`;
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
      } else {
        router.push("/payment/return");
      }
    } catch (err) {
      setItemError(reservation.id, err instanceof Error ? err.message : "Не удалось создать платёж");
      setBusy(reservation.id, false);
    }
  }

  // ── Cancel reservation ───────────────────────────────────────
  function handleCancelClick(reservation: UpcomingReservation, e: React.MouseEvent) {
    e.stopPropagation();
    if (reservation.status === "payment_authorized") {
      setPendingCancelId(reservation.id);
      setShowRefundDialog(true);
      return;
    }
    void doCancel(reservation.id);
  }

  async function doCancel(reservationId: string) {
    setBusy(reservationId, true);
    setItemError(reservationId, "");
    try {
      const result = await cancelReservation(reservationId);
      setReservations((prev) =>
        prev.map((r) =>
          r.id === reservationId
            ? { ...r, status: result.reservation.status, cancelledAt: result.reservation.cancelledAt ?? null }
            : r,
        ),
      );
    } catch (err) {
      setItemError(reservationId, err instanceof Error ? err.message : "Не удалось отменить бронь");
    } finally {
      setBusy(reservationId, false);
    }
  }

  function handleRefundConfirm() {
    if (!pendingCancelId) return;
    const id = pendingCancelId;
    setShowRefundDialog(false);
    setPendingCancelId(null);
    void doCancel(id);
  }

  async function handleReschedule(reservationIdArg?: string) {
    setShowRefundDialog(false);
    const reservationId = reservationIdArg || pendingCancelId;
    setPendingCancelId(null);

    if (!reservationId) {
      router.push("/catalog");
      return;
    }

    try {
      const reservation = await fetchReservation(reservationId);
      const href = buildRescheduleProductHref(reservation);
      router.push(href || "/catalog");
    } catch {
      router.push("/catalog");
    }
  }

  // ── Return rental ────────────────────────────────────────────
  function askReturnConfirm(rentalId: string): Promise<boolean> {
    return new Promise((resolve) => {
      confirmResolveRef.current = resolve;
      setReturnConfirmId(rentalId);
    });
  }

  function handleConfirmReturn(ok: boolean) {
    setReturnConfirmId(null);
    confirmResolveRef.current?.(ok);
    confirmResolveRef.current = null;
  }

  async function handleReturn(rentalId: string, e: React.MouseEvent) {
    e.stopPropagation();
    const confirmed = await askReturnConfirm(rentalId);
    if (!confirmed) return;
    setBusy(rentalId, true);
    setItemError(rentalId, "");
    try {
      await requestRentalReturn(rentalId);
      await load();
    } catch (err) {
      setItemError(rentalId, err instanceof Error ? err.message : "Не удалось начать возврат");
    } finally {
      setBusy(rentalId, false);
    }
  }

  const hasOrders = reservations.length > 0 || rentals.length > 0;

  return (
    <>
      <PageHeader
        eyebrow="Заказы"
        title="Мои заказы"
        subtitle="Будущие брони, активные аренды, история и возврат через доступные постаматы."
        actions={
          <select className="select" value={status} onChange={(event) => setStatus(event.target.value)}>
            {filters.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        }
      />

      {error ? <div className="alert alert-danger">{error}</div> : null}

      {loading ? (
        <div className="loader">Загружаем заказы</div>
      ) : hasOrders ? (
        <div className="product-grid orders-grid">
          {reservations.map((reservation) => {
                  const deadlineMeta = getReservationDeadlineMeta(reservation, nowMs);
                  const busy = busyIds[reservation.id] ?? false;
                  const itemErr = cardError[reservation.id] ?? "";
                  const canPay = ["created", "awaiting_payment"].includes(reservation.status);
                  const canCancel = ["created", "awaiting_payment", "payment_authorized"].includes(reservation.status);
                  const showActions = canPay || canCancel;

                  return (
                    <div
                      key={reservation.id}
                      className="product-card-clickable"
                      onClick={() => router.push(`/profile/orders/${reservation.id}`)}
                      role="article"
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && router.push(`/profile/orders/${reservation.id}`)}
                    >
                    <Surface className="product-card">
                      <div className="product-cover">
                        {resolvePublicAssetUrl(reservation.product.coverUrl) ? (
                          <img
                            src={resolvePublicAssetUrl(reservation.product.coverUrl) || undefined}
                            alt={reservation.product.name || "Товар"}
                          />
                        ) : (
                          <ImageIcon size={44} color="#dd362d" />
                        )}
                      </div>
                      <div className="product-body">
                        <div className="card-row">
                          <span className="icon-badge">
                            <PackageCheck size={20} />
                          </span>
                          <StatusPill status={reservation.status} />
                        </div>
                        <div>
                          <p className="eyebrow">Будущая бронь</p>
                          <h2 className="section-title">{reservation.product.name || "Товар"}</h2>
                        </div>
                        <div className="timeline">
                          <div className="timeline-item">
                            <span className="timeline-dot">
                              <MapPin size={17} />
                            </span>
                            <div>
                              <strong>{reservation.locker.name || "Постамат выдачи"}</strong>
                              <p className="muted small">{reservation.locker.address || "Адрес уточняется"}</p>
                            </div>
                          </div>
                        </div>
                        {deadlineMeta ? (
                          <div className={`rental-deadline rental-deadline-${deadlineMeta.tone}`}>
                            <deadlineMeta.Icon size={16} />
                            <div>
                              <strong>{deadlineMeta.title}</strong>
                            </div>
                          </div>
                        ) : null}
                        {itemErr ? (
                          <p className="muted small" style={{ color: "var(--danger, #dd362d)" }}>{itemErr}</p>
                        ) : null}
                        {showActions ? (
                          <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                            {canPay ? (
                              <button
                                className="button button-primary button-sm"
                                type="button"
                                disabled={busy}
                                onClick={(e) => handlePay(reservation, e)}
                              >
                                <CreditCard size={15} />
                                {busy ? "Открываем оплату…" : "Оплатить"}
                              </button>
                            ) : null}
                            {reservation.status === "payment_authorized" ? (
                              <button
                                className="button button-secondary button-sm"
                                type="button"
                                disabled={busy}
                                onClick={(e) => { e.stopPropagation(); void handleReschedule(reservation.id); }}
                              >
                                <ArrowLeftRight size={15} />
                                Перенести
                              </button>
                            ) : null}
                            {canCancel ? (
                              <button
                                className="button button-ghost button-sm"
                                type="button"
                                disabled={busy}
                                onClick={(e) => handleCancelClick(reservation, e)}
                              >
                                <XCircle size={15} />
                                {reservation.status === "payment_authorized" ? "Вернуть деньги" : "Отменить"}
                              </button>
                            ) : null}
                          </div>
                        ) : null}
                        {DEV_PAYMENT_BYPASS_ENABLED && canPay ? (
                          <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                            <span className="muted small">dev: любой код подойдёт</span>
                          </div>
                        ) : null}
                      </div>
                    </Surface>
                    </div>
                  );
                })}

          {rentals.map((rental) => {
                  const deadlineMeta = getRentalDeadlineMeta(rental, nowMs);
                  const busy = busyIds[rental.id] ?? false;
                  const itemErr = cardError[rental.id] ?? "";
                  const canReturn = ["active", "overdue"].includes(rental.status);

                  return (
                    <div
                      key={rental.id}
                      className="product-card-clickable"
                      onClick={() => router.push(`/profile/orders/${rental.id}`)}
                      role="article"
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && router.push(`/profile/orders/${rental.id}`)}
                    >
                    <Surface className="product-card">
                      <div className="product-cover">
                        {resolvePublicAssetUrl(rental.product.coverUrl) ? (
                          <img
                            src={resolvePublicAssetUrl(rental.product.coverUrl) || undefined}
                            alt={rental.product.name || "Товар"}
                          />
                        ) : (
                          <ImageIcon size={44} color="#dd362d" />
                        )}
                      </div>
                      <div className="product-body">
                        <div className="card-row">
                          <span className="icon-badge">
                            <PackageCheck size={20} />
                          </span>
                          <StatusPill status={rental.status} />
                        </div>
                        <div>
                          <p className="eyebrow">{rental.locker.name}</p>
                          <h2 className="section-title">{rental.product.name || "Товар"}</h2>
                        </div>
                        {deadlineMeta ? (
                          <div className={`rental-deadline rental-deadline-${deadlineMeta.tone}`}>
                            <deadlineMeta.Icon size={16} />
                            <div>
                              <strong>{deadlineMeta.title}</strong>
                            </div>
                          </div>
                        ) : null}
                        {itemErr ? (
                          <p className="muted small" style={{ color: "var(--danger, #dd362d)" }}>{itemErr}</p>
                        ) : null}
                        {canReturn ? (
                          <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                            <button
                              className="button button-secondary button-sm"
                              type="button"
                              disabled={busy}
                              onClick={(e) => handleReturn(rental.id, e)}
                            >
                              <RotateCcw size={15} />
                              {busy ? "Открываем ячейку…" : "Оформить возврат"}
                            </button>
                          </div>
                        ) : null}
                      </div>
                    </Surface>
                    </div>
                  );
                })}
        </div>
      ) : (
        <EmptyState
          icon={<PackageCheck size={34} />}
          title="Заказов пока нет"
          text="После первого оформления здесь появятся будущие брони и активные аренды."
        />
      )}

      {/* Refund confirmation dialog */}
      {showRefundDialog ? (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-box">
            <div className="modal-icon">
              <XCircle size={26} />
            </div>
            <h2 className="modal-title">Вернуть деньги?</h2>
            <p className="modal-text">
              Вы уверены, что хотите вернуть деньги? Вы можете перенести запись на другое время в следующем шаге.
            </p>
            <div className="modal-actions">
              <div className="modal-actions-row">
                <button
                  className="button button-secondary"
                  type="button"
                  onClick={() => void handleReschedule()}
                >
                  <ArrowLeftRight size={16} />
                  Перенести запись
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={pendingCancelId ? (busyIds[pendingCancelId] ?? false) : false}
                  onClick={handleRefundConfirm}
                >
                  Да, вернуть деньги
                </button>
              </div>
              <div className="modal-back">
                <button
                  type="button"
                  onClick={() => { setShowRefundDialog(false); setPendingCancelId(null); }}
                >
                  Назад
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* Return confirmation dialog */}
      {returnConfirmId !== null ? (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-box">
            <div className="modal-icon">
              <RotateCcw size={26} />
            </div>
            <h2 className="modal-title">Начать возврат?</h2>
            <p className="modal-text">
              Убедитесь, что вы уже находитесь у постамата. После подтверждения ячейка откроется физически — положите предмет и закройте дверцу.
            </p>
            <div className="modal-actions">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => handleConfirmReturn(false)}
              >
                Отмена
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={() => handleConfirmReturn(true)}
              >
                Да, я у постамата
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
