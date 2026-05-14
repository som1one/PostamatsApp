"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowLeftRight,
  CheckCircle2,
  Clock3,
  ImageIcon,
  Key,
  MapPin,
  PackageCheck,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { PageChrome } from "@/components/PageChrome";
import { PageHeader } from "@/components/PageHeader";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusPill } from "@/components/StatusPill";
import { Surface } from "@/components/Surface";
import { ApiError } from "@/shared/api/client";
import {
  cancelReservation,
  fetchMyReservations,
  fetchReservation,
  fetchRental,
  fetchRentals,
  requestRentalReturn,
} from "@/shared/api/endpoints";
import type {
  RentalDetail,
  RentalListItem,
  ReservationSummary,
  UpcomingReservation,
} from "@/shared/api/types";
import { buildRescheduleProductHref } from "@/shared/checkout/reschedule";
import { formatCountRu, formatDateTime } from "@/shared/format";
import { resolvePublicAssetUrl } from "@/shared/media";

type OrderData =
  | { type: "reservation"; data: UpcomingReservation; detail?: ReservationSummary | null }
  | { type: "rental"; data: RentalListItem; detail?: RentalDetail };

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

function getReservationCancelMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === "RESERVATION_NOT_CANCELLABLE") {
      return "Эту бронь уже нельзя отменить вручную.";
    }
    if (error.code === "RESERVATION_CANCEL_FAILED") {
      return "Не удалось отменить бронь. Попробуйте ещё раз.";
    }
    if (error.code === "YOOKASSA_CANCEL_FAILED") {
      return "Не удалось отменить платёж в платёжной системе. Попробуйте позже или обратитесь в поддержку.";
    }
  }

  return error instanceof Error ? error.message : "Не удалось отменить бронь";
}

export function OrderDetailClient({ id }: { id: string }) {
  return (
    <PageChrome>
      <RequireAuth>
        <OrderDetailContent id={id} />
      </RequireAuth>
    </PageChrome>
  );
}

function OrderDetailContent({ id }: { id: string }) {
  const router = useRouter();
  const [order, setOrder] = useState<OrderData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [returnConfirmId, setReturnConfirmId] = useState<string | null>(null);
  const confirmResolveRef = useRef<((ok: boolean) => void) | null>(null);
  // Dialog for cancelling a paid reservation (payment_authorized)
  const [showRefundDialog, setShowRefundDialog] = useState(false);
  const [pendingCancelId, setPendingCancelId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // Try to find as rental first (has detail endpoint)
      try {
        const rentalDetail = await fetchRental(id);
        // Also get list item for consistent data
        const rentals = await fetchRentals();
        const listItem = rentals.find((r) => r.id === id);
        if (listItem) {
          setOrder({ type: "rental", data: listItem, detail: rentalDetail });
        } else {
          // Build a minimal list item from detail
          setOrder({
            type: "rental",
            data: {
              id: rentalDetail.id,
              status: rentalDetail.status,
              plannedEndAt: rentalDetail.plannedEndAt,
              actualEndAt: rentalDetail.actualEndAt,
              product: rentalDetail.product,
              locker: rentalDetail.pickupLocker,
            },
            detail: rentalDetail,
          });
        }
        return;
      } catch {
        // Not a rental, try reservation
      }

      const reservations = await fetchMyReservations();
      const reservation = reservations.find((r) => r.id === id);
      if (reservation) {
        let detail: ReservationSummary | null = null;
        try {
          detail = await fetchReservation(id);
        } catch {
          detail = null;
        }
        setOrder({ type: "reservation", data: reservation, detail });
        return;
      }

      setError("Заказ не найден");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить заказ");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 60_000);
    return () => window.clearInterval(timer);
  }, []);

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

  async function handleReturn(rentalId: string) {
    const confirmed = await askReturnConfirm(rentalId);
    if (!confirmed) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await requestRentalReturn(rentalId);
      setMessage(result.return.instructions || "Возврат запущен.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось начать возврат");
    } finally {
      setBusy(false);
    }
  }

  // Called when user clicks cancel button
  function handleCancelClick(reservationId: string, status: string) {
    // For paid reservations — show refund dialog first
    if (status === "payment_authorized") {
      setPendingCancelId(reservationId);
      setShowRefundDialog(true);
      return;
    }
    // For unpaid reservations — cancel immediately
    void doCancel(reservationId);
  }

  async function doCancel(reservationId: string) {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await cancelReservation(reservationId);
      setOrder((current) => {
        if (!current || current.type !== "reservation" || current.data.id !== reservationId) {
          return current;
        }

        return {
          type: "reservation",
          detail: current.detail ?? null,
          data: {
            ...current.data,
            status: result.reservation.status,
            cancelledAt: result.reservation.cancelledAt ?? null,
            cancelReason: "cancelled_by_user",
          },
        };
      });
      setMessage("Бронь отменена.");
    } catch (err) {
      setError(getReservationCancelMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function handleRefundConfirm() {
    if (!pendingCancelId) return;
    const id = pendingCancelId;
    setShowRefundDialog(false);
    setPendingCancelId(null);
    void doCancel(id);
  }

  async function handleReschedule() {
    setShowRefundDialog(false);
    setPendingCancelId(null);

    if (!order || order.type !== "reservation") {
      router.push("/catalog");
      return;
    }

    let detail = order.detail ?? null;
    if (!detail) {
      try {
        detail = await fetchReservation(order.data.id);
        setOrder((current) =>
          current && current.type === "reservation" && current.data.id === order.data.id
            ? { ...current, detail }
            : current,
        );
      } catch {
        detail = null;
      }
    }

    const href = detail ? buildRescheduleProductHref(detail) : null;
    router.push(href || `/catalog/${order.data.product.id}`);
  }

  if (loading) {
    return (
      <>
        <PageHeader eyebrow="Заказы" title="Загрузка..." />
        <div className="loader">Загружаем заказ</div>
      </>
    );
  }

  if (!order) {
    return (
      <>
        <PageHeader eyebrow="Заказы" title="Заказ не найден" />
        {error ? <div className="alert alert-danger">{error}</div> : null}
        <Link href="/profile/orders" className="button button-secondary">
          <ArrowLeft size={18} />
          Назад к заказам
        </Link>
      </>
    );
  }

  const isReservation = order.type === "reservation";
  const productName = isReservation
    ? order.detail?.product?.name || order.data.product.name || "Товар"
    : order.data.product.name || "Товар";
  const coverUrl = isReservation
    ? resolvePublicAssetUrl(order.detail?.product?.coverUrl || order.data.product.coverUrl)
    : resolvePublicAssetUrl(order.data.product.coverUrl);
  const status = isReservation ? order.data.status : order.data.status;

  return (
    <>
      <PageHeader
        eyebrow="Заказы"
        title={productName}
        actions={<StatusPill status={status} />}
      />

      <Link href="/profile/orders" className="button button-secondary" style={{ marginBottom: 18 }}>
        <ArrowLeft size={18} />
        Назад к заказам
      </Link>

      {message ? <div className="alert">{message}</div> : null}
      {error ? <div className="alert alert-danger">{error}</div> : null}

      <div className="order-detail-layout">
        {/* Main info panel */}
        <Surface className="detail-panel order-detail-card">
          <div className="product-cover" style={{ borderRadius: 16, maxHeight: 320 }}>
            {coverUrl ? (
              <img src={coverUrl || undefined} alt={productName} />
            ) : (
              <ImageIcon size={44} color="#dd362d" />
            )}
          </div>

          <div className="meta-list">
            {isReservation ? (
              <>
                <div className="meta-line">
                  <span>Постамат</span>
                  <strong>{order.data.locker.name || "—"}</strong>
                </div>
                <div className="meta-line">
                  <span>Адрес</span>
                  <strong>{order.data.locker.address || "—"}</strong>
                </div>
                <div className="meta-line">
                  <span>Забрать до</span>
                  <strong>{formatDateTime(order.data.expiresAt)}</strong>
                </div>
                {order.data.cancelledAt ? (
                  <div className="meta-line">
                    <span>Отменена</span>
                    <strong>{formatDateTime(order.data.cancelledAt)}</strong>
                  </div>
                ) : null}
                {order.data.status === "cancelled" ? (
                  <div className="rental-deadline rental-deadline-success">
                    <CheckCircle2 size={16} />
                    <div>
                      <strong>Бронь отменена</strong>
                      <span>Постамат и товар больше не зарезервированы за вами.</span>
                    </div>
                  </div>
                ) : (
                  (() => {
                  const expiresMs = new Date(order.data.expiresAt).getTime();
                  const diffMs = expiresMs - nowMs;
                  if (Number.isNaN(expiresMs)) return null;
                  const duration = formatDurationLabel(diffMs);
                  if (diffMs <= 0) {
                    return (
                      <div className="rental-deadline rental-deadline-danger">
                        <AlertTriangle size={16} />
                        <div>
                          <strong>Бронь истекла {duration} назад</strong>
                          <span>Эта бронь уже недоступна для выдачи.</span>
                        </div>
                      </div>
                    );
                  }
                  if (order.data.status === "payment_authorized") {
                    return (
                      <div className="rental-deadline rental-deadline-success">
                        <CheckCircle2 size={16} />
                        <div>
                          <strong>До выдачи: {duration}</strong>
                          <span>Оплата подтверждена. Заберите до {formatDateTime(order.data.expiresAt)}.</span>
                        </div>
                      </div>
                    );
                  }
                  return (
                    <div className="rental-deadline rental-deadline-warn">
                      <Clock3 size={16} />
                      <div>
                        <strong>До отмены брони: {duration}</strong>
                        <span>Оплатите и заберите до {formatDateTime(order.data.expiresAt)}.</span>
                      </div>
                    </div>
                  );
                  })()
                )}
              </>
            ) : (
              <>
                <div className="meta-line">
                  <span>Постамат</span>
                  <strong>{order.data.locker.name || "—"}</strong>
                </div>
                {order.detail?.pickupLocker?.address ? (
                  <div className="meta-line">
                    <span>Адрес</span>
                    <strong>{order.detail.pickupLocker.address}</strong>
                  </div>
                ) : null}
                {order.detail?.startsAt ? (
                  <div className="meta-line">
                    <span>Начало аренды</span>
                    <strong>{formatDateTime(order.detail.startsAt)}</strong>
                  </div>
                ) : null}
                <div className="meta-line">
                  <span>Плановое окончание</span>
                  <strong>{formatDateTime(order.data.plannedEndAt)}</strong>
                </div>
                {order.data.actualEndAt ? (
                  <div className="meta-line">
                    <span>Фактическое окончание</span>
                    <strong>{formatDateTime(order.data.actualEndAt)}</strong>
                  </div>
                ) : null}
                {(() => {
                  const rental = order.data;
                  if (rental.status === "return_in_progress") {
                    return (
                      <div className="rental-deadline rental-deadline-success">
                        <CheckCircle2 size={16} />
                        <div>
                          <strong>Возврат уже начат</strong>
                          <span>Завершите возврат через открытую ячейку постамата.</span>
                        </div>
                      </div>
                    );
                  }
                  if (!rental.plannedEndAt) return null;
                  const plannedEndMs = new Date(rental.plannedEndAt).getTime();
                  if (Number.isNaN(plannedEndMs)) return null;
                  const diffMs = plannedEndMs - nowMs;
                  const duration = formatDurationLabel(diffMs);
                  if (rental.status === "overdue" || diffMs <= 0) {
                    return (
                      <div className="rental-deadline rental-deadline-danger">
                        <AlertTriangle size={16} />
                        <div>
                          <strong>Просрочено на {duration}</strong>
                          <span>Стоит оформить возврат как можно скорее.</span>
                        </div>
                      </div>
                    );
                  }
                  if (["pickup_ready", "pickup_opened", "active"].includes(rental.status)) {
                    return (
                      <div className="rental-deadline rental-deadline-warn">
                        <Clock3 size={16} />
                        <div>
                          <strong>До возврата: {duration}</strong>
                          <span>Вернуть до {formatDateTime(rental.plannedEndAt)}</span>
                        </div>
                      </div>
                    );
                  }
                  return null;
                })()}
              </>
            )}
          </div>

          {/* PIN for rental — moved into main panel */}
          {!isReservation && order.detail?.pickupPin ? (
            <div className="alert">
              <Key size={18} style={{ marginRight: 8 }} />
              <strong>PIN для получения: {order.detail.pickupPin}</strong>
            </div>
          ) : null}

          {/* Payment info for rental */}
          {!isReservation && order.detail?.paymentSummary ? (
            <div className="meta-list">
              <div className="meta-line">
                <span>Преавторизация</span>
                <strong>
                  {(order.detail.paymentSummary.preauthAmount / 100).toFixed(0)} ₽
                </strong>
              </div>
              <div className="meta-line">
                <span>Списано</span>
                <strong>
                  {(order.detail.paymentSummary.capturedAmount / 100).toFixed(0)} ₽
                </strong>
              </div>
            </div>
          ) : null}

          {/* Action buttons — inline in main panel */}
          <div className="detail-actions">
            {/* Reschedule button for paid reservation */}
            {isReservation && order.data.status === "payment_authorized" ? (
              <button
                className="button button-secondary"
                type="button"
                disabled={busy}
                onClick={handleReschedule}
              >
                <ArrowLeftRight size={18} />
                Перенести
              </button>
            ) : null}

            {/* Cancel reservation */}
            {isReservation &&
              ["created", "awaiting_payment", "payment_authorized"].includes(order.data.status) ? (
              <button
                className="button button-secondary"
                type="button"
                disabled={busy}
                onClick={() => handleCancelClick(order.data.id, order.data.status)}
              >
                <XCircle size={18} />
                {order.data.status === "payment_authorized"
                  ? "Вернуть деньги"
                  : "Отменить бронь"}
              </button>
            ) : null}

            {/* Return rental */}
            {!isReservation && ["active", "overdue"].includes(order.data.status) ? (
              <button
                className="button button-secondary"
                type="button"
                disabled={busy}
                onClick={() => handleReturn(order.data.id)}
              >
                <RotateCcw size={18} />
                Оформить возврат
              </button>
            ) : null}

            {/* Cancelled due to pickup expired */}
            {!isReservation &&
              order.data.status === "cancelled" &&
              order.data.cancelReason === "pickup_expired" ? (
              <div className="rental-deadline rental-deadline-warn">
                <RefreshCw size={16} />
                <div>
                  <strong>Время получения истекло</strong>
                  <span>
                    Вы не забрали товар вовремя. Хотите выбрать другой?{" "}
                    <Link href="/catalog" className="link">
                      Перейти в каталог
                    </Link>
                  </span>
                </div>
              </div>
            ) : null}
          </div>
        </Surface>
      </div>

      {/* Return confirmation modal */}
      {returnConfirmId !== null ? (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-box">
            <div className="modal-icon">
              <RotateCcw size={28} />
            </div>
            <h2 className="modal-title">Начать возврат?</h2>
            <p className="modal-text">
              Убедитесь, что вы уже находитесь у постамата. После подтверждения ячейка откроется
              физически — положите предмет и закройте дверцу.
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

      {/* Refund confirmation modal (for payment_authorized reservations) */}
      {showRefundDialog ? (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-box">
            <div className="modal-icon">
              <XCircle size={28} />
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
                  onClick={handleReschedule}
                >
                  <ArrowLeftRight size={16} />
                  Перенести запись
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={busy}
                  onClick={handleRefundConfirm}
                >
                  {busy ? "Отменяем" : "Да, вернуть деньги"}
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
    </>
  );
}
