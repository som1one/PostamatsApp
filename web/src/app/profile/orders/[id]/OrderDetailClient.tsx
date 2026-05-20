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
import { YandexMap } from "@/components/YandexMap";
import { ApiError } from "@/shared/api/client";
import {
  cancelReservation,
  confirmRentalPickup,
  confirmRentalReturn,
  fetchAllLockers,
  fetchMyReservations,
  fetchReservation,
  fetchRental,
  fetchRentals,
  openRentalCell,
  requestRentalReturn,
} from "@/shared/api/endpoints";
import type {
  Locker,
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
  const [returnLockers, setReturnLockers] = useState<Locker[]>([]);
  const [returnLockerId, setReturnLockerId] = useState("");
  const returnLockerIdRef = useRef("");
  const [returnLockersLoading, setReturnLockersLoading] = useState(false);
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

  useEffect(() => {
    returnLockerIdRef.current = returnLockerId;
  }, [returnLockerId]);

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
    const pickupLockerId =
      order && order.type === "rental" ? order.detail?.pickupLocker.id : "";
    setReturnLockerId(pickupLockerId || "");
    setReturnLockers([]);
    setReturnLockersLoading(true);
    setMessage("");
    setError("");

    void fetchAllLockers()
      .then((items) => {
        const pickup = items.find((locker) => locker.id === pickupLockerId);
        const cityId = pickup?.cityId;
        const sameCity = cityId
          ? items.filter(
              (locker) =>
                locker.cityId === cityId && locker.status === "online",
            )
          : pickup
            ? [pickup]
            : [];
        setReturnLockers(sameCity);
        setReturnLockerId((current) =>
          sameCity.some((locker) => locker.id === current)
            ? current
            : pickup?.id || sameCity[0]?.id || "",
        );
      })
      .catch(() => {
        setReturnLockers([]);
      })
      .finally(() => {
        setReturnLockersLoading(false);
      });

    const confirmed = await askReturnConfirm(rentalId);
    if (!confirmed) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await requestRentalReturn(
        rentalId,
        returnLockerIdRef.current || undefined,
      );
      setMessage(result.return.instructions || "Возврат запущен.");
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "RETURN_LOCKER_DIFFERENT_CITY") {
        setError("Возврат возможен только в постамат того же города.");
      } else if (err instanceof ApiError && err.code === "LOCKER_OFFLINE") {
        setError("Постамат сейчас офлайн. Выберите другую точку.");
      } else if (err instanceof ApiError && err.code === "RETURN_CELL_NOT_AVAILABLE") {
        setError("В выбранном постамате нет свободных ячеек. Попробуйте другой.");
      } else {
        setError(err instanceof Error ? err.message : "Не удалось начать возврат");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleOpenCell(rentalId: string) {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await openRentalCell(rentalId);
      setMessage("Ячейка открыта. Заберите товар.");
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "LOCKER_OFFLINE") {
          setError(
            "Постамат сейчас офлайн. Попробуйте чуть позже — в ночные часы устройство может уходить в режим обслуживания.",
          );
        } else if (err.code === "LOCKER_NOT_CONFIGURED") {
          setError("Постамат пока не привязан к серверу. Обратитесь в поддержку.");
        } else if (err.code === "CELL_NOT_OPERABLE") {
          setError("Ячейка временно неисправна. Обратитесь в поддержку.");
        } else if (err.code === "ESI_OPEN_FAILED") {
          setError("Не удалось открыть ячейку. Попробуйте ещё раз через минуту.");
        } else {
          setError(err.message || "Не удалось открыть ячейку");
        }
      } else {
        setError(err instanceof Error ? err.message : "Не удалось открыть ячейку");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmPickup(rentalId: string) {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await confirmRentalPickup(rentalId);
      setMessage("Спасибо! Аренда началась.");
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "RENTAL_NOT_PICKUP_READY") {
        setError("Сначала нажмите «Открыть ячейку».");
      } else {
        setError(err instanceof Error ? err.message : "Не удалось подтвердить получение");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmReturnDone(rentalId: string) {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await confirmRentalReturn(rentalId);
      setMessage("Возврат принят. Спасибо!");
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "RENTAL_NOT_RETURNING") {
        setError("Сначала оформите возврат и подождите, пока ячейка откроется.");
      } else if (err instanceof ApiError && err.code === "RETURN_REQUEST_NOT_FOUND") {
        setError("Активная заявка на возврат не найдена. Оформите возврат заново.");
      } else {
        setError(err instanceof Error ? err.message : "Не удалось подтвердить возврат");
      }
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

          {/* Action buttons — inline in main panel */}
          <div className="detail-actions">
            {/* Open pickup cell */}
            {!isReservation &&
              ["pickup_ready", "pickup_opened"].includes(order.data.status) ? (
              <>
                <p className="muted detail-actions-hint">
                  Подойдите к постамату и нажмите «Открыть ячейку». Когда заберёте
                  товар, нажмите «Я забрал» — аренда начнётся.
                </p>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={busy}
                  onClick={() => handleOpenCell(order.data.id)}
                >
                  <Key size={18} />
                  Открыть ячейку
                </button>
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => handleConfirmPickup(order.data.id)}
                >
                  <PackageCheck size={18} />
                  Я забрал
                </button>
              </>
            ) : null}

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

            {/* Confirm return — once locker is opened we wait for the user to confirm */}
            {!isReservation && order.data.status === "return_in_progress" ? (
              <>
                <p className="muted detail-actions-hint">
                  Положите товар в открытую ячейку и закройте дверцу. Затем нажмите
                  «Я вернул товар», чтобы завершить аренду.
                </p>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={busy}
                  onClick={() => handleConfirmReturnDone(order.data.id)}
                >
                  <CheckCircle2 size={18} />
                  Я вернул товар
                </button>
              </>
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
          <div className="modal-box modal-box-wide">
            <div className="modal-icon">
              <RotateCcw size={28} />
            </div>
            <h2 className="modal-title">Куда вернуть товар?</h2>
            <p className="modal-text">
              Можно вернуть в любой постамат того же города. После подтверждения ячейка
              откроется физически — убедитесь, что вы уже у выбранной точки, положите
              предмет и закройте дверцу.
            </p>
            <div className="return-locker-picker">
              <div className="return-locker-list">
                {returnLockersLoading && !returnLockers.length ? (
                  <div className="muted small">Загружаем постаматы…</div>
                ) : null}
                {!returnLockersLoading && !returnLockers.length ? (
                  <div className="muted small">
                    Не удалось загрузить список — будет использован постамат выдачи.
                  </div>
                ) : null}
                {returnLockers.map((locker) => {
                  const isSelected = returnLockerId === locker.id;
                  return (
                    <button
                      type="button"
                      key={locker.id}
                      className={`product-locker-card ${isSelected ? "is-selected" : ""}`}
                      onClick={() => setReturnLockerId(locker.id)}
                    >
                      <div className="product-locker-card-row">
                        <strong>{locker.name}</strong>
                        {isSelected ? <em>Выбран</em> : null}
                      </div>
                      <span>{locker.address}</span>
                    </button>
                  );
                })}
              </div>
              {returnLockers.length ? (
                <div className="return-locker-map">
                  <YandexMap
                    lockers={returnLockers}
                    selectedLockerId={returnLockerId}
                    onSelectLocker={setReturnLockerId}
                  />
                </div>
              ) : null}
            </div>
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
                disabled={!returnLockerId}
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
